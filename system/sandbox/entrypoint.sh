#!/bin/sh
# BACH Sandbox Stufe 3 - Entrypoint (Task #1385)
# Aktuell delegiert docker run direkt an python3 (siehe Dockerfile
# ENTRYPOINT). Dieses Skript dokumentiert den vorgesehenen
# Erweiterungspunkt (z.B. seccomp-Profile, zusaetzliche Env-Filterung)
# und bleibt bewusst minimal.
exec python3 "$@"
