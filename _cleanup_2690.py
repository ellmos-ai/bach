import os, glob, hashlib

base = '/Users/lukas/services/bach-worktrees/task-2690'
targets = sorted(glob.glob(os.path.join(base, 'system/tests/test_2690_*.py')))
removed = []
for p in targets:
    try:
        os.remove(p)
        removed.append(os.path.basename(p))
    except Exception as e:
        print(f"REMOVE_FAIL {os.path.basename(p)}: {e}")
print(f"REMOVED_COUNT {len(removed)}")
print(f"REMOVED {','.join(removed) if removed else 'NONE'}")

fixture = os.path.join(base, 'system/tests/test_worker_scope_snapshot.py')
if os.path.exists(fixture):
    h = hashlib.sha256()
    with open(fixture, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    print(f"SHA256 {h.hexdigest()}")
    print(f"SIZE {os.path.getsize(fixture)}")
else:
    print("FIXTURE_MISSING")
