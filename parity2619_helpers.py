#!/usr/bin/env python3
"""Task 2619 helper (Worktree-only): check/sync/verify/cleanup via unittest."""
import os, re, unittest

ROOT = "/Users/lukas/services/bach-worktrees/task-2619"
CB = re.compile(r"```[^\n]*\n.*?```", re.S)
HP = re.compile(r"^(#{1,6}) ", re.M)
DN = re.compile(r"[A-ZÄÖÜ][A-ZÄÖÜ0-9_-]{3,}\.md")
H12 = re.compile(r"^#{1,2} ", re.M)
TARGETS = ("SKILL_EN.md", "SKILL_ES.md")

def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()

def _write(name, text):
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as fh:
        fh.write(text)

def _snapshot():
    de = _read("SKILL.md")
    return de, CB.findall(de), HP.findall(de)

def _hpdiff(hd, ht):
    return [(i, hd[i] if i < len(hd) else None, ht[i] if i < len(ht) else None)
            for i in range(max(len(hd), len(ht)))
            if (hd[i] if i < len(hd) else None) != (ht[i] if i < len(ht) else None)]

class TestCheck2619(unittest.TestCase):
    def test_run(self):
        de, cbd, hd = _snapshot()
        for name in TARGETS:
            t = _read(name)
            cbt, ht = CB.findall(t), HP.findall(t)
            ex = sorted(set(DN.findall(t)) - set(DN.findall(de)))
            print(name, "CB", len(cbt), "DE", len(cbd), "HP", len(ht), "DE", len(hd),
                  "H12", len(H12.findall(t)), "DOCextra", ex,
                  "fences", t.count("```"), "DEfences", de.count("```"))
            print(name, "HPdiff", _hpdiff(hd, ht))
            self.assertEqual(len(cbt), len(cbd), "CB mismatch " + name)

class TestSync2619(unittest.TestCase):
    def test_run(self):
        de, cbd, _ = _snapshot()
        for name in TARGETS:
            t = _read(name)
            cbt = CB.findall(t)
            self.assertEqual(len(cbt), len(cbd), "ABORT no-blind-replace " + name)
            out, pos = [], 0
            for i, mm in enumerate(CB.finditer(t)):
                out.append(t[pos:mm.start()])
                out.append(cbd[i])
                pos = mm.end()
            out.append(t[pos:])
            new = "".join(out)
            self.assertEqual(CB.findall(new), cbd, "FAILOUT " + name)
            if new != t:
                _write(name, new)
                print("SYNC", name, len(cbt), "Bloecke->DE")
            else:
                print("SKIP", name, "Blocks gleich")

class TestVerify2619(unittest.TestCase):
    def test_run(self):
        de, cbd, hd = _snapshot()
        ok = True
        for name in TARGETS:
            t = _read(name)
            cbt, ht = CB.findall(t), HP.findall(t)
            ex = sorted(set(DN.findall(t)) - set(DN.findall(de)))
            c1, c2, c3 = cbt == cbd, ht == hd, ex == []
            print("PASSCHECK", name, c1, c2, c3,
                  "H12", len(H12.findall(t)), "HP", len(ht), "CB", len(cbt))
            if not c1:
                print("CBdiff", name)
            if not c2:
                print("HPdiff", name, _hpdiff(hd, ht))
            if not c3:
                print("DOCextra", name, ex)
            ok = ok and c1 and c2 and c3
        self.assertTrue(ok, "STRICT parity failed")

class TestCleanup2619(unittest.TestCase):
    def test_run(self):
        here = os.path.join(ROOT, "parity2619_helpers.py")
        if os.path.exists(here):
            os.remove(here)
        pyc = os.path.join(ROOT, "__pycache__")
        if os.path.isdir(pyc):
            for fn in os.listdir(pyc):
                if fn.startswith("parity2619_helpers."):
                    os.remove(os.path.join(pyc, fn))
        self.assertFalse(os.path.exists(here), "helper noch vorhanden")

if __name__ == "__main__":
    unittest.main()