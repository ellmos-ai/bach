# -*- coding: utf-8 -*-
"""Tests fuer die Fackel-Zuteilung.

Ein echtes Modell zum Messen zu laden kostet 18 GB und verdraengt den
laufenden Rechenjob - also wird /api/ps gefaelscht. Die Zahlen darin sind
die am 05.09.2026 auf mac-studio gemessenen: Metal empfiehlt 26,80e9 Byte,
das 27B lief mit 30,06e9 (28,0 GiB) und damit darueber.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hub._services import fackel  # noqa: E402

METAL = 26_800_603_136          # gemessen: recommendedMaxWorkingSetSize
VRAM_27B_32K = 30_064_771_072   # gemessen: size_vram bei 32k Kontext
VRAM_27B_8K = 22_393_706_992    # gemessen: size_vram bei kleinem Fenster


GEWICHT_27B = 18_174_721_847    # gemessen: /api/tags size qwen3.8:27b-mlx
GEWICHT_35B = 21_909_210_142    # gemessen: /api/tags size qwen3.6:35b-mlx
GEWICHT_E2B = 7_162_405_886     # gemessen: /api/tags size gemma4:e2b

VORRAT = [{"name": "qwen3.8:27b-mlx", "size": GEWICHT_27B},
          {"name": "qwen3.6:35b-mlx", "size": GEWICHT_35B},
          {"name": "gemma4:e2b", "size": GEWICHT_E2B}]


def _stelle(geladen, metal=METAL, sysctl=0, kap_env=0, vorraetig=None):
    """Messquellen ersetzen. Jeder Test setzt alle, deshalb braucht es
    kein Aufraeumen zwischendurch."""
    fackel._ps_models = lambda: list(geladen)
    fackel._tags_models = lambda: list(VORRAT if vorraetig is None else vorraetig)
    fackel._metal_bytes = lambda: metal
    fackel._sysctl_bytes = lambda _name: sysctl
    if kap_env:
        os.environ["BACH_FACKEL_KAPAZITAET_MB"] = str(kap_env)
    else:
        os.environ.pop("BACH_FACKEL_KAPAZITAET_MB", None)


def _modell(name, vram):
    return {"name": name, "size_vram": vram}


def test_leer_sind_alle_fackeln_frei():
    _stelle([])
    assert fackel.frei() == 10.0
    assert fackel.passt(0)


def test_eigenes_modell_sperrt_nicht_aus():
    """Ist mein Modell schon geladen, kostet seine Benutzung nichts extra -
    sonst haelt sich der Worker an seiner eigenen Arbeit auf."""
    _stelle([_modell("qwen3.8:27b-mlx", VRAM_27B_32K)])
    assert fackel.fremd_belegt_bytes("qwen3.8:27b-mlx") == 0
    assert fackel.frei("qwen3.8:27b-mlx") == 10.0
    assert fackel.passt(0, "qwen3.8:27b-mlx")


def test_tagvariante_gilt_als_eigenes():
    _stelle([_modell("qwen3.8:latest", VRAM_27B_32K)])
    assert fackel.fremd_belegt_bytes("qwen3.8:27b-mlx") == 0


def test_fremdes_modell_nimmt_alle_fackeln():
    _stelle([_modell("qwen3.6:35b-mlx", VRAM_27B_32K)])
    assert fackel.frei("qwen3.8:27b-mlx") <= 0.0, "fremdes Modell haelt alles"
    assert not fackel.passt(1, "qwen3.8:27b-mlx")


def test_einheit_bleibt_stabil_bei_ueberbuchung():
    """Metal empfiehlt 24,96 GiB, geladen waren nachweislich 28,0 GiB.

    Die Fackel darf davon nicht groesser werden - sonst waeren zwei
    Messungen desselben Rechners nicht mehr vergleichbar. Stattdessen wird
    die Ueberbuchung sichtbar: negative freie Fackeln.
    """
    _stelle([_modell("fremd:35b", VRAM_27B_32K)])
    assert fackel.kapazitaet_bytes() == METAL, "Einheit bleibt bei Metal"
    assert fackel.frei("qwen3.8:27b-mlx") < 0, "Ueberbuchung wird gemeldet"


def test_geladenes_modell_nur_als_notnagel():
    """Ohne Metal (kein Apple Silicon) dient das Geladene als Boden."""
    _stelle([_modell("fremd:7b", 8_000_000_000)], metal=0)
    assert fackel.kapazitaet_bytes() == 8_000_000_000


def test_metal_gilt_wenn_nichts_laeuft():
    _stelle([])
    assert fackel.kapazitaet_bytes() == METAL
    assert round(fackel.fackel_bytes() / 2**30, 1) == 2.5


def test_gesetzte_grenze_schlaegt_messung():
    _stelle([_modell("fremd:7b", 5_000_000_000)], kap_env=20_000)
    assert fackel.kapazitaet_bytes() == 20_000 * 1024 * 1024


def test_sysctl_vor_metal():
    _stelle([], sysctl=16 * 1024**3)
    assert fackel.kapazitaet_bytes() == 16 * 1024**3


def test_nicht_messbar_blockiert_nicht():
    """Kein Ollama, kein Metal: Die harte Grenze zieht Ollama selbst -
    wir wuerden sonst auf einem gesunden System jede Arbeit verhindern."""
    _stelle([], metal=0)
    assert fackel.fackel_bytes() == 0
    assert fackel.frei() == 10.0
    assert fackel.passt(99 * 2**30) is True


def test_zwei_kleine_modelle_nebeneinander():
    """Die Anlage ist nicht binaer: gemma4:e2b (7,2 GB) und qwen3.5:4b
    (3,4 GB) passen gemeinsam - das muss der Verteiler auch sagen."""
    _stelle([_modell("gemma4:e2b", int(7.2 * 10**9))])
    assert fackel.passt(int(3.4 * 10**9), "qwen3.5:4b"), "beide passen zusammen"
    assert 5.0 < fackel.frei("qwen3.5:4b") < 10.0


def test_gate_haelt_wenn_der_chat_sein_modell_faehrt():
    """Der Fall, um den es wirklich geht: Das 35B des Chats haelt 21,9 GB
    von 26,8 GB. Rechnerisch bleiben 4,9 GB - das 27B braucht aber allein
    18,2 GB Gewichte. Ollama wuerfe den Chat hinaus."""
    _stelle([_modell("qwen3.6:35b-mlx", GEWICHT_35B)])
    assert fackel.modell_bytes("qwen3.8:27b-mlx") == GEWICHT_27B
    assert not fackel.passt(fuer_modell="qwen3.8:27b-mlx")


def test_gate_laesst_neben_kleinem_modell_durch():
    """Nicht binaer: Neben gemma4:e2b (7,2 GB) bleiben 19,6 GB - die
    Gewichte des 27B passen dort hinein."""
    _stelle([_modell("gemma4:e2b", GEWICHT_E2B)])
    assert fackel.passt(fuer_modell="qwen3.8:27b-mlx")


def test_bedarf_null_waere_der_fehler_gewesen():
    """Regressionswaechter fuer die Vorgabe von passt().

    Mit ``bedarf=0`` lautet die Frage nur "uebersteigt das Fremde allein
    schon die Kapazitaet?" - und die ist hier mit Nein zu beantworten,
    obwohl kein Platz ist. Die Vorgabe muss deshalb None bleiben."""
    _stelle([_modell("qwen3.6:35b-mlx", GEWICHT_35B)])
    assert fackel.passt(0, "qwen3.8:27b-mlx"), "so sah der Fehler aus"
    assert not fackel.passt(fuer_modell="qwen3.8:27b-mlx"), "so ist es richtig"


def test_unbekanntes_modell_blockiert_nicht():
    _stelle([_modell("gemma4:e2b", GEWICHT_E2B)], vorraetig=[])
    assert fackel.modell_bytes("gibtsnicht:1b") == 0
    assert fackel.passt(fuer_modell="gibtsnicht:1b")


def test_stand_meldet_quelle():
    _stelle([])
    assert fackel.stand()["quelle"] == "metal"
    _stelle([_modell("fremd:7b", 8_000_000_000)], metal=0)
    assert fackel.stand()["quelle"] == "geladen"
    _stelle([], kap_env=20_000)
    assert fackel.stand()["quelle"] == "gesetzt"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        zurueck = None
        try:
            fn()
            print(f"OK    {name}")
        except AssertionError as e:
            fails += 1
            print(f"FEHL  {name}: {e}")
        except Exception as e:
            fails += 1
            print(f"FEHL  {name}: {type(e).__name__}: {e}")
    print(f"\n{'ALLE GRUEN' if not fails else str(fails) + ' FEHLGESCHLAGEN'}")
    sys.exit(1 if fails else 0)
