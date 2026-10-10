# SPDX-License-Identifier: MIT
"""
Ordnerwaechter fuer die Foerderbericht-Pipeline.

Beobachtet Berichte/data_roh/. Sobald genau ein Klienten-Ordner darin liegt
und sich eine Weile nicht mehr veraendert hat (Kopieren/Sync abgeschlossen),
startet die Pipeline im konfigurierten Modus. Ohne zusaetzliche
Abhaengigkeiten (Polling statt watchdog), damit es auf Mac und Windows
gleich laeuft.

    bach bericht watch                      # laeuft bis Strg+C
    bach bericht watch --once               # eine Pruefung (fuer Scheduler)
    bach bericht watch --modus lokal --intervall 30 --ruhe 60
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WatchState:
    """Merkt sich den letzten Stand zwischen zwei Pruefungen."""
    letzter_fingerabdruck: tuple | None = None
    fehlgeschlagen: set = field(default_factory=set)


def fingerabdruck(data_roh: Path) -> tuple | None:
    """Anzahl, Gesamtgroesse und juengste Aenderung aller Dateien."""
    files = [f for f in data_roh.rglob("*") if f.is_file() and not f.name.startswith(".")]
    if not files:
        return None
    stats = [f.stat() for f in files]
    return (len(files), sum(s.st_size for s in stats), max(s.st_mtime for s in stats))


def pruefe_eingang(base_path: Path, state: WatchState, ruhe_s: float,
                   jetzt: float | None = None) -> tuple[bool, str]:
    """Entscheidet, ob jetzt ein Lauf starten soll.

    Returns:
        (starten, grund) -- grund erklaert, warum (nicht) gestartet wird.
    """
    jetzt = time.time() if jetzt is None else jetzt
    data_roh = base_path / "data_roh"
    if (base_path / ".pipeline_lock").exists():
        return False, "Pipeline laeuft bereits"
    if not data_roh.exists():
        return False, "data_roh/ fehlt"
    ordner = [d for d in data_roh.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if len(ordner) > 1:
        return False, f"{len(ordner)} Klienten-Ordner in data_roh/ - bitte nur einen"
    fp = fingerabdruck(data_roh)
    vorher, state.letzter_fingerabdruck = state.letzter_fingerabdruck, fp
    if fp is None:
        return False, "keine Akte"
    if fp in state.fehlgeschlagen:
        return False, "Akte unveraendert seit fehlgeschlagenem Lauf"
    if jetzt - fp[2] < ruhe_s:
        return False, "Akte wird noch kopiert"
    if vorher is not None and vorher != fp:
        return False, "Akte hat sich seit der letzten Pruefung veraendert"
    return True, "Akte bereit"


def watch(pipeline_factory: Callable[[], object], modus: str | None = None,
          intervall_s: float = 30.0, ruhe_s: float = 60.0, once: bool = False,
          melden: Callable[[str], None] = print,
          sleep: Callable[[float], None] = time.sleep,
          max_laeufe: int | None = None,
          pipeline_kwargs: dict | None = None) -> int:
    """Beobachtet data_roh/ und startet die Pipeline.

    Args:
        pipeline_factory: Liefert eine FoerderberichtPipeline.
        modus: lokal, cloud oder hybrid (None: Konfiguration).
        intervall_s: Sekunden zwischen zwei Pruefungen.
        ruhe_s: So lange muss die Akte unveraendert sein.
        once: Nur eine Pruefung (fuer Aufgabenplanung/cron).
        melden: Ausgabe von Statusmeldungen.
        sleep, max_laeufe: fuer Tests.
        pipeline_kwargs: weitere Argumente fuer run_full_pipeline
            (z. B. berichtszeitraum, llm_backend, model, lokal_modell).

    Returns:
        Anzahl erfolgreich erstellter Berichte.
    """
    from hub._services.document.foerderbericht_modi import resolve_modus

    modus = resolve_modus(modus)
    state = WatchState()
    erfolgreich = 0
    laeufe = 0
    letzter_grund = None
    melden(f"Foerderbericht-Waechter aktiv (Modus {modus}).")
    while True:
        pipeline = pipeline_factory()
        base_path = Path(pipeline.base_path)
        # Bei --once zaehlt nur die Ruhezeit, es gibt keine Vorpruefung.
        if once:
            state.letzter_fingerabdruck = fingerabdruck(base_path / "data_roh")
        starten, grund = pruefe_eingang(base_path, state, ruhe_s)
        if starten:
            fp = state.letzter_fingerabdruck
            melden(f"Akte gefunden, starte Bericht (Modus {modus}) ...")
            try:
                result = pipeline.run_full_pipeline(modus=modus, **(pipeline_kwargs or {}))
            except Exception as exc:  # noqa: BLE001 - Waechter darf nicht sterben
                result = None
                fehler = str(exc)
            else:
                fehler = getattr(result, "error", "")
            laeufe += 1
            if result is not None and getattr(result, "success", False):
                erfolgreich += 1
                # Dateiname nicht nennen: er enthaelt den Klarnamen.
                melden("Bericht fertig in output_berichte/.")
            else:
                state.fehlgeschlagen.add(fp)
                melden(f"Bericht fehlgeschlagen: {fehler}. Die Akte bleibt liegen; "
                       f"nach einer Aenderung wird es erneut versucht.")
            letzter_grund = None
        elif grund != letzter_grund and grund not in ("keine Akte",):
            melden(grund)
            letzter_grund = grund
        if once or (max_laeufe is not None and laeufe >= max_laeufe):
            return erfolgreich
        sleep(intervall_s)
