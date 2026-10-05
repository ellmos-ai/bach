# BACH Sandbox Stufe 3 - Container-Image (Task #1385)
# Minimal-Image fuer isolierte Skript-Ausfuehrung.
# Haertung passiert zur Laufzeit via docker run (--network none,
# --read-only, cgroups-Limits) — siehe core/container_sandbox.py.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Nicht-root User: Skripte laufen nicht als root im Container
RUN useradd --create-home --uid 10001 sandbox
USER sandbox

WORKDIR /work

# KEIN ENTRYPOINT — build_docker_cmd in core/container_sandbox.py haengt
# "python3" als Kommando an (cmd += [img, "python3", script_rel]); ein
# ENTRYPOINT wuerde es doppelt anhaengen (python3 python3 script).
