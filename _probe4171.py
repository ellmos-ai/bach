"""Probe: Kopf des Diffs worker_result_review.py (nur Diagnose, wird geloescht)."""
import subprocess

OUT = subprocess.run(
    ["git", "diff", "HEAD", "--", "system/hub/_services/worker_result_review.py"],
    capture_output=True,
    text=True,
    check=False,
).stdout.splitlines()


def test_dump():
    print("HEAD-BEREICH")
    for i, line in enumerate(OUT[:54], start=1):
        print(f"{i:04d}|{line}")
    assert True
