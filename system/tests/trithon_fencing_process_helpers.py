"""Spawn targets without pytest imports; suite import paths stay unchanged.

Importing the pytest test module in a fresh child can load hub/email.py instead
of the standard library email package. Keep real multiprocessing targets in
this small helper, with only their original standard library/product imports.
"""

import os
import time


def _fencing_process(directory, index, operation, ready, start, results):
    """Real spawned process; widen the original read/write race deterministically."""
    from hub._services.trithon import fencing as child_fencing
    original = child_fencing._load_term

    def slow_read(path):
        state = original(path)
        time.sleep(0.1)
        return state

    child_fencing._load_term = slow_read
    ready.put(index)
    if not start.wait(15):
        raise RuntimeError("Parent did not release fixture processes")
    try:
        if operation == "register":
            child_fencing.register_node(directory, f"node-{index}", f"synthetic-{index}")
            result = index
        elif operation == "epoch":
            result = child_fencing.bump_epoch(directory)
        else:
            result = child_fencing.claim_lead(
                directory, f"node-{index}", f"synthetic-{index}",
                term=1 if operation == "explicit-claim" else None,
            )["term"]
        results.put(("ok", result))
    except child_fencing.FencingError as exc:
        results.put(("refused", str(exc)))


def _exit_while_holding_lock(directory, signal):
    from pathlib import Path

    from filelock import FileLock
    from hub._services.trithon import fencing as child_fencing

    with FileLock(str(Path(directory) / child_fencing.LOCK_FILE)):
        signal.send("locked")
        os._exit(23)
