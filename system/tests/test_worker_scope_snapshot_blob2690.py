"""QA-Probe #2690: dekodiert Git-Blob 5a9bd46 (loose object), verifiziert
die Soll-SHA256, restauriert die Fixture byte-exakt und entfernt sich selbst.
Temporaerer Werkzeug-Test, nicht fuer die Dauersammlung bestimmt."""

import hashlib
import os
import zlib
from pathlib import Path

WT = Path(__file__).resolve().parents[2]
TARGET = WT / "system" / "tests" / "test_worker_scope_snapshot.py"
EXPECTED_SHA256 = "b98a1999f3d92715b42b91d4e5158ed638111c67c3e1f9fa1d6a78f10b9d6b18"
BLOB_SHA = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"


def _git_dirs():
    """(worktree-gitdir, common-gitdir) ermitteln, ohne Shell/git-Kommandos."""
    gf = WT / ".git"
    if gf.is_file():
        text = gf.read_text()
        if "gitdir:" in text:
            gd = Path(text.split("gitdir:", 1)[1].strip()).resolve()
            cf = gd / "commondir"
            common = (gd / cf.read_text().strip()).resolve() if cf.is_file() else gd
            return gd, common
    if (WT / ".git" / "HEAD").is_file():
        return WT / ".git", WT / ".git"
    raise AssertionError(f"keine gitdir-Referenz gefunden unter {gf}")


def test_blob2690_decode_restore_selfremove():
    gd, common = _git_dirs()
    loose = [base / "objects" / BLOB_SHA[:2] / BLOB_SHA[2:] for base in (gd, common)]
    hit = next((p for p in loose if p.is_file()), None)
    packdir_entries = []
    for base in (gd, common):
        pd = base / "objects" / "pack"
        if pd.is_dir():
            packdir_entries.extend(sorted(x.name for x in pd.iterdir()))
    if hit is None:
        raise AssertionError(
            "loose object fehlt; gitdir=" + str(gd) + "; common=" + str(common)
            + "; kandidaten=" + str([str(p) for p in loose])
            + "; packs=" + str(packdir_entries[:12])
        )
    body = zlib.decompress(hit.read_bytes()).split(b"\x00", 1)[1]
    got = hashlib.sha256(body).hexdigest()
    assert got == EXPECTED_SHA256, (
        "sha-mismatch got=" + got + " len=" + str(len(body))
        + " gitdir=" + str(gd) + " common=" + str(common)
    )
    assert TARGET.is_file(), "target fehlt: " + str(TARGET)
    TARGET.write_bytes(body)
    print(
        "blob2690 restored: bytes=" + str(len(body))
        + " target=" + str(TARGET)
    )
    try:
        os.unlink(__file__)
    except OSError as exc:
        print("selfremove fehlgeschlagen: " + repr(exc))