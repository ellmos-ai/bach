# Mac: LaunchAgents für Chat-Tray und Telegram-Bot

Versionierte Vorlagen: `system/launchd/com.bach.chat-tray.plist` und
`system/launchd/com.bach.telegram-bot.plist`. Sie starten über `/bin/zsh -lc` mit
`$HOME`-Pfaden (Live-Pfad `$HOME/services/bach`, Venv `$HOME/.venvs/bach`,
Logs `$HOME/Library/Logs/bach/`), also ohne festen Benutzernamen.

## OLLAMA_NUM_CTX = 16384

Ohne die Variable nimmt `OllamaBackend` `num_ctx = 4096`. Für Implementierungsaufgaben
reicht das nicht: Am 2026-09-26 brach der Idle-Worker (Task 1339) nach zwei
Kontext-Übergaben bei 5179 und 3579 Token mit „Kontext-Übergabe bleibt nach zwei
Versuchen zu groß“ ab. Gemessen auf dem Mac Studio (32 GB, `qwen3.8:27b-mlx`):

| Messung | Ergebnis |
|---|---|
| Modell frisch geladen, 16384 bzw. 32768 | je 18 GB, Druckstufe 1 (normal) – MLX reserviert KV nach Verbrauch |
| Workerlauf mit 32768 | Modell wuchs auf 20–21 GB, Druckstufe 2 (Warnung), 17 % frei |
| Prompt-Auswertung | ~50 Token/s (4516 Token in 84–88 s) |
| Workerlauf mit 32768, Ende | `ReadTimeout` nach 1856 s – ein Prompt nahe 32k braucht ~10 min pro Runde |

16384 ist das Vierfache des Standards, begrenzt das KV-Wachstum unter den Wert, der
die Warnstufe auslöste, und hält eine Runde bei höchstens ~5 min Prompt-Auswertung.

## Installation

```sh
cd ~/Library/LaunchAgents
cp -p com.bach.chat-tray.plist com.bach.chat-tray.plist.bak-$(date +%Y%m%d)
cp ~/services/bach/system/launchd/com.bach.chat-tray.plist .
launchctl bootout gui/$(id -u)/com.bach.chat-tray
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bach.chat-tray.plist \
  || launchctl kickstart -k gui/$(id -u)/com.bach.chat-tray
launchctl print gui/$(id -u)/com.bach.chat-tray | grep -E "state =|pid ="
```

Gleich für `com.bach.telegram-bot`. Beobachtet am 2026-09-26: `bootout` wirkt
asynchron; ein sofortiges `bootstrap` meldet dann „5: Input/output error“ und der Dienst
bleibt geladen, aber gestoppt (`state = not running`). `kickstart -k` startet ihn mit der
neuen Definition. Beim S2b-Rollout am selben Tag luden `bootstrap`-Aufrufe über SSH die
Dienste sogar sauber, starteten sie aber nicht (`state = not running` trotz `RunAtLoad`);
`kickstart -k` ist deshalb nach jedem `bootstrap` Pflicht. Danach immer den Zustand und die Umgebung des Prozesses prüfen
(`ps eww -o command= -p <pid> | tr ' ' '\n' | grep OLLAMA_NUM_CTX`).
