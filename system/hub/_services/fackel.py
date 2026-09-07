# -*- coding: utf-8 -*-
"""Fackeln: wie viel Modellspeicher ist frei, und passt der naechste Bewerber?

Zehn Fackeln pro System, eine Fackel = ein Zehntel des modelltauglichen
Speichers. Die Zahl zehn ist ueberall gleich - dadurch bleiben
Prioritaetsregeln und Meldungen zwischen Rechnern uebertragbar. Die Groesse
einer Fackel ist es nicht: Sie folgt der Maschine (hier 2,50 GiB; auf
einem groesseren Rechner entsprechend mehr - dort gemessen, nicht hier
ausgerechnet).

Geregelt werden nur Modelle. Gewoehnliche Prozesse regelt das
Betriebssystem besser als wir - macOS komprimiert (gemessen 35:1) und
lagert aus. GPU-gebundener Speicher entzieht sich dem: Er wird weder
komprimiert noch ausgelagert, er muss physisch da sein. Nur deshalb
braucht es hier ueberhaupt eine Zuteilung.

Gemessen, nicht gebucht: Es gibt keine Tabelle darueber, wer wie viele
Fackeln haelt. Der Zustand wird erfragt. Eine Buchhaltung geht auseinander,
sobald ein Prozess ohne Abmeldung stirbt - eine Messung kann das nicht.

Die Anlage ist nicht binaer. Dass auf diesem Rechner meist ein Bewerber
alles bekommt, ist das Ergebnis der Rechnung, nicht ihre Form.

    python3 -m hub._services.fackel     # zeigt den Stand
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request

from hub._services.limits import limit

#: Zehn, ueberall. Siehe Modul-Docstring.
FACKELN = 10

_GIB = 1024 ** 3   # Alle Angaben in GiB - nie mit ollamas dezimalen GB mischen
_metal_cache: int | None = None


def _ollama_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    if not host.startswith("http"):
        host = "http://" + host
    return host.rstrip("/")


def _sysctl_bytes(name: str) -> int:
    """sysctl-Wert (in MB) als Bytes; 0 = nicht gesetzt oder nicht vorhanden."""
    try:
        p = subprocess.run(["sysctl", "-n", name], capture_output=True,
                           text=True, timeout=5)
        return int(p.stdout.strip()) * 1024 * 1024 if p.returncode == 0 else 0
    except Exception:
        return 0


def _metal_bytes() -> int:
    """Metals empfohlene Arbeitsmenge (Apple Silicon), 0 wenn nicht ermittelbar.

    Gemessen statt erinnert: pyobjc fehlt hier, aber die CommandLineTools
    bringen swift mit. Das Ergebnis wird gemerkt - es aendert sich zur
    Laufzeit nicht, und ein Subprozess je Abfrage waere Verschwendung.
    """
    global _metal_cache
    if _metal_cache is not None:
        return _metal_cache
    _metal_cache = 0
    quelle = ("import Metal\n"
              "print(MTLCreateSystemDefaultDevice()?"
              ".recommendedMaxWorkingSetSize ?? 0)\n")
    try:
        p = subprocess.run(["swift", "-"], input=quelle, capture_output=True,
                           text=True, timeout=60)
        if p.returncode == 0 and p.stdout.strip():
            _metal_cache = int(p.stdout.strip().splitlines()[-1])
    except Exception:
        pass
    return _metal_cache


def _ps_models() -> list[dict]:
    """Was Ollama gerade geladen hat. Die eine Nahtstelle - Tests ersetzen sie."""
    try:
        with urllib.request.urlopen(_ollama_url() + "/api/ps", timeout=5) as r:
            return json.load(r).get("models") or []
    except Exception:
        return []


def _ist_meins(geladen: str, modell: str) -> bool:
    """qwen3.8:27b-mlx und qwen3.8:latest sind dasselbe Modell.

    Gleiche Duldung wie OllamaBackend._lebt - die Tagvariante darf nicht
    als fremder Bewerber gelten, sonst haelt sich der Worker selbst auf.
    """
    if not modell:
        return False
    return geladen == modell or geladen.startswith(modell.split(":")[0])


def belegt_bytes() -> int:
    """Was Modelle gerade halten - Summe ueber size_vram aus /api/ps.

    Bewusst nicht vm_stat: GPU-Speicher ist auf Apple Silicon wired. Ein
    geladenes Modell senkt den freien Speicher UND wuerde die Kapazitaet
    senken, wenn man sie aus dem freien Rest ableitet. Der Nenner darf sich
    nicht mit dem bewegen, was er misst.
    """
    return sum(int(m.get("size_vram") or 0) for m in _ps_models())


def fremd_belegt_bytes(modell: str) -> int:
    """Was ANDERE Modelle halten.

    Das eigene zaehlt nicht: Ist es bereits geladen, kostet seine Benutzung
    keinen zusaetzlichen Speicher. Ohne diese Unterscheidung wuerde sich
    eine Instanz durch ihr eigenes Modell aussperren.
    """
    return sum(int(m.get("size_vram") or 0) for m in _ps_models()
               if not _ist_meins(m.get("name", ""), modell))


def _tags_models() -> list[dict]:
    """Was Ollama vorraetig hat. Zweite Nahtstelle - Tests ersetzen sie."""
    try:
        with urllib.request.urlopen(_ollama_url() + "/api/tags", timeout=5) as r:
            return json.load(r).get("models") or []
    except Exception:
        return []


def modell_bytes(name: str) -> int:
    """Gewichte dieses Modells laut /api/tags - die untere Schranke des Bedarfs.

    Der wirkliche Bedarf liegt hoeher, weil der Kontext dazukommt: Das 27B
    wiegt 16,93 GiB, belegt bei 32k aber 28,00 GiB. Die Gewichte sind
    trotzdem die brauchbare Zahl, denn sie muessen in jedem Fall physisch
    da sein - und sie stehen fest, bevor irgendetwas geladen wurde.

    Unbekanntes Modell ergibt 0. Dann laesst das Gate durch, statt auf
    einer fehlenden Auskunft eine Blockade zu bauen: Die harte Grenze zieht
    ohnehin Ollama.
    """
    if not name:
        return 0
    for m in _tags_models():
        if _ist_meins(m.get("name", ""), name):
            return int(m.get("size") or 0)
    return 0


def kapazitaet_bytes() -> int:
    """Wie viel Speicher Modelle physisch belegen duerfen.

    In dieser Reihenfolge, und alle vier gemessen statt erinnert:
      1. gesetzte Grenze - BACH_FACKEL_KAPAZITAET_MB
      2. iogpu.wired_limit_mb, falls jemand sie gesetzt hat
      3. Metals empfohlene Arbeitsmenge
      4. hilfsweise, was gerade geladen ist (kein Metal: kein Apple Silicon)

    Bewusst NICHT ``max(metal, belegt)``: Das haette die Fackelgroesse
    wandern lassen - 2,50 GiB im Leerlauf, 2,80 GiB bei geladenem 27B. Eine
    bewegliche Einheit macht Meldungen zwischen zwei Zeitpunkten
    unvergleichbar, und Vergleichbarkeit ist der einzige Grund, warum die
    Zahl zehn ueberall gleich ist.

    Offen und hier nicht entscheidbar: Ob Ollamas ``size_vram`` beim
    MLX-Backend dasselbe misst wie Metals Empfehlung. Auf diesem Rechner
    lief das 27B mit 28,0 GiB gegen eine Empfehlung von 24,96 GiB - das
    kann echte Ueberbuchung sein oder zwei verschiedene Massstaebe. Wer
    dauerhaft negative Werte sieht, ohne dass etwas bricht, setzt
    BACH_FACKEL_KAPAZITAET_MB und ist die Frage los.
    """
    gesetzt = limit("BACH_FACKEL_KAPAZITAET_MB") * 1024 * 1024
    return (gesetzt or _sysctl_bytes("iogpu.wired_limit_mb")
            or _metal_bytes() or belegt_bytes())


def fackel_bytes() -> int:
    """Groesse einer Fackel; 0 heisst: hier ist nichts messbar."""
    return kapazitaet_bytes() // FACKELN


def frei(fuer_modell: str = "") -> float:
    """Freie Fackeln.

    Mit ``fuer_modell`` aus Sicht dieses Bewerbers - sein eigenes, bereits
    geladenes Modell belegt ihn nicht. Nicht messbar (kein Ollama, kein
    Metal) ergibt volle Freiheit statt Blockade: Die harte Grenze zieht
    Ollama selbst, wir entscheiden nur, wer fragen darf.
    """
    f = fackel_bytes()
    if not f:
        return float(FACKELN)
    # Nach oben gedeckelt, weil die Fackelgroesse abgerundet wird und sonst
    # "10,1 von 10 frei" herauskaeme. Nach unten NICHT: Ein negativer Wert
    # heisst ueberbucht, und das kommt vor - Ollama laedt auch ueber Metals
    # Empfehlung hinaus. Diese Warnung soll sichtbar bleiben.
    return min(float(FACKELN),
               (kapazitaet_bytes() - fremd_belegt_bytes(fuer_modell)) / f)


def passt(bedarf_bytes: int | None = None, fuer_modell: str = "") -> bool:
    """Passt dieser Bewerber noch neben die fremden Modelle?

    Ohne ``bedarf_bytes`` werden die Gewichte von ``fuer_modell``
    nachgeschlagen. Das ist absichtlich der Vorgabefall: Ein Bedarf von 0
    fragt naemlich nicht "haelt ein Fremdes den Speicher?", sondern nur
    "uebersteigt das Fremde allein schon die Kapazitaet?" - und das trifft
    fast nie zu. Faehrt der Chat das 35B (20,40 GiB von 24,96 GiB), blieben
    rechnerisch 4,56 GiB uebrig, und ein Gate mit Bedarf 0 winkte das 27B
    durch, das allein 16,93 GiB Gewichte braucht. Ollama wuerfe dann das
    Chat-Modell hinaus -
    genau der Fall, den das Gate verhindern soll.
    """
    if not fackel_bytes():
        return True
    if bedarf_bytes is None:
        bedarf_bytes = modell_bytes(fuer_modell)
    return bedarf_bytes <= kapazitaet_bytes() - fremd_belegt_bytes(fuer_modell)


def stand(fuer_modell: str = "") -> dict:
    """Alles auf einmal - fuer Meldungen und den Selbsttest."""
    kap, bel, f = kapazitaet_bytes(), belegt_bytes(), fackel_bytes()
    if limit("BACH_FACKEL_KAPAZITAET_MB") or _sysctl_bytes("iogpu.wired_limit_mb"):
        quelle = "gesetzt"
    else:
        quelle = "metal" if _metal_bytes() else "geladen"
    return {
        "kapazitaet_gib": round(kap / _GIB, 2),
        "fackel_gib": round(f / _GIB, 2),
        "belegt_gib": round(bel / _GIB, 2),
        "belegt_fackeln": round(bel / f, 1) if f else 0.0,
        "frei_fackeln": round(frei(fuer_modell), 1),
        "modelle": [m.get("name", "?") for m in _ps_models()],
        "quelle": quelle,
    }


def main() -> int:
    s = stand()
    print(f"Kapazitaet   {s['kapazitaet_gib']} GiB  (Quelle: {s['quelle']})")
    print(f"1 Fackel     {s['fackel_gib']} GiB")
    print(f"belegt       {s['belegt_gib']} GiB = {s['belegt_fackeln']} Fackeln")
    print(f"frei         {s['frei_fackeln']} von {FACKELN} Fackeln")
    print(f"geladen      {', '.join(s['modelle']) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
