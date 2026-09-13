# Review-Auftrag — :8081 "/activity"-Design (T-20260913-660268706, Punkt 7)

Du bist Reviewer für den Branch `fix/T-20260913-660268706-activity-design`
(BACH-Repo) gegen `origin/main`. Lies
`git diff origin/main..HEAD -- system/hub/_services/chat/telegram_chat.py`
vollständig. Kontext: Auftrag in `_codex/AUFTRAG-2.md` (Ziel: NUR
CSS-Farbtokens der `WEB_DASHBOARD`-Variable auf die BACH-GUI-Palette aus
`system/gui/static/css/main.css` umstellen, Funktion 1:1 erhalten — keine
Änderung an HTML-IDs, Klassennamen im `class`-Attribut, `onclick`-Handlern
oder `<script>`-Logik), Bericht des Autors in `_codex/BERICHT-2.md`.

Prüfe:
1. Sind wirklich NUR CSS-Werte im `<style>`-Block und die eine Inline-Style
   der Aktivitätsanzeige-Verlinkung geändert, keine Struktur-/ID-/
   Skript-Änderungen?
2. Stimmen die neuen CSS-Variablen exakt mit `main.css` überein (Zeilen 8-40
   dort)?
3. Bleiben die von JS referenzierten Selektoren `.btn`, `.btn:hover`,
   `.btn.active`, `.dot.green`/`.dot.red`/`.dot.yellow`, `#toast` erhalten?
4. Führe selbst einen Python-Syntax-Check der Datei aus (AST-Parse reicht,
   die Datei enthält ein reines String-Literal) und berichte das Ergebnis.

Urteil als APPROVE oder CHANGES-NEEDED, kurze Liste. Schreibe dein Ergebnis
nach `_codex/REVIEW-2.md`. Nenne am Ende exakt dein Modell.
