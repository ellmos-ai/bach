#!/usr/bin/env sh
set -eu
/Users/lukas/.venvs/bach/bin/python3 -c 'import time; time.sleep(6)'
exec /Users/lukas/.venvs/bach/bin/python3 -c 'from pathlib import Path; import time; Path('"'"'/Users/lukas/services/bach/system/.pytest_tmp/test_slow_successful_precomman0/final-started'"'"').write_text('"'"'started'"'"'); time.sleep(2)'
