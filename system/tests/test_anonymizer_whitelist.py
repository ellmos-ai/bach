# -*- coding: utf-8 -*-
"""
Tests fuer Amtspersonen-Whitelist im AnonymProfile (Task #801).

Anforderung: Sachbearbeiter-Namen (Amtspersonen) duerfen NICHT
anonymisiert werden. Die Whitelist wird IM PROFIL gefuehrt und
ueberlebt damit den encrypt/decrypt-Key-File-Roundtrip.

Abgedeckt:
  1. create_profile(...) nimmt whitelist-Parameter ins Profil auf
  2. whitelisted Namen erhalten kein Mapping (names)
  3. _sorted_replacements filtert whitelisted Mapping-Keys (letzte
     Verteidigungslinie)
  4. encrypt_key_file / decrypt_key_file Roundtrip erhaelt whitelist
  5. End-to-End: Textanonymisierung laesst Sachbearbeiter unberuehrt
"""
import os
import sys
import tempfile
from pathlib import Path

# Projekt-Root auf sys.path (Tests laufen aus tests/)
sys.path.insert(0, str(Path(__file__).parent.parent))

from hub._services.document.anonymizer_service import (
    AnonymProfile,
    DocumentAnonymizer,
    decrypt_key_file,
    encrypt_key_file,
)

try:
    import cryptography  # noqa: F401
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


def _make_anonymizer():
    return DocumentAnonymizer()


def test_profile_carries_whitelist():
    """Whitelist-Parameter von create_profile landet im Profil (Task #801)."""
    anon = _make_anonymizer()
    profile = anon.create_profile(
        real_name="Max Mustermann",
        geburtsdatum="15.03.2016",
        whitelist=["Sandra Behrend", "Dr. Klemens Vogt"],
    )
    assert profile.whitelist, "Whelist fehlt im Profil"
    wl_lower = {w.lower() for w in profile.whitelist}
    assert "sandra behrend" in wl_lower
    assert "dr. klemens vogt" in wl_lower


def test_whitelisted_name_gets_no_mapping():
    """Amtspersonen aus der Whitelist erhalten KEIN names-Mapping."""
    anon = _make_anonymizer()
    profile = anon.create_profile(
        real_name="Max Mustermann",
        geburtsdatum="15.03.2016",
        weitere_namen=["Sandra Behrend", "Erika Mustermann"],
        whitelist=["Sandra Behrend"],
    )
    names = profile.mappings.get("names", {})
    assert "Sandra Behrend" not in names, "Sachbearbeiter darf kein Mapping haben"
    # Nicht-whitelisted weitere Namen MUESSEN gemappt werden
    assert "Erika Mustermann" in names
    # Klient selbst bleibt gemappt
    assert names.get("Max Mustermann") == profile.tarnname


def test_sorted_replacements_filters_whitelist():
    """Letzte Verteidigungslinie: whitelisted Keys werden aus Replacements gefiltert."""
    anon = _make_anonymizer()
    profile = AnonymProfile(
        client_id="K_TEST",
        tarnname="Felix Bergmann",
        fake_geburtsdatum="22.07.2016",
        mappings={"names": {
            "Max Mustermann": "Felix Bergmann",
            "Sandra Behrend": "Tarnname Falsch",  # bewusst eingestreutes Mapping
        }},
        whitelist=["sandra behrend"],  # Case-Variante muss auch matchen
    )
    replacements = dict(anon._sorted_replacements(profile))
    assert "Sandra Behrend" not in replacements, "Whitelisted Key muss gefiltert werden"
    assert "Max Mustermann" in replacements


def test_deanonymize_reverse_profile_not_filtered():
    """Reverse-Profil (Deanonymize) hat leere Whitelist -> Tarnnamen kehren zurueck."""
    anon = _make_anonymizer()
    profile = AnonymProfile(
        client_id="K_TEST",
        tarnname="",
        fake_geburtsdatum="",
        mappings={"names": {"Felix Bergmann": "Max Mustermann"}},
    )
    replacements = dict(anon._sorted_replacements(profile))
    assert replacements.get("Felix Bergmann") == "Max Mustermann"


def test_key_file_roundtrip_keeps_whitelist():
    """Whitelist ueberlebt encrypt_key_file -> decrypt_key_file (Task #801 Kern)."""
    if not CRYPTO_AVAILABLE:
        print("  [SKIP] cryptography nicht installiert")
        return
    anon = _make_anonymizer()
    profile = anon.create_profile(
        real_name="Max Mustermann",
        geburtsdatum="15.03.2016",
        weitere_namen=["Erika Mustermann"],
        whitelist=["Sandra Behrend"],
    )
    with tempfile.TemporaryDirectory() as tmp:
        key_path = os.path.join(tmp, "test.schluessel.enc")
        pw = "top-secret-801"
        encrypt_key_file(profile, key_path, pw)
        loaded = decrypt_key_file(key_path, pw)
        wl_loaded = {w.lower() for w in loaded.whitelist}
        assert "sandra behrend" in wl_loaded, "Whitelist fehlt nach Roundtrip"
        names_loaded = {k.lower() for k in loaded.mappings.get("names", {})}
        assert "max mustermann" in names_loaded, "Mappings nach Roundtrip unvollstaendig"


def test_e2e_text_anonymization_spared_officials():
    """End-to-End: .txt mit Klient + Sachbearbeiter -> nur Klient wird ersetzt."""
    anon = _make_anonymizer()
    profile = anon.create_profile(
        real_name="Max Mustermann",
        geburtsdatum="15.03.2016",
        weitere_namen=["Erika Mustermann"],
        whitelist=["Sandra Behrend"],
    )
    original = (
        "Familie Mustermann: Max Mustermann (geb. 15.03.2016) und Erika Mustermann. "
        "Sachbearbeiterin Sandra Behrend vom Amt hat den Bescheid erstellt."
    )
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "akte.txt"
        src.write_text(original, encoding="utf-8")
        ok, count = anon.anonymize_file(str(src), profile)
        assert ok, "anonymize_file schlug fehl"
        result = src.read_text(encoding="utf-8")
        assert "Sandra Behrend" in result, "Amtsperson wurde fälschlich anonymisiert!"
        assert "Max Mustermann" not in result, "Klient wurde nicht anonymisiert!"
        assert "15.03.2016" not in result, "Geburtsdatum wurde nicht anonymisiert!"
        assert profile.tarnname in result


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted({k: v for k, v in globals().items()
                            if k.startswith("test_") and callable(v)}.items()):
        try:
            fn()
            print(f"[PASS] {name}")
        except AssertionError as e:
            failures += 1
            print(f"[FAIL] {name}: {e}")
        except Exception as e:
            failures += 1
            print(f"[ERR ] {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failures else 0)