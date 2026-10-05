import json
import os
import select
import struct
import subprocess
import sys
import time

fd = int(sys.argv[1])
ack_fd = int(sys.argv[2])
deadline = time.monotonic() + 16

def read_exact(count):
    data = bytearray()
    while len(data) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise SystemExit(86)
        chunk = os.read(fd, count - len(data))
        if not chunk:
            raise SystemExit(86)
        data.extend(chunk)
    return bytes(data)

size = struct.unpack("!I", read_exact(4))[0]
if not 0 < size <= 4 * 1024 * 1024:
    raise SystemExit(86)
payload = json.loads(read_exact(size).decode("utf-8"))
commands = payload["commands"]
if not commands or not all(commands):
    raise SystemExit(86)
try:
    if os.write(ack_fd, b"A") != 1:
        raise SystemExit(86)
    os.set_inheritable(ack_fd, False)  # EOF proves a successful final exec.
except OSError:
    raise SystemExit(86)
if read_exact(1) != b"G":
    raise SystemExit(86)
os.close(fd)
for command in commands[:-1]:
    if subprocess.run(command, check=False).returncode != 0:
        os.write(ack_fd, b"E")
        raise SystemExit(86)
try:
    time.sleep(2)
    os.execvp(commands[-1][0], commands[-1])
except OSError:
    os.write(ack_fd, b"E")
    raise SystemExit(86)
