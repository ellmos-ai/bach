#!/bin/bash
set -e
cd /Users/lukas/services/bach-worktrees/task-2563
python system/bach.py testing/run_pytest system/tests/test_free_model_pin.py -q
