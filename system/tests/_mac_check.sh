#!/bin/bash
# Quick BACH check on Mac Studio
cd ~/Library/CloudStorage/OneDrive-Persönlich/.TOPICS/.AI/.OS/BACH 2>/dev/null || cd ~/OneDrive/.TOPICS/.AI/.OS/BACH 2>/dev/null
echo "PWD: $(pwd)"
echo "---"
ls -la system/bach.py system/gui/server.py start/bach.sh 2>&1
echo "---"

# Use venv python if available (FastAPI etc. only in venv)
if [ -f "$HOME/.venvs/bach/bin/python" ]; then
    PY="$HOME/.venvs/bach/bin/python"
elif [ -f "$HOME/.venvs/science/bin/python" ]; then
    PY="$HOME/.venvs/science/bin/python"
else
    PY=python3
fi
echo "Python: $PY"
PYTHONIOENCODING=utf-8 "$PY" -c "import sys; print('Version:', sys.version)"
echo "---"
echo "BACH paths test:"
PYTHONIOENCODING=utf-8 "$PY" -c "
import sys
sys.path.insert(0, 'system')
from hub import bach_paths as bp
print('DB:', bp.BACH_DB)
print('System:', bp.SYSTEM_ROOT)
print('DB exists:', bp.BACH_DB.exists())
"
echo "---"
echo "GUI server import test:"
PYTHONIOENCODING=utf-8 "$PY" -c "
import sys
sys.path.insert(0, 'system')
sys.path.insert(0, 'system/gui')
try:
    import fastapi
    print('FastAPI: OK')
except ImportError:
    print('FastAPI: MISSING')
try:
    import uvicorn
    print('uvicorn: OK')
except ImportError:
    print('uvicorn: MISSING')
"
echo "---"
echo "Services check:"
curl -s --max-time 3 http://127.0.0.1:8081/api/status > /dev/null 2>&1 && echo "Control API: ONLINE" || echo "Control API: OFFLINE"
curl -s --max-time 3 http://127.0.0.1:8000/ > /dev/null 2>&1 && echo "GUI Dashboard: ONLINE" || echo "GUI Dashboard: OFFLINE"
echo "--- DONE ---"
