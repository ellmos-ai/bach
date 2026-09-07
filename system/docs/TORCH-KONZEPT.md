# Ollama-Torch: wer darf rechnen, und wie viel

Stand: 05.09.2026 · Zahlen gemessen auf mac-studio (32 GB, M1 Max)

Auf einem Rechner mit lokalen Modellen konkurrieren mehrere Parteien um
denselben Speicher: der Chat (interaktiv, soll ansprechbar sein), die
Hintergrundarbeit (Tasks abarbeiten) und Rechenjobs (Forschung, laufen
tagelang). Dieses Dokument definiert die Einheit, in der zugeteilt wird, und
die Regeln, nach denen entschieden wird.

## Grundsätze

Drei Festlegungen, die vor allen Zahlen stehen und beim Bauen nicht
unterschritten werden dürfen:

**1. Die Anlage ist nicht binär.** Der Verteiler kann beliebig viele Bewerber
gleichzeitig bedienen und Teilmengen zuteilen. Dass auf *diesem* Rechner
neben einem 27B-Modell nichts mehr passt, ist ein Messergebnis, keine
Eigenschaft des Systems. Schon hier gilt es nicht allgemein: `qwen3.5:4b`
(3,16 GiB) und `gemma4:e2b` (6,67 GiB) laufen problemlos nebeneinander. Wer die
Enge dieses Falls in die Architektur einbaut, macht sie auf dem nächsten
Rechner falsch.

Grundsatz 1 und 2 betreffen verschiedene Ebenen und widersprechen sich
nicht: Der **Umfang** ist klein (nur Modelle), die **Struktur** bleibt
mehrstellig. Wer `ist ein Modell geladen? ja/nein` implementiert, hat binär
gebaut und muss es auf dem nächsten Rechner wegwerfen. Wer `welche Bewerber
passen in neun Fackeln?` implementiert, bekommt hier dieselbe Antwort und
dort die richtige.

**2. Geregelt wird nur, was das Betriebssystem nicht regeln kann.** macOS
komprimiert auf diesem Rechner 43,2 GB Daten in 1,24 GB physischen Speicher
— eine Rate von 35:1 — und lagert zusätzlich aus. Für gewöhnliche Prozesse
ist jede Zuteilung, die wir darüberlegen, schlechter als das, was das System
ohnehin tut. Sie würde nur Arbeit verhindern, die problemlos gelaufen wäre.

Modelle entziehen sich dem: Sie laufen GPU-gebunden (auf Apple Silicon im
Unified Memory, `size_vram`), und GPU-Speicher wird weder komprimiert noch
ausgelagert. Er muss physisch da sein. **Der Verteiler regelt Modelle, nicht
Prozesse.**

**3. Gemessen, nicht gebucht.** Keine Tabelle darüber, wer wie viele Fackeln
hält — der Zustand wird erfragt (`vm_stat`, `/api/ps`). Eine Buchhaltung geht
auseinander, sobald ein Prozess ohne Abmeldung stirbt; eine Messung kann das
nicht. Dieselbe Lehre wie beim Timeout, siehe USMC-Lesson 77.

## Die Fackel

> **Zehn Fackeln pro System. Eine Fackel = ein Zehntel des modelltauglichen
> Speichers.**

Modelltauglich heißt: der Speicher, den ein Modell physisch belegen kann.
Die Messung ist plattformabhängig, die Regel nicht — und sie wird **erfragt,
nicht hergeleitet**, in dieser Reihenfolge:

| # | Quelle | gilt wenn |
|---|---|---|
| 1 | `BACH_FACKEL_KAPAZITAET_MB` | jemand hat die Grenze bewusst gesetzt |
| 2 | `sysctl iogpu.wired_limit_mb` | auf diesem Rechner explizit gesetzt (hier: `0`, also nicht) |
| 3 | Metal `recommendedMaxWorkingSetSize` | Apple Silicon — über `swift -` abfragbar, pyobjc nicht nötig |
| 4 | Summe `size_vram` aus `/api/ps` | Notnagel, wenn keine der drei greift |

Auf dedizierten GPUs tritt an Stelle 3 das VRAM der Karte, im reinen
CPU-Betrieb RAM minus `wired`.

> **Korrektur vom 05.09.2026.** Hier stand vorher „Apple Silicon: Default
> ~75 % RAM" — eine *erinnerte* Konstante, die 24 GB ergab und damit der im
> selben Dokument stehenden Messung von 28 GB widersprach. Der zweite
> Anlauf, `hw.memsize` minus `wired`, war ebenso falsch, nur unauffälliger:
> GPU-Speicher **ist** wired, der Nenner hätte sich mit dem bewegt, was er
> misst. Beides sind Verstöße gegen Grundsatz 3 im eigenen Dokument.

Gemessen auf mac-studio: Metal empfiehlt **26.800.603.136 Byte = 24,96 GiB**,
eine Fackel wiegt damit **2,50 GiB**.

> **Einheiten:** Alle Fackel-Angaben hier und in `fackel.py` sind **GiB**
> (2³⁰). Ollama meldet in Byte, `ollama list` zeigt dezimale GB — 18,17 GB
> und 16,93 GiB sind dieselben Gewichte. Wer beides mischt, liegt um 7 %
> daneben; bei 10 Fackeln ist das eine ganze.

Die Zahl „zehn" bleibt überall gleich, also bleiben Prioritätsregeln und
Meldungen übertragbar; die Größe einer Fackel folgt der Maschine. Dass
dasselbe Modell auf einem größeren Rechner **weniger** Fackeln kostet, ist
richtig — dort ist es auch weniger belastend. Die Zahl für einen anderen
Rechner wird dort gemessen, nicht hier ausgerechnet.

**Die Einheit darf nicht wandern.** Naheliegend wäre, als Kapazität das
Maximum aus Empfehlung und tatsächlich Geladenem zu nehmen. Dann wöge eine
Fackel im Leerlauf 2,50 GiB und bei geladenem 27B 2,80 GiB — zwei Messungen
desselben Rechners wären nicht mehr vergleichbar, und Vergleichbarkeit ist
der einzige Grund, warum die Zahl zehn überall gleich ist.

### Gemessener Bedarf auf mac-studio

| Bewerber | Bedarf | Fackeln (à 2,50 GiB) |
|---|---|---|
| Ollama 27B, 32k Kontext | 28,00 GiB `size_vram` | **11,2 — überbucht** |
| Ollama 27B, 8k Kontext | 20,85 GiB `size_vram` | 8,4 |
| `gemma4:e2b` (Gewichte) | 6,67 GiB | 2,7 |
| `qwen3.5:4b` (Gewichte) | 3,16 GiB | 1,3 |
| Claude Code (extern) | 0,75 GiB | 0,3 |

**Der bisher übersehene Befund: 32k Kontext liegt über der Empfehlung.**
Das 27B belegt dabei 11,2 Fackeln — mehr, als der Rechner nach Metals
Maßstab hat. Es lief trotzdem, weil die Empfehlung eine Komfortlinie ist
und keine Wand.

Was das für den Betrieb heißt, ist **offen und hier nicht behauptet.** Die
`Backend-Fehler:` der Nacht vom 04. auf den 05.09. hatten eine belegte
andere Ursache: den 180-Sekunden-Gesamttimeout, behoben durch das
Streaming. Ob die Randlage bei 32k zusätzlich beiträgt, ist eine
Vermutung ohne Messung. `BACH_CONTEXT_LIMIT` bleibt deshalb auf 32768 —
das ist ein Befund zur Entscheidung, keine stille Umkonfiguration.

Ungeklärt bleibt, ob Ollamas `size_vram` beim MLX-Backend dasselbe misst
wie Metals Empfehlung. Es kann echte Überbuchung sein oder ein Vergleich
zweier Maßstäbe. Wer dauerhaft negative Werte sieht, ohne dass etwas
bricht, setzt `BACH_FACKEL_KAPAZITAET_MB` und ist die Frage los.

**Der Kontext ist Verhandlungsmasse.** Das 27B wiegt selbst 16,93 GiB (Gewichte laut `/api/tags`); der
Rest ist Kontextspeicher. „Fackel ja, aber kleines Fenster" ist deshalb eine
gültige Antwort des Verteilers — für einen Chat reichen 8k (8,4 statt 11,2
Fackeln), nur die Bauarbeit braucht die großen.

**Delegation ist die effizienteste Zuteilung.** Claude Code kostet 0,3 statt
11,2 Fackeln. Nach außen zu geben räumt fast den ganzen Speicher frei — das ist
kein Notbehelf, sondern die beste verfügbare Antwort bei Knappheit.

## Drei Klassen — wichtiger als die Priorität

| Klasse | Beispiel | Bei Entzug |
|---|---|---|
| **unteilbar** | Modell | ganz oder gar nicht; Kontext verhandelbar |
| **pausierbar** | Rechenjob | `SIGSTOP`, Zustand bleibt im Speicher |
| **abbrechbar** | Worker-Paket | endet, Zustand liegt auf der Platte |

Einen unteilbaren Bewerber kann man nicht ein wenig zurückdrängen — das
entscheidet vor jeder Prioritätszahl.

## Die zwei Chat-Modi

| | **Chat-Modus** (Default) | **Interaktiv/Working** |
|---|---|---|
| Fackeln | gibt sie nach Ruhe zurück | behält, was gebraucht wird |
| Rückgabe nach | **10 min** ohne Nachricht | **1 h** ohne Nachricht **und** ohne Arbeitssignal |
| Kontext | klein (8k) genügt | groß, weil gebaut wird |
| Wechsel hinein | — | per Command oder durch den Auftrag, selbst zu bauen |

Beide Zeiten sind Voreinstellungen und vom Nutzer änderbar.

Der Cooldown existiert gegen **Flattern**: Ohne ihn entlädt jede Chatpause das
Modell, und die nächste Nachricht lädt es neu — auf diesem Rechner 17 GiB hin
und her und 35 Sekunden Wartezeit pro Nachricht (gemessen).

Im Working-Modus arbeitet der Nutzer mit: Er begleitet eine Programmieraufgabe,
gibt erweiterte Aufträge, korrigiert. Dann ist der Chat selbst die ausführende
Instanz und darf nicht mitten in der Arbeit entladen werden.

**Arbeitssignal, nicht Timer:** „Keine Nachrichten" ist kein Zustand. Ein
Modell, das gerade eine Datei schreibt, arbeitet, auch wenn niemand tippt. Als
Signal zählen Werkzeugaufrufe und Tokenfluss, nicht die Stille im Chat.

## Prioritäten

Absteigend, wobei die Klasse immer zuerst greift:

1. **Nutzer schlägt alles.** Sagt er „Priorität liegt jetzt hier", wird neu
   eingepreist.
2. **Direkt im Chat beauftragt** — sehr hoch, außer der Nutzer sagt
   ausdrücklich „nicht dringend, nur einstellen".
3. **Kurz und speicherhungrig** vor **lang und pausierbar**: Ein Job, der die
   Fackeln schnell wieder freigibt, kommt vor einem Tagelang-Läufer.
4. **Pausierbare Rechenjobs** — geben leicht ab und verlieren nichts, haben
   deshalb etwas weniger Anspruch.
5. **Wartung und Altlasten** — nur wenn Fackeln ohnehin frei sind.

**Bei anhaltendem Mangel delegieren:** Muss die Hintergrundinstanz mehrfach
hintereinander abgeben, versucht sie den Job an Claude Code, Codex oder einen
Cloud-Anbieter zu geben. Sind wieder Fackeln frei, kann zurückdelegiert werden.

## Stand der Umsetzung

**Gebaut am 05.09.2026** — `hub/_services/fackel.py` (16 Tests, `tests/test_fackel.py`):

| Funktion | beantwortet |
|---|---|
| `kapazitaet_bytes()` | wie viel dürfen Modelle belegen (Kette oben) |
| `belegt_bytes()` / `fremd_belegt_bytes(modell)` | was halten sie gerade |
| `modell_bytes(name)` | was fordert ein Bewerber (Gewichte aus `/api/tags`) |
| `frei(fuer_modell)` | freie Fackeln; negativ = überbucht |
| `passt(bedarf, fuer_modell)` | darf dieser Bewerber laden |
| `stand()` · `python3 -m hub._services.fackel` | alles auf einmal |

Drei Entwurfsentscheidungen, die im Betrieb tragen müssen:

- Das **eigene** Modell zählt nicht als Belegung. Ist es schon geladen,
  kostet seine Benutzung nichts — sonst sperrt sich der Worker an seiner
  eigenen Arbeit aus.
- **Nicht messbar heißt frei**, nicht blockiert: Die harte Grenze zieht
  Ollama selbst, der Verteiler entscheidet nur, wer fragen darf.
- **Der Bedarf wird nachgeschlagen, nicht auf null gesetzt.** Ein Gate mit
  Bedarf 0 fragt nur, ob das Fremde *allein schon* die Kapazität übersteigt
  — und das trifft fast nie zu. Fährt der Chat das 35B (20,40 GiB von
  24,96 GiB), blieben rechnerisch 4,56 GiB, und das 27B mit 16,93 GiB Gewichten
  wäre durchgewinkt worden; Ollama hätte dann den Chat hinausgeworfen. Ein
  Test bewacht genau diesen Unterschied.

**Verdrahtet** ist bisher genau eine Stelle, die dafür die richtige: das
Gate in `worker.py`. Es fragte bislang nur „ist der Chat still?" — das ist
die halbe Frage, denn still heißt nicht frei. Jetzt fragt es zusätzlich, ob
ein *fremdes* Modell den Speicher hält.

Vorhanden wie bisher: Compute-Lock (pausiert Rechenjobs für Ollama),
`agent_runners.py` (externe Anbieter), `limits.py` (Grenzen).

Offen: die zwei Chat-Modi (bisher nur Ollamas `keep_alive` mit 5m/30m statt
10min/1h), das Zurückdelegieren bei anhaltendem Mangel, und die Frage, ob
zehn Fackeln die richtige Körnung sind — das muss der Betrieb zeigen.
