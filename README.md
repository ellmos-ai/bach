# Gemini-Login auf dem Mac für die Um:bruch-Pipeline

## Ziel
Die `gemini`-CLI ist in der Pipeline als Schreib- und Gegenlese-Agent verfügbar.
Abnahmekriterium:
```bash
gemini -p "Antworte nur mit OK"
# Ausgabe enthält: OK
```

## Voraussetzung
`@google/gemini-cli` Version 0.63.0 ist bereits installiert (siehe Task-Beschreibung).

## Schritte

### 1. Direkt am Mac (mit GUI-Browser)
Öffne ein Terminal auf dem Mac und führe aus:
```bash
gemini
```
Folge den Anweisungen, um dich mit deinem Google-Konto anzumelden.
Sobald die Anmeldung abgeschlossen ist, beende die Sitzung wieder:
```bash
exit
```

### 2. Remote per SSH (kein GUI-Browser verfügbar)
Falls du nur per SSH auf dem Mac arbeitest:
```bash
NO_BROWSER=true gemini
```
Es wird ein Gerätecode oder Link ausgegeben. Öffne diesen Link oder gib den Code in einem Browser auf einem anderen Gerät ein, um die Anmeldung zu autorisieren. Danach beenden:
```bash
exit
```

## 3. Prüfung
Führe danach aus:
```bash
gemini -p "Antworte nur mit OK"
```
Die Ausgabe muss `OK` enthalten.

## Automatisierte Prüfung
Das beigefügte Skript `check_gemini.py` kann mit `python -m pytest check_gemini.py -q` gestartet werden. Es prüft:
1. `gemini` ist im `PATH` installiert.
2. `gemini -p "Antworte nur mit OK"` gibt `OK` zurück.
