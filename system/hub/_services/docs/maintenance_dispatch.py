"""Bounded documentation dispatch through the canonical Task API.

This is a consumer executor for ellmos-scheduler, not a task store or an LLM
launcher. Cached state contains references; task/result authority stays native.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

STATE_SCHEMA = "bach.docs-maintenance.v1"
WORKFLOWS = ("help-forensic", "help-expert-review", "root-docs-review", "docs-analyse")
REVISION = re.compile(r"[a-f0-9]{40}")
PACKAGES = {
    "workers": ("system/hub/_services/chat/", "system/gui/api/worker_"),
    "scheduler": (
        "system/hub/scheduler",
        "system/gui/daemon_",
        "system/hub/_services/recurring/",
    ),
    "memory": (
        "system/hub/_services/memory",
        "system/hub/_services/hermes",
        "system/hub/_services/nemofold",
    ),
    "governance": ("system/hub/_services/governance", "system/gui/api/governance"),
    "gui": ("system/gui/", "system/ocean_gui_shell/"),
}


def stamp(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("Aware time required")
    return now.astimezone(timezone.utc).isoformat()


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"schema": STATE_SCHEMA, "packages": {}}
    if path.stat().st_size > 65536:
        raise ValueError("Maintenance state exceeds budget")
    state = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or state.get("schema") != STATE_SCHEMA
        or not isinstance(state.get("packages"), dict)
        or len(state["packages"]) > len(PACKAGES) + 1
    ):
        raise ValueError("Invalid maintenance state")
    routines = state.get("routines", {})
    if not isinstance(routines, dict) or len(routines) > 4:
        raise ValueError("Invalid maintenance routines")
    for name, item in {**state["packages"], **routines}.items():
        if name not in {
            *PACKAGES,
            "root",
            "help_forensic",
            "roadmap_review",
            "doc_freshness",
            "docs_changelog_review",
        } or not isinstance(item, dict):
            raise ValueError("Invalid maintenance package")
        if (
            type(item.get("task_id")) is not int
            or item["task_id"] <= 0
            or not REVISION.fullmatch(str(item.get("revision", "")))
        ):
            raise ValueError("Invalid maintenance task reference")
    return state


def write_state(path: Path, state: dict, guard) -> None:
    guard(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise PermissionError("Maintenance state cannot use symlinks")
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("Maintenance state exceeds budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    if temporary.is_symlink():
        raise PermissionError("Maintenance temporary state cannot use symlinks")
    guard(temporary)
    temporary.write_text(encoded, encoding="utf-8")
    guard(path)
    temporary.replace(path)


def git_snapshot(root: Path, previous: str | None) -> tuple[str, list[str]]:
    def run(arguments):
        result = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, timeout=10, check=True
        )
        if len(result.stdout) > 65536:
            raise ValueError("Documentation delta exceeds budget")
        return result.stdout.decode("utf-8", errors="strict")

    revision = run(["rev-parse", "HEAD"]).strip()
    if not REVISION.fullmatch(revision):
        raise ValueError("Invalid source revision")
    # Do not describe an uncommitted implementation as the committed revision.
    dirty = run(
        [
            "diff",
            "--name-only",
            "HEAD",
            "--",
            "system/hub",
            "system/gui/api",
            "docs",
            "README.md",
        ]
    )
    if dirty.strip():
        raise RuntimeError("source_dirty")
    untracked = run(
        [
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "system/hub",
            "system/gui/api",
            "docs",
        ]
    )
    if untracked.strip():
        raise RuntimeError("source_dirty")
    if previous is not None:
        if not REVISION.fullmatch(previous):
            raise ValueError("Invalid previous revision")
        files = run(["diff", "--name-only", "-z", previous, revision, "--"])
    else:
        files = run(
            [
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                revision,
            ]
        )
    names = [name for name in files.split("\x00") if name]
    if len(names) > 256:
        raise ValueError("Documentation delta exceeds file budget")
    names = [
        name for name in names if not name.startswith(("system/data/", "system/tests/"))
    ]
    return revision, names


def packages_for(files: list[str]) -> dict[str, list[str]]:
    result = {}
    for name in files:
        if (
            not isinstance(name, str)
            or len(name) > 240
            or any(char in name for char in "\x00\n\r")
            or ":" in name
            or "\\" in name
            or name.startswith("/")
            or ".." in name.split("/")
        ):
            raise ValueError("Invalid source filename")
        key = next(
            (key for key, prefixes in PACKAGES.items() if name.startswith(prefixes)),
            "root",
        )
        result.setdefault(key, []).append(name)
    return result


class DocumentationDispatcher:
    def __init__(
        self,
        root: Path,
        state_path: Path,
        task_api,
        result_reader,
        guard,
        *,
        snapshot=git_snapshot,
        clock=None,
        binding=None,
    ):
        self.root, self.state_path = root, state_path
        self.tasks, self.result_reader, self.guard = task_api, result_reader, guard
        self.snapshot = snapshot
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.binding = binding or {}
        if set(self.binding) - {"assigned_slot", "required_model"}:
            raise ValueError("Invalid documentation worker binding")

    def _task_state(self, item: dict) -> dict:
        observed = self.result_reader(item["task_id"])
        if (
            not isinstance(observed, dict)
            or observed.get("verified") is not True
            or observed.get("task_id") != item["task_id"]
        ):
            raise RuntimeError("task_readback_unverified")
        result = observed.get("result")
        accepted = (
            isinstance(result, dict)
            and result.get("accepted") is True
            and observed.get("status") in {"done", "completed"}
        )
        return {
            "task_status": observed["status"],
            "result_accepted": accepted,
            "result_id": result.get("result_id") if isinstance(result, dict) else None,
            "last_review_success": result.get("accepted_at") if accepted else None,
            "last_repair_success": None,
        }

    def _description(self, package: str, revision: str, files: list[str]) -> str:
        references = "\n".join(
            "- system/skills/workflows/" + workflow + ".md" for workflow in WORKFLOWS
        )
        selected = "\n".join("- " + name for name in files[:6])
        return (
            "[BACH-DOCS-DELTA] Begrenzte empirische Dokuprüfung, zunächst nur Analyse.\n"
            f"Paket: {package}; tatsächlicher Quellcommit: {revision}.\n"
            "Quellen dieses Änderungspakets (höchstens sechs pro Durchlauf):\n"
            + selected
            + "\n"
            f"Weitere Dateien im Delta: {max(0, len(files) - 6)}; nicht still als geprüft markieren.\n"
            "Vorhandene Methoden gezielt konsumieren:\n" + references + "\n"
            "Alte Modell-, Fanout-, Pfad-, Archivierungs- und Zeitvorgaben darin sind keine aktuellen Befugnisse. "
            "Rootregeln, Locks, Host/Instanz und installierten Pin frisch prüfen. Fachliche Aussagen anhand "
            "belegter nativer CLI/API/GUI-Empirie vergleichen; Codepräsenz ist kein Laufnachweis. "
            "Bestätigte Realität hat bei Tatsachendoku Vorrang; offene bessere Sollanforderungen bleiben Tasks. "
            "Eine konkrete Differenz mit Source-/Eventlokator und kleinem Korrekturvorschlag liefern. "
            "Keine Dateien ändern/archivieren/löschen, keine Dienste/Modelle starten, keine weiteren Tasks claimen. "
            "Keine Differenz ist ein gültiges Ergebnis. Gespeicherter Vorschlag, unabhängiger Review, "
            "tatsächlicher Dokurepair und persönliche Ergebnisfreigabe sind getrennte Schritte."
        )

    def _ensure_task(self, title, description, *, priority="P2"):
        matches = self.tasks.list(status=None, filter_text=title, limit=20)
        exact = [row for row in matches if row.get("title") == title]
        if len(exact) > 1:
            raise RuntimeError("documentation_task_conflict")
        self.guard(self.root)
        action = "recovered"
        if not exact:
            args = [
                title,
                "--priority",
                priority,
                "--category",
                "WORKER",
                "--assign",
                "bach",
                "--description",
                description,
            ]
            for field, flag in (
                ("assigned_slot", "--assigned-slot"),
                ("required_model", "--required-model"),
            ):
                if self.binding.get(field):
                    args.extend([flag, self.binding[field]])
            ok, _ = self.tasks.raw("add", *args)
            if not ok:
                raise RuntimeError("documentation_task_creation_failed")
            matches = self.tasks.list(status=None, filter_text=title, limit=20)
            exact = [row for row in matches if row.get("title") == title]
            action = "created"
        if len(exact) != 1:
            raise RuntimeError("documentation_task_ack_unverified")
        row = exact[0]
        if (
            type(row.get("id")) is not int
            or row["id"] <= 0
            or row.get("description") != description
            or row.get("category") != "WORKER"
            or str(row.get("assigned_to", "")).lower() != "bach"
            or any(
                (row.get(key) or "") != self.binding.get(key, "")
                for key in ("assigned_slot", "required_model")
            )
        ):
            raise RuntimeError("documentation_task_binding_conflict")
        return row["id"], action

    def dispatch(self) -> dict:
        self.guard(self.root)
        state = read_state(self.state_path)
        now = self.clock()
        revision, files = self.snapshot(self.root, state.get("source_revision"))
        changed = packages_for(files)
        # Re-read native references, never infer completed review from dispatch.
        for item in [*state["packages"].values(), *state.get("routines", {}).values()]:
            item.update(self._task_state(item))
        selected = None
        for package, names in sorted(changed.items()):
            previous = state["packages"].get(package)
            if previous and (
                previous["revision"] == revision
                or previous["task_status"] not in {"done", "completed", "cancelled"}
            ):
                continue
            selected = (package, names)
            break
        outcome = {
            "state": "idle",
            "source_revision": revision,
            "task_id": None,
            "semantic_review_completed": False,
        }
        if selected:
            package, names = selected
            root_id = hashlib.sha256(str(self.root.resolve()).encode()).hexdigest()[:8]
            title = f"Doku-Delta {package} {root_id} {revision[:12]}"
            task_id, action = self._ensure_task(
                title, self._description(package, revision, names)
            )
            item = {
                "revision": revision,
                "task_id": task_id,
                "dispatched_at": stamp(now),
            }
            item.update(self._task_state(item))
            state["packages"][package] = item
            outcome.update(state="dispatched", task_id=task_id, dispatch_action=action)
        # Retain the delta until every changed package was dispatched at this revision.
        covered = all(
            state["packages"].get(key, {}).get("revision") == revision
            for key in changed
        )
        if covered:
            state["source_revision"] = revision
        state["observed_at"] = stamp(now)
        state["last_dispatch_check"] = outcome
        write_state(self.state_path, state, self.guard)
        return outcome
