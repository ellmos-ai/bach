# Förderbericht: Identität bei der Ausgabe

Stand: 04.11.2026. Nur synthetische Testdaten; keine produktive Abnahme.

## SOLL

Die explizite Rückanonymisierungsoption bestimmt sowohl den Dateinamen als auch
profilbasierte Namens- und Datumsplatzhalter im Markdown-/Template-Fallback.
Bereits zurückübersetzte Originalwerte dürfen nicht nochmals als Tarnwerte
interpretiert werden. Der lokale Modus darf Originaldaten lokal verarbeiten;
der Cloud-Modus muss seine getrennten Anonymisierungsgates weiterhin erfüllen.

## IST dieser Änderung

- `auto_deanonymize=False` verwendet Tarnname und Tarndatum aus dem Profil für
  Dateiname und Platzhalter. Bereits im übergebenen Text vorhandene Originaldaten
  werden durch diese Option nicht nachträglich anonymisiert.
- `True` verwendet die Originalidentität. JSON wird einmal zurückübersetzt; der
  Markdown-Fallback erhält die unveränderte öffentliche Option und ein internes
  Kennzeichen für bereits übersetzten Inhalt.
- Text und rekursive JSON-Werte nutzen dieselbe simultane Rückersetzung. Längste
  überlappende Tarnwerte gewinnen; zurückgegebene Originalwerte werden nicht
  erneut durchsucht. Wortgrenzen und der Schutz von E-Mail-Teilnamen bleiben
  erhalten.
- Deterministische Regressionen prüfen Dateinamen und DOCX-Inhalte mit/ohne
  Template, lokale/Cloud-Profile, deaktivierte/aktive Rückanonymisierung, den
  JSON-Fallback und die Kollision `BEGRIFF_01` → `Frau Bergmann` gegenüber
  `Bergmann` → `Leonhardt`.

Unabhängiger Review, Merge, Deployment und ein Bericht mit realen Nutzerdaten
sind getrennte Schritte und werden damit nicht als abgeschlossen behauptet.
