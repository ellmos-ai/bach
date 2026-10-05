import subprocess,sys
from pathlib import Path
BACH_ROOT=Path(__file__).resolve().parents[2]
ABS_OUT="/Users/lukas/services/bach/data/temp/pytest_rueckfluss_planer.out"
with open(ABS_OUT,"w") as fh:
    proc=subprocess.run([sys.executable,"-m","pytest","tests/test_rueckfluss_planer.py","-v"],cwd=BACH_ROOT/"system",stdout=fh,stderr=subprocess.STDOUT)
    print("EXIT:%d"%proc.returncode)