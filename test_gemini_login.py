import shutil
import subprocess
import sys

def test_gemini_is_installed():
    gemini_path = shutil.which("gemini")
    assert gemini_path is not None, "gemini CLI ist nicht im PATH installiert"


def test_gemini_authenticated_and_responds_ok():
    result = subprocess.run(
        ["gemini", "-p", "Antworte nur mit OK"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print("stdout:", result.stdout, file=sys.stderr)
    print("stderr:", result.stderr, file=sys.stderr)
    print("returncode:", result.returncode, file=sys.stderr)
    assert result.returncode == 0, f"gemini beendete sich mit Fehlercode {result.returncode}"
    assert "OK" in result.stdout, f"Erwartete 'OK' in der Ausgabe, bekam: {result.stdout!r}"
