#!/usr/bin/env bash
set -e
cd /Users/lukas/services/bach-worktrees/task-2993
python system/tests/test_http429_generator.py
echo "EXIT:$?"
