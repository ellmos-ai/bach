# -*- coding: utf-8 -*-
"""Lint-Regel: Der Pfad zur bach.db wird NUR zentral bestimmt.

Hintergrund
-----------
BACH hat mit ``hub/bach_paths.py`` eine zentrale Pfad-Registry. Trotzdem hatten
rund 20 Module den DB-Pfad selbst zusammengebaut — meist repo-relativ als
``<irgendwas>/data/bach.db``. Zwei Fehlerklassen entstanden dadurch:

1. **Stille Alt-Daten:** Die repo-relative ``system/data/bach.db`` ist nicht mehr
   die kanonische Datenbank (das ist ``~/.bach/bach.db``). Module, die sie selbst
   konstruierten, lasen tagelang veraltete Daten, ohne dass etwas fehlschlug.
2. **Geisterdatenbanken:** Verzaehlte ``Path(__file__).parent``-Ketten ergaben
   Pfade auf nicht existierende Verzeichnisse. ``sqlite3.connect()`` legt eine
   fehlende Datei stillschweigend als 0-KB-Datenbank an — der Prozess lief
   scheinbar normal weiter, nur eben auf einer leeren DB.

Beide Fehler sind still. Deshalb diese Regel: Module ERFRAGEN den Pfad
(``from hub.bach_paths import BACH_DB``), sie KONSTRUIEREN ihn nicht.

Erkennung
---------
Per AST, nicht per Regex: Die alten Stellen nutzten mindestens drei Syntaxformen
(``X / "data" / "bach.db"``, ``DATA_DIR / "bach.db"``,
``os.path.join(BASE, "data", "bach.db")``). Ein Regex auf einzelne Muster wuerde
Varianten durchlassen. Der AST-Check erkennt das Literal ``"bach.db"`` als Teil
einer Pfad-Komposition (``/``-Operator oder ``os.path.join``) und ignoriert
zugleich blosse Erwaehnungen in Docstrings und Kommentaren.
"""
import ast
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent

DB_FILENAMES = {"bach.db"}

# Dateien, die den Pfad legitim selbst bestimmen duerfen. Jeder Eintrag braucht einen
# Grund — "faellt sonst rot aus" ist keiner.
WHITELIST = {
    # Die Registry selbst — hier IST die Definition zuhause.
    "hub/bach_paths.py",
    # Zentrale DB-Schicht.
    "core/db.py",
    # BaseHandler leitet _canonical_db her, das ALLE Handler benutzen. Die lokale DB
    # gewinnt dort nur, wenn base_path NICHT der echte system-Root ist — genau darueber
    # injizieren die Test-Fixtures ihre tmp-DB. Die Konstruktion ist hier der Mechanismus,
    # nicht der Fehler.
    "hub/base.py",
    # Der Path-Handler spiegelt die Registry bewusst auf einen alternativen Runtime-Root
    # (_active_db_path). Ihn auf die Registry zu zwingen, wuerde seinen Zweck aufheben.
    "hub/path.py",
    # ProSync verwaltet die lokale DB (~/.bach/bach.db) und die OneDrive-DB explizit als
    # ZWEI Endpunkte einer Kopie. Beide Pfade kommen aus der Registry (LOCAL_BACH_DIR,
    # ONEDRIVE_DB); nur der Dateiname wird angehaengt.
    "hub/db_sync.py",
    # SealHandler und AgentRegistry bekommen base_path herein — und GENAU DAS ist der
    # Injektionsmechanismus der Test-Fixtures (tmp-Verzeichnis mit eigener DB). Beide
    # nutzen daher dasselbe Muster wie hub/base.py: liegt unter einem base_path, der NICHT
    # der echte system-Root ist, eine DB, gewinnt diese; sonst die Registry.
    # (Belegt am 2026-07-13: eine blinde Ersetzung durch BACH_DB machte
    #  test_agent_runtime_invalidates_cached_module_after_code_change und
    #  test_smoke::test_seal_status rot — die Tests suchten in der echten 82-MB-DB.)
    "hub/seal.py",
    "core/agent_runtime.py",
}

# Verzeichnis-Namen, die an JEDER Stelle im Pfad ausnehmen (nicht nur ganz vorn:
# ``hub/_archive/`` liegt eben nicht am Anfang des relativen Pfades).
WHITELIST_PARTS = {
    "tests",
    "_archive",
    "_dev",
    ".dev",
    "__pycache__",
}

WHITELIST_DIRS = (
    "data/temp/",
    # Migrationen sind Einmal-Skripte, die ihren Ziel-Pfad per Argument bekommen
    # und auch gegen eine BELIEBIGE DB-Datei laufen koennen muessen (etwa eine
    # Kopie, die vor dem Upgrade gezogen wurde). Ihr Default ist bewusst frei.
    "data/schema/migrations/",
)

# ---------------------------------------------------------------------------
# ALT-SCHULD (Baseline) — semantisch etwas ANDERES als die Whitelist oben!
#
# Whitelist = darf den Pfad dauerhaft selbst bestimmen.
# Baseline  = tut es noch, soll es aber nicht — bekannte Alt-Schuld.
#
# Diese Liste darf nur SCHRUMPFEN, nie wachsen. Neue oder zurueckgefallene
# Dateien schlagen fehl; wer eine Datei saniert, entfernt sie hier.
#
# Stand 2026-07-13: Nur noch `tools/` — die Wartungs- und Hilfsskripte. Die eigentliche
# Laufzeit (bach.py, bach_api, hub/, hub/_services/, core/, gui/, agents/, connectors/)
# ist vollstaendig auf die Registry umgestellt; dort ist der Test gruen, WEIL der Code
# sauber ist, nicht kraft dieser Liste.
# ---------------------------------------------------------------------------
KNOWN_OFFENDERS = {
    "tools/abo/abo_scanner.py",
    "tools/agents/agent_cli.py",
    "tools/agents/agent_service_integration.py",
    "tools/agents_export.py",
    "tools/bach_auto_discovery.py",
    "tools/bach_db_viewer.py",
    "tools/bach_text_viewer.py",
    "tools/chains_export.py",
    "tools/claude_md_sync.py",
    "tools/context_compressor.py",
    "tools/data_importer.py",
    "tools/distribution.py",
    "tools/doc_search.py",
    "tools/doc_update_checker.py",
    "tools/document_indexer.py",
    "tools/folder_diff_scanner.py",
    "tools/fs_protection.py",
    "tools/headless_agent.py",
    "tools/injectors.py",
    "tools/json/json_registry_cleaner.py",
    "tools/lesson_trigger_generator.py",
    "tools/llmauto/modes/chain.py",
    "tools/maintenance/create_boot_checks.py",
    "tools/maintenance/doc_path_updater.py",
    "tools/maintenance/generate_skills_report.py",
    "tools/maintenance/path_healer.py",
    "tools/maintenance/register_skills.py",
    "tools/maintenance/registry_watcher.py",
    "tools/maintenance/skill_health_monitor.py",
    "tools/maintenance/sync_registry.py",
    "tools/maintenance/sync_skills.py",
    "tools/maintenance/sync_utils.py",
    "tools/maintenance/translate_tools_en.py",
    "tools/memory_sync.py",
    "tools/memory_working_cleanup.py",
    "tools/migrate_consolidate_dbs.py",
    "tools/migrate_consolidate_phase2.py",
    "tools/migration/migrate_skills_hierarchy.py",
    "tools/partner_communication/communication.py",
    "tools/partner_communication/interaction_protocol.py",
    "tools/partner_communication/system_explorer.py",
    "tools/partners_export.py",
    "tools/rezeptbuch.py",
    "tools/schema_reader.py",
    "tools/schwarm/runner.py",
    "tools/schwarm/specialist.py",
    "tools/schwarm/stigmergy_pattern.py",
    "tools/schwarm/summarize_chunks.py",
    "tools/schwarm/translate_swarm.py",
    "tools/session_analyzer.py",
    "tools/skill_header_gen.py",
    "tools/theme_packet_generator.py",
    "tools/time_system.py",
    "tools/token_monitor.py",
    "tools/tool_auto_discovery.py",
    "tools/trigger_maintainer.py",
    "tools/unified_search.py",
    "tools/usecases_export.py",
    "tools/user_console.py",
    "tools/workflow_trigger_generator.py",
}


def _is_whitelisted(rel: str) -> bool:
    parts = set(rel.split("/"))
    if parts & WHITELIST_PARTS:
        return True
    return rel in WHITELIST or any(rel.startswith(d) for d in WHITELIST_DIRS)


def _iter_py_files():
    for path in SYSTEM_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SYSTEM_ROOT).as_posix()
        if _is_whitelisted(rel):
            continue
        yield path, rel


def _db_literal(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and (
        node.value in DB_FILENAMES or node.value.replace("\\", "/").endswith(tuple(f"/{n}" for n in DB_FILENAMES))
    )


def _is_path_home_call(node) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "home"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "Path"
    )


def _is_canonical_home_db(node: ast.BinOp) -> bool:
    """True fuer ``Path.home() / ".bach" / "bach.db"`` — den kanonischen Pfad.

    Diese eine Konstruktion ist erlaubt, und zwar genau dort, wo sie gebraucht
    wird: im Notfall-Fallback, wenn der Import der Registry selbst fehlschlaegt.
    Dann KANN der Pfad nicht mehr erfragt werden, er muss gebaut werden.

    Verboten bleibt jede Konstruktion, die woandershin zeigt — insbesondere die
    repo-relative ``.../data/bach.db`` (veraltete Cloud-Kopie bzw. Geister-DB).
    """
    left = node.left
    return (
        isinstance(left, ast.BinOp)
        and isinstance(left.op, ast.Div)
        and isinstance(left.right, ast.Constant)
        and left.right.value == ".bach"
        and _is_path_home_call(left.left)
    )


def _find_constructions(tree: ast.AST) -> list:
    """Findet Stellen, an denen ein DB-Dateiname zu einem Pfad komponiert wird."""
    hits = []

    for node in ast.walk(tree):
        # Form 1+2:  irgendwas / "bach.db"   bzw.  irgendwas / "data" / "bach.db"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if _db_literal(node.right) and not _is_canonical_home_db(node):
                hits.append(node.lineno)

        # Form 3:  os.path.join(BASE_DIR, "data", "bach.db")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "join" and any(_db_literal(a) for a in node.args):
                hits.append(node.lineno)

    return sorted(set(hits))


def _scan() -> dict:
    """Liefert {relativer Pfad: [Zeilennummern]} aller Eigenkonstruktionen."""
    found = {}

    for path, rel in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue  # Nicht-parsebare Dateien sind nicht Gegenstand dieser Regel.

        hits = _find_constructions(tree)
        if hits:
            found[rel] = hits

    return found


def test_kein_neues_modul_baut_den_db_pfad_selbst():
    """Neue oder zurueckgefallene Module duerfen den DB-Pfad nicht selbst bauen.

    Das ist die eigentliche Schutzfunktion: Sie faengt Rueckfaelle. Die bereits
    bekannte Alt-Schuld steht in KNOWN_OFFENDERS und wird hier geduldet.
    """
    found = _scan()
    neu = sorted(set(found) - KNOWN_OFFENDERS)

    assert not neu, (
        "Diese Dateien bauen den bach.db-Pfad selbst, statt ihn zentral zu erfragen:\n  "
        + "\n  ".join(f"{rel}:{','.join(map(str, found[rel]))}" for rel in neu)
        + "\n\nStattdessen die Registry fragen:\n"
        "    from hub.bach_paths import BACH_DB\n\n"
        "Liegt das Modul nicht im sys.path (Standalone-Start)? Dann davor:\n"
        '    _SYSTEM_ROOT = next(\n'
        '        p for p in Path(__file__).resolve().parents\n'
        '        if (p / "hub" / "bach_paths.py").exists()\n'
        "    )\n"
        "    sys.path.insert(0, str(_SYSTEM_ROOT))\n\n"
        "Ein selbst gebauter Pfad zeigt entweder auf die veraltete Cloud-Kopie "
        "(stille Alt-Daten) oder auf ein Verzeichnis, das es nicht gibt — dort "
        "legt sqlite3 dann still eine leere 0-KB-Datenbank an."
    )


def test_alt_schuld_liste_schrumpft_nur():
    """Sanierte Dateien muessen aus KNOWN_OFFENDERS entfernt werden.

    Ohne diesen Test verrottet die Baseline: Eintraege blieben stehen, obwohl die
    Datei laengst sauber ist — und niemand saehe mehr, wie gross die Restschuld
    wirklich ist.
    """
    found = _scan()
    erledigt = sorted(KNOWN_OFFENDERS - set(found))

    assert not erledigt, (
        "Diese Dateien bauen den DB-Pfad nicht mehr selbst (oder existieren nicht "
        "mehr) — bitte aus KNOWN_OFFENDERS in dieser Datei entfernen:\n  "
        + "\n  ".join(erledigt)
    )


def test_registry_liefert_die_kanonische_db():
    """Die Registry zeigt auf die lokale DB, nicht auf die Kopie im Cloud-Ordner."""
    import sys

    if str(SYSTEM_ROOT) not in sys.path:
        sys.path.insert(0, str(SYSTEM_ROOT))
    from hub.bach_paths import BACH_DB, ONEDRIVE_DB

    import os

    if os.environ.get("BACH_DB"):
        pytest.skip("BACH_DB ist per ENV ueberschrieben — kein Aussagewert.")

    local_db = Path.home() / ".bach" / "bach.db"
    if not (local_db.exists() and local_db.stat().st_size > 0):
        pytest.skip("Lokale DB fehlt — Registry faellt dann bewusst auf OneDrive zurueck.")

    assert BACH_DB == local_db, (
        f"Registry liefert {BACH_DB}, erwartet wurde die lokale DB {local_db}."
    )
    assert BACH_DB != ONEDRIVE_DB, (
        "Eine aktive WAL-SQLite-DB gehoert nicht in einen synchronisierten Cloud-Ordner."
    )
