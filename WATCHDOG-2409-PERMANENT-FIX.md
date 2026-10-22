# WATCHDOG-2409 – Dauerhafte Fixe für Mac-Speicherdruck-Watchdog (Referenzimplementierung)

**Task:** #2409 – Mac-Watchdog: Buddha-27B nicht bei normalem Speicherdruck entladen
**Zielhostskript:** `/Users/lukas/compute/abc_hct/compute_queue/memory_pressure_watchdog.sh`
**Stand dieses Dokuments:** Referenzimplementierung – KEIN exakter Diff. Die Hostquelldatei liegt außerhalb des Task-Lesebereichs (read_file auf Hostpfad blockiert); dieser Text beschreibt die Fixe so, dass sie auf dem Mac direkt einarbeitbar sind. Worktree: `/Users/lukas/services/bach-worktrees/task-2409`.

## Kontext

- **Sofortfix ist live** (zuletzt geprüft via `file_info`): Skript 26,4 KB, mtime 2026-10-22 04:44:18, Rechte 700, Commit/Stand SHA `e3463...`, Dienst neugestartet (PID 1219 → 1274).
- Sofortfix-Inhalt (bereits live, NICHT erneut implementieren):
  1. `pressure1` + `lowfree` ist **kein** Notfall-Unload mehr.
  2. Eskalation endet bei Rückkehr zu `pressure1`.
  3. Fehlendes `sysctl`-Ergebnis → Rückfall auf `warn2` (statt blindem Entladen).
- **Offen laut Task #2409** (dieses Dokument): (1) racefreie Fackel-/Idle-Maintenance-Koordination, (2) belastbare Behandlung fehlender/unbekannter Druckmessung, (3) natürliche Beobachtung eines Buddha-27B-Laufs.

## Fix 1 – HostInferenceGate: echte Laufprüfung statt Telegramflag (racefrei)

**Problem:** Bisher signalisiert (laut Tasklage) primär ein legacy Telegram-Flag, ob eine Inferenz läuft. Das ist unzuverlässig (Flag wird nicht gesetzt/zurückgesetzt) und raceanfällig: Der Watchdog kann zwischen „Lauf startet" und „Flag gesetzt" ein Unload entscheiden.

**Lösung:** Dreiklang aus Prozessprüfung, Idle-TTL und atomarem Abschnitt.

```bash
#!/bin/bash
# --- HostInferenceGate: aktive Inferenz erkennen, racefrei ---
WD_STATE_DIR="$HOME/.cache/memwatchdog"          # anlegen: mkdir -p, chmod 700
WD_LOCK="$WD_STATE_DIR/inference.lock"           # flock-Sperrdatei
WD_IDLE_FLAG="$WD_STATE_DIR/inference.idle"      # Idle-Markierung mit mtime
IDLE_TTL_SECONDS=300                              # 5 min ohne Laufstart = Idle annehmbar

# Aktive Modellprozesse prüfen (Musterliste an lokale Dienste anpassen)
wd_active_model_pids() {
  ps -axo pid=,rss=,command= \
    | grep -Ei 'ollama|llama|llm-serve|buddha|qwen|gguf|vllm' \
    | grep -vE 'grep|memory_pressure_watchdog' \
    | awk '$2 > 200000 {print $1}'   # >200 MB RSS = echtes Modell, kein Hilfsprozess
}

# Atomarer Gate-Abschnitt: konkurriert sicher mit Laufstart desselben Skripts.
# Jeder Modulstart (auch der Inferenzstarter) ruft wd_mark_inference_start()
# innerhalb desselben Locks auf -> kein Unload-Laufstart-Rennen mehr.
wd_mark_inference_start() {
  (
    flock -n 9 || { echo "$(date '+%F %T') GATE: Lock belegt, Start ignoriert" >> "$HOME/Library/Logs/memwatchdog.log"; exit 1; }
    rm -f "$WD_IDLE_FLAG"
    echo "$(date '+%s')" > "$WD_LOCK.start"   # letzter beobachteter Laufstart
  ) 9>"$WD_LOCK"
}

wd_inference_gate_allows_unload() {
  (
    flock -n 9 || return 1                    # Lock belegt -> niemals entladen
    local pids; pids="$(wd_active_model_pids)"
    if [ -n "$pids" ]; then
      echo "$(date '+%F %T') GATE: aktive Modell-PIDs: $pids -> kein Unload" >> "$HOME/Library/Logs/memwatchdog.log"
      return 1                               # aktive Prozesse -> kein Unload
    fi
    # Idle-Flag mit TTL: nur wenn seit IDLE_TTL kein Laufstart gesehen wurde
    if [ -f "$WD_LOCK.start" ]; then
      local last; last="$(cat "$WD_LOCK.start" 2>/dev/null || echo 0)"
      local age=$(( $(date '+%s') - last ))
      if [ "$age" -lt "$IDLE_TTL_SECONDS" ]; then
        echo "$(date '+%F %T') GATE: letzter Laufstart vor ${age}s < TTL -> kein Unload" >> "$HOME/Library/Logs/memwatchdog.log"
        return 1
      fi
    fi
    return 0                                  # echtes Idle -> Unload erlaubt
  ) 9>"$WD_LOCK"
}
```

**Einbauregel:** Jede Unload-Entscheidung im Watchdog wird durch `wd_inference_gate_allows_unload` UND `wd_mark_inference_start` (im Inferenzstartpfad von `compute_queue`) ersetzt bzw. ergänzt. Das Telegramflag wird nur noch als zusätzliche Absicherung gelesen, nie als alleinige Quelle. **Fehlentscheidung gilt immer zugunsten des Bestandsmodells: im Zweifel NICHT entladen.**

## Fix 2 – Fehlende/unbekannte Druckmessung: messen, wiederholen, zählen – nicht entladen

**Problem:** Ein leerer/unparsbarer `sysctl`-Wert darf (auch nach Sofortfix) nicht in eine Entladepfad-Logik kippen; heute ist es nur ein `warn2`-Rückfall, ohne Retry, ohne Zähler.

**Lösung:**

```bash
WD_FAIL_FILE="$WD_STATE_DIR/measure_fail_count"
MEASURE_RETRY_WAIT=30          # Sekunden bis zur nächsten Messung (naechste Iteration)
MEASURE_FAIL_WARN=3            # ab 3 Fehlversuchen zusaetzliche Warnstufe

wd_read_pressure() {
  local raw; raw="$(sysctl -n vm.memory_pressure 2>/dev/null)"
  case "$raw" in
    ''|*[!0-9]*)
      local fails=$(( $(cat "$WD_FAIL_FILE" 2>/dev/null || echo 0) + 1 ))
      echo "$fails" > "$WD_FAIL_FILE"
      echo "$(date '+%F %T') MEASURE: sysctl unlesbar/unbekannt ('${raw:-leer}'), Versuch $fails, kein Unload, Retry in ${MEASURE_RETRY_WAIT}s" >> "$HOME/Library/Logs/memwatchdog.log"
      return 1                                  # NIEMALS entladen bei fehlender Messung
      ;;
    *) rm -f "$WD_FAIL_FILE"; echo "$raw"; return 0 ;;
  esac
}

# In der Haupt-Iteration:
# if ! pressure="$(wd_read_pressure)"; then
#   sleep "$MEASURE_RETRY_WAIT"; continue        # Messung nach Warteintervall wiederholen
# fi
# [ "$(cat "$WD_FAIL_FILE" 2>/dev/null || echo 0)" -ge "$MEASURE_FAIL_WARN" ] && \
#   echo "$(date '+%F %T') MEASURE: WARNSTUFE - $MEASURE_FAIL_WARN+ Fehlmessungen" >> Log
```

**Invarianten:** Bestandsmodell bleibt geladen; Messung wird nach `MEASURE_RETRY_WAIT` wiederholt; Fehlversuche werden gezählt und ab `MEASURE_FAIL_WARN` als Warnstufe geloggt; Zähler wird bei erfolgreicher Messung zurückgesetzt.

## Fix 3 – Beobachtungsplan Buddha-27B-Lauf (nach Abschluss von #2419/#2420)

| Prüfpunkt | Erwartung |
|---|---|
| Modell geladen, Druck ~18 GB (Stufe 1 / pressure1) | **kein Unload**, normale Logmeldung |
| Druck 20–21 GB (Stufe 2) | Eskalation höchstens bis Grenzwarnung, **kein Notfall-Unload**, sofern Gate aktive Prozesse sieht |
| Unload generell | nur wenn Gate kein aktives Modell findet UND Idle-TTL abgelaufen |
| sysctl leer/unlesbar während des Laufs | kein Unload, `MEASURE:`-Eintrag + Retry |

**Protokollführung während des Laufs:** alle 60 s `ps eww` auf Modell-PIDs, `sysctl vm.memory_pressure`, `tail ~/Library/Logs/memwatchdog.log`; Zeitstempel und beobachtete Aktion festhalten; Ergebnis in Task #2409 dokumentieren. Vorbedingung: Fixe 1+2 sind auf dem Host angewendet, sonst keine belastbare Aussage möglich.

## Anleitung: Fixe auf dem Mac anwenden

1. **Lesezugriff erweitern oder direkt am Host arbeiten:** Die Quelle ist vom BACH-Worktree aus nicht lesbar (Task-Lesebereich). Entweder den Lesebereich auf `/Users/lukas/compute/abc_hct/` erweitern lassen und hier einen exakten Diff nachreichen, oder die Fixe 1+2 direkt am Host einarbeiten.
2. **Backup:** `cp memory_pressure_watchdog.sh memory_pressure_watchdog.sh.bak-$(date +%Y%m%d-%H%M%S)`
3. **Einbauen:** Funktionen aus Fix 1 und Fix 2 am Skriptkopf ergänzen; alle Entlade-/Eskalationsentscheidungen durch Gate-Aufruf ersetzen; Inferenzstartpfad um `wd_mark_inference_start` ergänzen.
4. **Syntaxprüfung:** `bash -n memory_pressure_watchdog.sh` (muss still sein).
5. **Dienst neu laden:** Label ermitteln (`launchctl list | grep -i watchdog`), dann `launchctl bootout gui/$UID/<label>` gefolgt von `launchctl bootstrap gui/$UID <plist-pfad>` – oder `launchctl kickstart -k gui/$UID/<label>`.
6. **Wirksamkeit prüfen:** `ps eww <pid>` zeigt neue Argumente/Umgebung; `tail -f ~/Library/Logs/memwatchdog.log` zeigt `GATE:`/`MEASURE:`-Zeilen.
7. **Gezielte Tests am Host:**
   - a) Normaldruck: Buddha-27B laden, künstlich Druck Richtung 20–21 GB – Watchdog darf NICHT entladen.
   - b) Fehlmessung: `sysctl`-Aufruf temporär stubben/Umgebung testen – Watchdog bleibt bei `warn2`/Retry, zählt Fehlversuche.
   - c) Idle-TTL: Modell stoppen, >300 s warten – erst jetzt darf der Unload erfolgen.

## Offene Restarbeit (nicht in diesem Lauf erledigbar)

- Hostfix noch **nicht** auf `/Users/lukas/compute/abc_hct/compute_queue/memory_pressure_watchdog.sh` angewendet (Host-Lese-/Schreibzugriff blockiert; execute_command nicht bestätigt).
- Buddha-27B-Laufbeobachtung ausstehend (nach #2419/#2420; Hostbeobachtung nötig).
- Nach Anwendung am Host: exakten Diff und Prüfergebnisse in Task #2409 nachreichen.