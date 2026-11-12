"""Fail-closed Verifikation fuer den BACH-Installer.

Das Modul ist bewusst stdlib-only (json, hashlib, hmac, pathlib,
datetime, os) und enthaelt KEINE Mutationslogik. Es liefert:

* Laden und Pruefen versionierter Komponentenmanifeste
  (``bach.component-manifest.v1``) und Produktprofile
  (``bach.product-profile.v1``),
* exakte Soll-/Ist-Mengenpruefung der Komponenten VOR jeder Mutation,
* Pruefung eines extern signierten Capability-Grants (HMAC-SHA256),
* ein append-only Mutationsjournal sowie einen Rollback-Planer, der ALLE
  protokollierten Komponenten prueft, bevor irgendetwas geloescht wird.

Faellt eine Pruefung durch, wird ``InstallerVerificationError`` geworfen.
Es gibt keinen stillen Durchlauf und keinen Teil-Rollback.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Union

PRODUCT_PROFILE_SCHEMA = "bach.product-profile.v1"
MANIFEST_SCHEMA = "bach.component-manifest.v1"
GRANT_SCHEMA = "bach.capability-grant.v1"
JOURNAL_SCHEMA = "bach.mutation-journal.v1"

# Operationen, die als Mutation im Journal gelten und im Rollback
# geprueft werden muessen.
MUTATION_OPS = frozenset({"install", "write", "create", "migrate", "download"})


class InstallerVerificationError(RuntimeError):
    """Fail-closed Abbruch: Komponentenmenge oder Freigabe nicht belegt."""


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def canonical_json(payload: Any) -> bytes:
    """Kanonische JSON-Serialisierung (sortierte Keys, keine Whitespaces)."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def payload_digest(payload: Any) -> str:
    """sha256-Digest ueber die kanonische JSON-Form eines Objekts."""
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def file_digest(path: Union[str, os.PathLike]) -> str:
    """sha256-Digest einer Datei, gleiches Format wie ``payload_digest``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_json(path: Union[str, os.PathLike], kind: str) -> Dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise InstallerVerificationError(f"{kind} fehlt: {target}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise InstallerVerificationError(
            f"{kind} ist nicht lesbar oder kein gueltiges JSON ({target}): {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise InstallerVerificationError(f"{kind} muss ein JSON-Objekt sein: {target}")
    return data


def _component_name(entry: Any) -> str:
    if isinstance(entry, str):
        name = entry.strip()
    elif isinstance(entry, Mapping):
        name = str(entry.get("name", "")).strip()
    else:
        name = ""
    if not name:
        raise InstallerVerificationError(
            f"Komponenteneintrag ohne Namen: {entry!r}"
        )
    return name


def component_names(entries: Any) -> List[str]:
    """Namen aus Liste/Dict von Komponenteneintraegen normalisieren."""
    if entries is None:
        raise InstallerVerificationError("Komponentenmenge fehlt")
    if isinstance(entries, Mapping):
        names = [str(key).strip() for key in entries.keys()]
    elif isinstance(entries, (str, bytes)):
        raise InstallerVerificationError(
            "Komponentenmenge muss eine Liste oder ein Objekt sein, kein String"
        )
    elif isinstance(entries, Iterable):
        names = [_component_name(item) for item in entries]
    else:
        raise InstallerVerificationError(f"Komponentenmenge unbrauchbar: {entries!r}")
    if not names:
        raise InstallerVerificationError("Komponentenmenge ist leer")
    if any(not name for name in names):
        raise InstallerVerificationError("Komponentenmenge enthaelt leere Namen")
    return names


# --------------------------------------------------------------------------
# Manifest und Produktprofil
# --------------------------------------------------------------------------

def load_manifest(path: Union[str, os.PathLike]) -> Dict[str, Any]:
    """Laedt ein versioniertes Komponentenmanifest (fail closed)."""
    manifest = _load_json(path, "Komponentenmanifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise InstallerVerificationError(
            f"Komponentenmanifest hat falsches Schema: {manifest.get('schema')!r} "
            f"(erwartet {MANIFEST_SCHEMA!r})"
        )
    version = manifest.get("manifest_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise InstallerVerificationError(
            f"Komponentenmanifest ohne gueltige manifest_version: {version!r}"
        )
    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        raise InstallerVerificationError(
            "Komponentenmanifest enthaelt keine Komponentenliste"
        )
    return manifest


def load_product_profile(path: Union[str, os.PathLike]) -> Dict[str, Any]:
    """Laedt ein Produktprofil inklusive erwarteter Komponentenmenge."""
    profile = _load_json(path, "Produktprofil")
    if profile.get("schema") != PRODUCT_PROFILE_SCHEMA:
        raise InstallerVerificationError(
            f"Produktprofil hat falsches Schema: {profile.get('schema')!r} "
            f"(erwartet {PRODUCT_PROFILE_SCHEMA!r})"
        )
    if not str(profile.get("profile_id", "")).strip():
        raise InstallerVerificationError("Produktprofil ohne profile_id")
    product = profile.get("product")
    if product is not None and not isinstance(product, Mapping):
        raise InstallerVerificationError("Produktprofil: product muss ein Objekt sein")
    components = profile.get("components")
    if not isinstance(components, list) or not components:
        raise InstallerVerificationError(
            "Produktprofil enthaelt keine erwartete Komponentenmenge"
        )
    component_names(components)  # validiert Namen
    return profile


def resolve_components(manifest: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Loest die manifestierte Sollmenge in ``{name: eintrag}`` auf.

    Doppelte Namen sind ein Manifestfehler und fuehren zum Abbruch, weil
    sonst die Mengenpruefung unbemerkt verwaessern wuerde.
    """
    if not isinstance(manifest, Mapping):
        raise InstallerVerificationError("Manifest ist kein Objekt")
    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        raise InstallerVerificationError("Manifest enthaelt keine Komponentenliste")
    resolved: Dict[str, Dict[str, Any]] = {}
    for entry in components:
        name = _component_name(entry)
        if name in resolved:
            raise InstallerVerificationError(
                f"Komponente doppelt im Manifest: {name}"
            )
        resolved[name] = dict(entry) if isinstance(entry, Mapping) else {"name": name}
        resolved[name]["name"] = name
    return resolved


def verify_component_set(
    resolved: Union[Mapping[str, Any], Iterable[Any]],
    expected: Union[Mapping[str, Any], Iterable[Any]],
) -> None:
    """Prueft, dass Ist- und Sollmenge exakt gleich sind (VOR jeder Mutation)."""
    have = component_names(resolved)
    want = component_names(expected)
    have_set, want_set = set(have), set(want)
    if len(have_set) != len(have):
        duplicates = sorted({name for name in have if have.count(name) > 1})
        raise InstallerVerificationError(
            "Ist-Menge enthaelt Duplikate: " + ", ".join(duplicates)
        )
    if len(want_set) != len(want):
        duplicates = sorted({name for name in want if want.count(name) > 1})
        raise InstallerVerificationError(
            "Soll-Menge enthaelt Duplikate: " + ", ".join(duplicates)
        )
    missing = sorted(want_set - have_set)
    extra = sorted(have_set - want_set)
    if missing or extra:
        parts = []
        if missing:
            parts.append("fehlend: " + ", ".join(missing))
        if extra:
            parts.append("ueberzaehlig: " + ", ".join(extra))
        raise InstallerVerificationError(
            "Komponentenmenge weicht ab (" + "; ".join(parts) + ")"
        )


# --------------------------------------------------------------------------
# Capability-Grant (extern signiert)
# --------------------------------------------------------------------------

def _key_bytes(verify_key: Union[str, bytes, None]) -> bytes:
    if verify_key is None:
        raise InstallerVerificationError("Kein Grant-Pruefschluessel vorhanden")
    if isinstance(verify_key, bytes):
        key = verify_key
    else:
        key = str(verify_key).encode("utf-8")
    if not key:
        raise InstallerVerificationError("Grant-Pruefschluessel ist leer")
    return key


def compute_grant_signature(
    payload: Mapping[str, Any], verify_key: Union[str, bytes]
) -> str:
    """HMAC-SHA256 ueber den Grant ohne Signaturfeld.

    Hilfsfunktion fuer den externen Signierer bzw. fuer Tests; der
    Installer selbst signiert nie.
    """
    body = {key: value for key, value in payload.items() if key != "signature"}
    return hmac.new(_key_bytes(verify_key), canonical_json(body), hashlib.sha256).hexdigest()


def _check_not_after(grant: Mapping[str, Any]) -> None:
    raw = grant.get("not_after")
    if raw in (None, ""):
        return
    try:
        expiry = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InstallerVerificationError(
            f"Grant: not_after ist kein ISO-Zeitstempel: {raw!r}"
        ) from exc
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expiry:
        raise InstallerVerificationError(f"Grant ist abgelaufen: {raw}")


def verify_grant(
    grant_path: Union[str, os.PathLike],
    manifest_digest: str,
    product_profile: Mapping[str, Any],
    verify_key: Union[str, bytes, None],
) -> Dict[str, Any]:
    """Prueft Bindung + Signatur des Grants; ohne Gueltigkeit harter Abbruch."""
    if not manifest_digest:
        raise InstallerVerificationError("Manifest-Digest fuer Grant-Pruefung fehlt")
    if not isinstance(product_profile, Mapping):
        raise InstallerVerificationError("Produktprofil fuer Grant-Pruefung fehlt")
    grant = _load_json(grant_path, "Capability-Grant")

    if grant.get("schema") != GRANT_SCHEMA:
        raise InstallerVerificationError(
            f"Grant hat falsches Schema: {grant.get('schema')!r} "
            f"(erwartet {GRANT_SCHEMA!r})"
        )
    if grant.get("manifest_digest") != manifest_digest:
        raise InstallerVerificationError(
            "Grant ist nicht an dieses Manifest gebunden "
            f"(Grant: {grant.get('manifest_digest')!r}, Manifest: {manifest_digest!r})"
        )
    profile_id = str(product_profile.get("profile_id", "")).strip()
    if not profile_id:
        raise InstallerVerificationError("Produktprofil ohne profile_id")
    if str(grant.get("profile_id", "")).strip() != profile_id:
        raise InstallerVerificationError(
            f"Grant ist nicht an dieses Produktprofil gebunden "
            f"(Grant: {grant.get('profile_id')!r}, Profil: {profile_id!r})"
        )

    signature = grant.get("signature")
    if not signature:
        raise InstallerVerificationError("Grant ohne Signatur - Freigabe fehlt")
    signature = str(signature).strip()
    if signature.lower().startswith("hmac-sha256:"):
        signature = signature.split(":", 1)[1].strip()
    expected = compute_grant_signature(grant, verify_key)
    if not hmac.compare_digest(signature.lower(), expected):
        raise InstallerVerificationError("Grant-Signatur ist ungueltig")
    _check_not_after(grant)
    return grant


# --------------------------------------------------------------------------
# Mutationsjournal
# --------------------------------------------------------------------------

class MutationJournal:
    """Append-only JSONL-Journal aller Installer-Mutationen."""

    def __init__(self, path: Union[str, os.PathLike]) -> None:
        self.path = Path(path)
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def __len__(self) -> int:
        return len(self.entries())

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return iter(self.entries())

    def entries(self) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        return read_journal(self.path)

    def record(
        self,
        op: str,
        target: Union[str, os.PathLike],
        digest: Optional[str] = None,
        component: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Schreibt einen Mutationsdatensatz und synct ihn auf Platte."""
        if not str(op).strip():
            raise InstallerVerificationError("Journal: op fehlt")
        entry: Dict[str, Any] = {
            "schema": JOURNAL_SCHEMA,
            "seq": len(self.entries()) + 1,
            "ts": datetime.now(timezone.utc).isoformat(),
            "op": str(op),
            "target": str(target),
        }
        if digest:
            entry["digest"] = str(digest)
        if component:
            entry["component"] = str(component)
        line = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:  # pragma: no cover - Plattform ohne fsync
                pass
        return entry


def read_journal(journal_path: Union[str, os.PathLike]) -> List[Dict[str, Any]]:
    """Liest das Journal vollstaendig; defekte Zeilen brechen ab."""
    path = Path(journal_path)
    if not path.is_file():
        raise InstallerVerificationError(f"Mutationsjournal fehlt: {path}")
    entries: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InstallerVerificationError(
                    f"Journalzeile {lineno} ist kein gueltiges JSON: {exc}"
                ) from exc
            if not isinstance(record, dict) or not record.get("op") or "target" not in record:
                raise InstallerVerificationError(
                    f"Journalzeile {lineno} ist unvollstaendig: {line!r}"
                )
            entries.append(record)
    return entries


def plan_rollback(
    journal_path: Union[str, os.PathLike],
    expected_components: Optional[Any] = None,
) -> List[str]:
    """Plant die Ruecknahme - erst nach Vollpruefung ALLER Journaltargets.

    Geprueft wird Existenz und (falls protokolliert) Digest jeder
    Mutation. Schon eine Abweichung verhindert jeden Loeschplan.
    """
    entries = read_journal(journal_path)
    mutations = [e for e in entries if str(e.get("op")) in MUTATION_OPS]
    if not mutations:
        raise InstallerVerificationError(
            "Rollback verweigert: Journal enthaelt keine protokollierten Mutationen"
        )

    if expected_components is not None:
        expected = set(component_names(expected_components))
        recorded = {str(e.get("component")) for e in mutations if e.get("component")}
        missing = sorted(expected - recorded)
        if missing:
            raise InstallerVerificationError(
                "Rollback verweigert: unvollstaendige Protokollierung, "
                "nicht protokolliert: " + ", ".join(missing)
            )

    problems: List[str] = []
    verified: List[str] = []
    for entry in mutations:
        target = Path(str(entry["target"]))
        if not target.exists():
            problems.append(f"Ziel fehlt: {target}")
            continue
        digest = entry.get("digest")
        if digest:
            if target.is_dir():
                problems.append(f"Digest fuer Verzeichnis nicht pruefbar: {target}")
                continue
            try:
                have = file_digest(target)
            except OSError as exc:
                problems.append(f"Ziel nicht lesbar: {target} ({exc})")
                continue
            if not hmac.compare_digest(str(digest), have):
                problems.append(
                    f"Digest abweichend: {target} (erwartet {digest}, gefunden {have})"
                )
                continue
        verified.append(str(target))

    if problems:
        raise InstallerVerificationError(
            "Rollback verweigert, Vollpruefung fehlgeschlagen: " + "; ".join(problems)
        )

    plan: List[str] = []
    seen = set()
    for target in reversed(verified):
        if target in seen:
            continue
        seen.add(target)
        plan.append(target)
    return plan
