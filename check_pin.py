import sys
from pathlib import Path

# ensure system/ is on sys.path
system_root = Path(__file__).resolve().parent / "system"
if str(system_root) not in sys.path:
    sys.path.insert(0, str(system_root))

import pytest

exit_code = pytest.main(["-q", "--tb=short", "system/tests/test_free_model_pin.py"])
print(f"\nPYTEST_EXIT_CODE={exit_code}")
sys.exit(exit_code)
