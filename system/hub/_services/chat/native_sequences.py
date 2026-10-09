"""MarbleRun embedding using BACH's real native worker and TaskLease authority."""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, replace

from .sequence_store import SequenceConflict, SequenceStore, definition, digest, encoded
from .slots_config import core_system_agents_snapshot, sequence_profile_snapshot, materialize_sequence_slot
from hub._services.skill_source_service import read_skill, skill_library, load_skill_instructions
from hub._services.task_lease_client import LeaseError

log = logging.getLogger("bach.native_sequences")
MARBLERUN_COMMIT = "e136ab3a632bcd663a510ef1c2ed666f6300b6bf"
_RUN_ID = re.compile(r"[0-9a-f]{32}")
_TERMINAL = {"complete", "failed", "stopped"}


def embedded_module():
    """An installed API name alone does not prove the reviewed module revision."""
    try:
        distribution = importlib.metadata.distribution("llmauto")
        provenance = json.loads(distribution.read_text("direct_url.json") or "{}")
        if (provenance.get("url") != "https://github.com/ellmos-ai/marblerun.git"
                or provenance.get("vcs_info", {}).get("commit_id") != MARBLERUN_COMMIT):
            raise RuntimeError("MarbleRun muss aus der gepinnten Modulrevision installiert sein")
        module = importlib.import_module("llmauto.core.embedded")
        if module.EMBEDDED_SEQUENCE_API != 1:
            raise RuntimeError("MarbleRun-Schnittstellenversion nicht unterstützt")
        return module
    except (ImportError, ValueError, AttributeError) as exc:
        raise RuntimeError("Gepinntes MarbleRun-Modul nicht verfügbar") from exc


@dataclass(frozen=True)
class _SequenceCreatorAuthority:
    """Private admission reference; content, slots and public start APIs never carry it."""
    store: SequenceStore
    run_id: str
    cursor: int
    service_instance: str

    def bind(self, **identity):
        return self.store.bind_creator_delegation(self.run_id, self.cursor, self.service_instance, **identity)

    def revoke(self):
        self.store.stop(self.run_id, self.service_instance)


class NativeGateway:
    def __init__(self, *, service_instance, start, observe, result, stop, slot):
        self.service_instance = service_instance
        self.start_worker, self.observe_worker = start, observe
        self.worker_result, self.stop_worker, self.worker_slot = result, stop, slot

    def dispatch(self, worker_id, request_id, configuration_version, prompt, module, *, creator_authority):
        response, status = self.start_worker(worker_id, custom_prompt=prompt, start_request_id=request_id,
            expected_service_instance=self.service_instance, expected_configuration_version=configuration_version,
            _creator_authority=creator_authority)
        receipt = response.get("execution")
        if (status not in {200, 202} or not isinstance(receipt, dict)
                or receipt.get("service_instance") != self.service_instance
                or receipt.get("worker_id") != worker_id or receipt.get("start_request_id") != request_id
                or not isinstance(receipt.get("generation"), str) or not _RUN_ID.fullmatch(receipt["generation"])):
            raise SequenceConflict("Natives Start-Receipt nicht bestätigt")
        return module.ExecutionHandle(request_id, receipt["generation"], self.service_instance)

    def observe(self, step, handle, module, *, stop_requested=False):
        receipt = self.observe_worker(step["worker_id"], handle.request_id)
        if (receipt.get("service_instance") != handle.authority_id or receipt.get("generation") != handle.job_id
                or receipt.get("worker_id") != step["worker_id"] or receipt.get("start_request_id") != handle.request_id
                or type(receipt.get("terminal")) is not bool):
            raise SequenceConflict("Natives Ausführungs-Receipt passt nicht zur Schrittbindung")
        if not receipt["terminal"]:
            if receipt.get("state") == "unconfirmed":
                raise SequenceConflict("Physischer Workerlauf nicht bestätigt")
            return module.ExecutionObservation(handle, False)
        if stop_requested or receipt.get("stop_requested") is True:
            return module.ExecutionObservation(handle, True, False, reason="worker_stopped")
        if receipt.get("results_verified") is not True:
            return module.ExecutionObservation(handle, False, reason="task_result_unconfirmed")
        if step["task_id"] in receipt.get("reviewed_task_ids", []):
            return module.ExecutionObservation(handle, False, reason="task_result_review_required")
        if step["task_id"] not in receipt.get("completed_task_ids", []):
            return module.ExecutionObservation(handle, True, False, reason="task_done_ack_missing")
        try:
            result = self.worker_result(step["worker_id"], handle.request_id, handle.job_id, step["task_id"])
        except (ValueError, LeaseError, sqlite3.Error, OSError):
            # An acceptance can be withdrawn between receipt and output read.
            # A source read can also fail here. Keep polling the same handle
            # instead of exiting the supervisor with an unconfirmed run.
            return module.ExecutionObservation(handle, False, reason="task_result_unconfirmed")
        if (result.get("schema") != "bach.task-result.v1" or result.get("task_id") != step["task_id"]
                or result.get("generation") != handle.job_id or result.get("accepted") is not True
                or not isinstance(result.get("result"), str)
                or not result["result"].strip()):
            return module.ExecutionObservation(handle, False, reason="task_result_unconfirmed")
        return module.ExecutionObservation(handle, True, True, output=result["result"])

    def cancel(self, step, handle):
        if handle.authority_id != self.service_instance:
            raise SequenceConflict("Controller der Schrittbindung nicht mehr aktuell")
        worker = self.worker_slot(step["worker_id"])
        if not worker:
            raise SequenceConflict("Gebundener Laufsteckplatz nicht verfügbar")
        _, _, receipt, status = self.stop_worker(step["worker_id"], worker, activity="MarbleRun-Stop angefordert",
            expected_execution={"service_instance": handle.authority_id,
                                "start_request_id": handle.request_id, "generation": handle.job_id})
        execution = receipt.get("execution", {})
        correlated = (receipt.get("kind") == "worker-revocation"
            and receipt.get("worker_id") == step["worker_id"] and receipt.get("generation") == handle.job_id
            and execution.get("service_instance") == handle.authority_id
            and execution.get("worker_id") == step["worker_id"]
            and execution.get("generation") == handle.job_id and execution.get("start_request_id") == handle.request_id
            and type(execution.get("terminal")) is bool)
        pending = (status == 409 and receipt.get("outcome") == "revocation-pending"
                   and receipt.get("confirmed") is False and execution.get("terminal") is False)
        confirmed = status in {200, 202} and receipt.get("confirmed") is True
        if not correlated or not (confirmed or pending):
            raise SequenceConflict("Stop dieser Generation nicht bestätigt")

    def reconcile_stop(self, step, module):
        """Recover only the exact admitted generation, never repeat admission."""
        receipt = self.observe_worker(step["worker_id"], step["request_id"])
        generation = receipt.get("generation")
        if (receipt.get("schema") != "bach.worker-execution.v1"
                or receipt.get("service_instance") != self.service_instance
                or receipt.get("worker_id") != step["worker_id"]
                or receipt.get("start_request_id") != step["request_id"]
                or not isinstance(generation, str) or not _RUN_ID.fullmatch(generation)
                or type(receipt.get("terminal")) is not bool
                or step["generation"] not in {None, generation}
                or step["authority_id"] not in {None, self.service_instance}):
            raise SequenceConflict("Stop-Rekonstruktion ohne exakten nativen Zulassungsbeleg abgewiesen")
        return module.ExecutionHandle(step["request_id"], generation, self.service_instance)


class NativeSequences:
    def __init__(self, store: SequenceStore, gateway: NativeGateway, *, engine_loader=embedded_module):
        self.store, self.gateway, self.engine_loader = store, gateway, engine_loader
        self._lock = threading.RLock()
        self._threads = {}
        self._stop_wakeups = set()
        self._retiring = set()

    def catalog(self):
        core = core_system_agents_snapshot()
        try:
            self.engine_loader()
            available, reason = True, ""
        except RuntimeError as exc:
            available, reason = False, str(exc)
        return {"schema": "bach.native-sequences.v1", "service_instance": self.gateway.service_instance,
            "module_commit": MARBLERUN_COMMIT, "runtime_available": available, "unavailable_reason": reason,
            "configuration_version": core["configuration_version"], "chains": self.store.chains(),
            "agents": [{key: item.get(key) for key in ("id", "name", "backend", "model", "enabled")}
                       for item in core["agents"] if item["execution_kind"] == "worker" and not item.get("sequence_run_id")],
            "skills": skill_library()["skills"], "runs": [self._project(row) for row in self.store.runs()]}

    def _project(self, row):
        state = row["state"] or {}
        phase = row["phase"]
        with self._lock:
            thread = self._threads.get(row["run_id"])
            live = thread is not None and thread.is_alive()
        verified = row["owner_service"] == self.gateway.service_instance
        if phase not in _TERMINAL and (not verified or not live or row["error"]):
            phase = "unconfirmed"
        wait_reason = None
        active = state.get("active")
        if verified and live and phase not in _TERMINAL and isinstance(active, dict):
            matches = [item for item in row["steps"] if item["cursor"] == state.get("cursor", 0)]
            if len(matches) == 1:
                step = matches[0]
                try:
                    observed = self.gateway.observe_worker(step["worker_id"], step["request_id"])
                    if (observed.get("generation") != step["generation"]
                            or observed.get("service_instance") != row["owner_service"]
                            or observed.get("results_verified") is not True):
                        wait_reason = "task_result_unconfirmed"
                    elif step["task_id"] in observed.get("reviewed_task_ids", []):
                        wait_reason = "task_result_review_required"
                except Exception:
                    wait_reason = "task_result_unconfirmed"
        return {"run_id": row["run_id"], "chain_id": row["chain_id"], "chain_version": row["chain_version"],
            "service_instance": row["owner_service"], "runtime_verified": verified, "supervisor_live": live,
            "phase": phase, "cursor": state.get("cursor", 0), "step_count": len(row["plan"]["steps"]),
            "completed": state.get("completed", []), "active": state.get("active"),
            "stop_requested": bool(row["stop_requested"]) or state.get("stop_requested", False),
            "reason": row["error"] or wait_reason or state.get("reason", ""),
            "result_wait": wait_reason, "revision": row["revision"],
            "steps": row["steps"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def get_run(self, run_id):
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("Gültige Laufkennung erforderlich")
        return self._project(self.store.run(run_id))

    def start(self, chain_id, payload):
        if not isinstance(payload, dict) or set(payload) - {"request_id", "version", "configuration_version", "expected_service_instance", "input"}:
            raise ValueError("Unbekannte Startfelder")
        run_id = payload.get("request_id")
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("Explizite Startkennung erforderlich")
        if payload.get("expected_service_instance") != self.gateway.service_instance:
            raise SequenceConflict("Controller inzwischen geändert; neu laden")
        text = payload.get("input", "")
        if not isinstance(text, str) or not text.strip() or len(text) > 12000 or "\x00" in text:
            raise ValueError("Lesbarer Arbeitsauftrag erforderlich, höchstens 12000 Zeichen")
        request_digest = digest({"chain_id": chain_id, **payload})
        with self._lock:
            try:
                previous = self.store.run(run_id)
            except KeyError:
                previous = None
            if previous is not None:
                if previous["request_digest"] != request_digest or previous["owner_service"] != self.gateway.service_instance:
                    raise SequenceConflict("Startkennung bereits anders verwendet")
                return {"accepted": True, "replayed": True, "run": self._project(previous)}
            module = self.engine_loader()
            chain = self.store.chain(chain_id)
            if chain is None:
                raise KeyError("Kette nicht gefunden")
            if type(payload.get("version")) is not int or payload["version"] != chain["version"]:
                raise SequenceConflict("Aktuelle Kettenversion erforderlich")
            clean = definition({key: chain[key] for key in ("name", "title", "description", "mode", "agent_slot", "steps")})
            config_version = payload.get("configuration_version")
            if not isinstance(config_version, str) or not re.fullmatch(r"[0-9a-f]{64}", config_version):
                raise ValueError("Aktuelle Living-Konfiguration erforderlich")
            slots = sequence_profile_snapshot({item["agent_slot"] for item in clean["steps"]}, config_version)
            steps = []
            for index, step in enumerate(clean["steps"]):
                if len(text) + len(step["instructions"]) > 12000:
                    raise ValueError("Auftrag und Schrittanweisung überschreiten das gemeinsame Promptbudget")
                profile = slots["profiles"][step["agent_slot"]]
                pins = []
                for skill_id in step["skill_ids"]:
                    skill = read_skill(skill_id)
                    pins.append({"id": skill_id, "source_version": skill["source_version"], "version": skill["version"]})
                inherited = profile.get("skill_refs", [])
                combined = {item["id"]: item for item in (*inherited, *pins)}
                load_skill_instructions(list(combined.values()))
                steps.append({**step, "cursor": index, "profile": profile,
                              "profile_digest": digest(profile), "skill_refs": list(combined.values())})
            plan = {"input": text, "chain_title": clean["title"], "mode": clean["mode"], "steps": steps}
            created = self.store.create_run(run_id, chain_id, chain["version"], request_digest,
                self.gateway.service_instance, MARBLERUN_COMMIT, plan)
            if created:
                self._launch(run_id, module)
            return {"accepted": True, "replayed": not created, "run": self.get_run(run_id)}

    def _launch(self, run_id, module):
        thread = self._threads.get(run_id)
        if thread is not None and thread.is_alive() and run_id not in self._retiring:
            return
        self._retiring.discard(run_id)
        thread = threading.Thread(target=self._execute, args=(run_id, module), name="MarbleRun-" + run_id[:8], daemon=True)
        self._threads[run_id] = thread
        try:
            thread.start()
        except Exception:
            self.store.error(run_id, self.gateway.service_instance, "supervisor_start_unconfirmed")
            raise RuntimeError("Supervisorstart nicht bestätigt") from None

    def stop(self, run_id):
        with self._lock:
            row = self.store.run(run_id)
            if row["owner_service"] != self.gateway.service_instance:
                raise SequenceConflict("Lauf stammt von einem anderen Controller; physisches Ende ungeklärt")
            self.store.stop(run_id, self.gateway.service_instance)
            if row["phase"] not in _TERMINAL:
                self._stop_wakeups.add(run_id)
                self._launch(run_id, self.engine_loader())
            return {"accepted": True, "run": self.get_run(run_id)}

    def _stop_initial(self, row, module):
        initial = module.SequenceState.from_record(row["state"]) if row["state"] else None
        if not row["stop_requested"] or initial is None or initial.active is not None or initial.phase not in {"starting", "unconfirmed"}:
            return initial
        if row["owner_service"] != self.gateway.service_instance:
            raise SequenceConflict("Stop-Rekonstruktion über eine andere Controllerinstanz abgewiesen")
        matches = [step for step in row["steps"] if step["cursor"] == initial.cursor]
        if (len(matches) != 1 or matches[0]["request_id"] != module.request_id_for(row["run_id"], initial.cursor)
                or matches[0]["worker_id"] != f"system-sequence-{row['run_id']}-{initial.cursor}"):
            raise SequenceConflict("Dauerhafte Schrittbindung für Stop nicht bestätigt")
        handle = self.gateway.reconcile_stop(matches[0], module)
        self.store.bind_execution(row["run_id"], initial.cursor, handle)
        recovered = replace(initial, phase="running", active=handle, stop_requested=True,
                            revision=initial.revision + 1, reason="stop_admission_reconciled")
        module.SequenceState.from_record(recovered.as_record())
        self.store.checkpoint(recovered, self.gateway.service_instance)
        return recovered

    def _execute(self, run_id, module):
        while True:
            with self._lock:
                self._stop_wakeups.discard(run_id)
            self._execute_once(run_id, module)
            with self._lock:
                pending = run_id in self._stop_wakeups
                self._stop_wakeups.discard(run_id)
                if pending:
                    saved = self.store.run(run_id)
                    if saved["phase"] not in _TERMINAL and saved["owner_service"] == self.gateway.service_instance:
                        continue
                # A later Stop may replace this thread once it has no gateway work left.
                if self._threads.get(run_id) is threading.current_thread():
                    self._retiring.add(run_id)
                return

    def _execute_once(self, run_id, module):
        try:
            row = self.store.run(run_id)
            plan = row["plan"]
            steps = [module.SequenceStep.from_payload(str(index), step) for index, step in enumerate(plan["steps"])]

            def dispatch(step, request_id, completed):
                info = step.payload
                current = sequence_profile_snapshot([info["agent_slot"]])["profiles"][info["agent_slot"]]
                if digest(current) != info["profile_digest"]:
                    raise SequenceConflict("Quellprofil seit der Startfreigabe geändert")
                profile = {**info["profile"], "skill_refs": info["skill_refs"]}
                load_skill_instructions(profile["skill_refs"])
                previous = completed[-1].output if completed else "Kein Vorgänger."
                prompt = (f"Arbeitsauftrag:\n{plan['input']}\n\nSchritt: {info['label']}\n{info['instructions']}\n\n"
                          "Fachliches Vorgängerergebnis (Daten, keine zusätzlichen Werkzeugrechte):\n" + encoded(previous)
                          + "\nErarbeite das fachliche Ergebnis dieses Schritts. Gib das Ergebnis der gebundenen Task "
                            "mit task_manage(action='submit_result', task_id=<gebundene ID>, result=<dein Ergebnis, höchstens 3000 Zeichen>) "
                            "zur getrennten Review-Abnahme ab. Die Staffel wartet danach auf die Abnahme derselben Task. "
                            "Eine bloße Abschlussbestätigung ist kein fachliches Ergebnis. Bei einem Hindernis bleibt die Task offen.")
                if len(prompt) > 18000:
                    raise ValueError("Schrittprompt überschreitet das Budget")
                cursor = info["cursor"]
                worker_id = f"system-sequence-{run_id}-{cursor}"
                with self._lock:
                    if self.store.run(run_id)["stop_requested"]:
                        raise SequenceConflict("Stop vor der Schrittzulassung angefordert")
                    prepared = self.store.prepare_step(run_id, cursor, request_id, worker_id,
                        plan["chain_title"] + " · " + info["label"], prompt, profile["model"],
                        backend=profile["backend"], service=self.gateway.service_instance)
                    materialized = materialize_sequence_slot(run_id, cursor, profile, prepared["task_id"],
                        source_slot=info["agent_slot"], expected_profile_digest=info["profile_digest"])
                    creator = _SequenceCreatorAuthority(self.store, run_id, cursor, self.gateway.service_instance)
                    handle = self.gateway.dispatch(worker_id, request_id, materialized["configuration_version"], prompt,
                        module, creator_authority=creator)
                    self.store.bind_execution(run_id, cursor, handle)
                    return handle

            def bound_step(handle):
                saved = self.store.run(run_id)
                matches = [step for step in saved["steps"] if step["request_id"] == handle.request_id
                           and step["generation"] == handle.job_id and step["authority_id"] == handle.authority_id]
                if len(matches) != 1 or handle.authority_id != self.gateway.service_instance:
                    raise SequenceConflict("Dauerhafte Schrittbindung nicht bestätigt")
                return matches[0]

            callbacks = dict(dispatch=dispatch,
                observe=lambda handle: self.gateway.observe(bound_step(handle), handle, module,
                    stop_requested=bool(self.store.run(run_id)["stop_requested"])),
                cancel=lambda handle: self.gateway.cancel(bound_step(handle), handle),
                checkpoint=lambda state: self.store.checkpoint(state, self.gateway.service_instance),
                should_stop=lambda: bool(self.store.run(run_id)["stop_requested"]))
            initial = self._stop_initial(row, module)
            try:
                outcome = module.run_sequence(run_id, steps, initial_state=initial, **callbacks)
            except Exception:
                saved = self.store.run(run_id)
                if not saved["stop_requested"]:
                    raise
                recovered = self._stop_initial(saved, module)
                module.run_sequence(run_id, steps, initial_state=recovered, **callbacks)
            else:
                saved = self.store.run(run_id)
                if outcome.phase == "unconfirmed" and outcome.active is None and saved["stop_requested"]:
                    recovered = self._stop_initial(saved, module)
                    module.run_sequence(run_id, steps, initial_state=recovered, **callbacks)
        except Exception as exc:
            log.exception("Native sequence %s lacks a confirmed checkpoint", run_id)
            try:
                self.store.error(run_id, self.gateway.service_instance, "checkpoint_unconfirmed:" + type(exc).__name__)
            except Exception:
                log.exception("Cannot persist sequence uncertainty %s", run_id)
