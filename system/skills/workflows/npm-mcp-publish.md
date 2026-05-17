# MCP Server Release Protokoll (NPM + GitHub)

> **Ziel:** Strukturierter Ablauf fuer das Veroeffentlichen von BACH MCP Servern auf GitHub und NPM.
> Gilt fuer: ellmos-filecommander-mcp, ellmos-codecommander-mcp

---

## Uebersicht

```
  ┌──────────────────────────────────────────────────────────────────┐
  │              MCP SERVER RELEASE WORKFLOW                         │
  ├──────────────────────────────────────────────────────────────────┤
  │                                                                  │
  │  Phase 1   Version Bump                                          │
  │     │      package.json, src/index.ts, CHANGELOG.md              │
  │     ▼                                                            │
  │  Phase 2   README & Docs aktualisieren                           │
  │     │      Features, Vergleichstabellen, Shared Tools            │
  │     ▼                                                            │
  │  Phase 3   Build                                                 │
  │     │      TypeScript kompilieren (Workaround beachten!)         │
  │     ▼                                                            │
  │  Phase 4   Git Commit + Tag                                      │
  │     │      Semantic Commit Message, vX.Y.Z Tag                   │
  │     ▼                                                            │
  │  Phase 5   GitHub Push                                           │
  │     │      git push origin master --tags                         │
  │     ▼                                                            │
  │  Phase 6   NPM Publish                                           │
  │            npm publish --ignore-scripts + Browser-Auth            │
  │                                                                  │
  └──────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Version Bump

Drei Dateien muessen synchron aktualisiert werden:

| Datei | Feld | Beispiel |
|-------|------|----------|
| `package.json` | `"version"` | `"1.4.1"` |
| `src/index.ts` | `version:` in Server-Config | `version: "1.4.1"` |
| `CHANGELOG.md` | Neuer `## [x.y.z]` Block | Datum + Aenderungen |

**Versionierung:** Semantic Versioning (semver)
- MAJOR: Breaking Changes
- MINOR: Neue Features/Tools
- PATCH: Bug-Fixes, Converter-Rewrites, Doc-Updates

---

## Phase 2: README & Docs

Checkliste fuer jedes Release:

- [ ] Tool-Beschreibungen in der Tabelle aktuell?
- [ ] "Why" Section - neue Highlights erwaehnt?
- [ ] Vergleichstabelle (FileCommander) aktuell?
- [ ] Shared Tools Tabelle (CodeCommander) aktuell?
- [ ] Tool-Anzahl korrekt? (38 / 14)
- [ ] Badge-Version wird automatisch von NPM gezogen

---

## Phase 3: Build

**WICHTIG - Bekanntes Problem:** Das `&` im Pfad `.AI` stoert `npm run build`.

**Workaround:** TypeScript direkt ueber Node aufrufen:

```bash
# FileCommander
node "%ONEDRIVE_AI_ROOT%\MCP\recludos-filecommander-mcp\node_modules\typescript\bin\tsc" --project "%ONEDRIVE_AI_ROOT%\MCP\recludos-filecommander-mcp\tsconfig.json"

# CodeCommander
node "%ONEDRIVE_AI_ROOT%\MCP\ellmos-codecommander-mcp\node_modules\typescript\bin\tsc" --project "%ONEDRIVE_AI_ROOT%\MCP\ellmos-codecommander-mcp\tsconfig.json"
```

Build ist erfolgreich wenn keine Ausgabe kommt (kein Output = kein Error).

---

## Phase 4: Git Commit + Tag

```bash
# Im Projektverzeichnis:
git add src/index.ts package.json CHANGELOG.md README.md
git commit -m "fix(tool): kurze beschreibung

Detaillierte Beschreibung der Aenderungen.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

git tag v1.4.1
```

**Commit-Prefixes:** `feat:` (neu), `fix:` (bugfix), `docs:` (doku), `chore:` (maintenance)

---

## Phase 5: GitHub Push

```bash
git push origin master --tags
```

Bei Tag-Updates (selbes Tag auf neuem Commit):
```bash
git tag -d v1.4.1                        # Lokal loeschen
git push origin :refs/tags/v1.4.1        # Remote loeschen
git tag v1.4.1                           # Neu setzen
git push origin master --tags            # Push mit neuem Tag
```

---

## Phase 6: NPM Publish

### Authentifizierung: Granular Access Token

NPM erfordert einen **Granular Access Token** mit "Bypass 2FA" fuer automatisiertes Publishing.
Classic Automation Tokens funktionieren NICHT mehr zuverlaessig (EOTP-Fehler).

**Aktueller Token:**
- Name: `bach-publisher 2`
- Typ: Granular Access Token (Read + Write, alle Packages)
- Erstellt: 2026-02-15
- Laeuft ab: **2026-05-16**
- Gespeichert in: `~/.npmrc` als `//registry.npmjs.org/:_authToken=...`

**Token erneuern (wenn abgelaufen):**
1. https://www.npmjs.com/settings/~/tokens → "Generate New Token"
2. **"Granular Access Token"** waehlen (NICHT Classic!)
3. Permissions: **Read and Write**, alle Packages
4. **"Bypass 2FA"** aktivieren (Checkbox!)
5. Token in `~/.npmrc` eintragen:
   `//registry.npmjs.org/:_authToken=<neuer-token>`

### Ablauf

```bash
# Token pruefen:
npm whoami    # -> muss "lukisch" ausgeben

# Publishen (kein OTP, kein Browser noetig):
cd <projektverzeichnis>
npm publish --ignore-scripts
```

### Warum --ignore-scripts?

Das `prepublishOnly` Script in package.json ruft `npm run build` auf,
was wegen des `&` im Pfad `.AI` fehlschlaegt. Da der Build bereits
manuell in Phase 3 erledigt wurde, wird er hier uebersprungen.

### Beide Server nacheinander

```bash
cd "%ONEDRIVE_AI_ROOT%\MCP\ellmos-filecommander-mcp"
npm publish --ignore-scripts

cd "%ONEDRIVE_AI_ROOT%\MCP\ellmos-codecommander-mcp"
npm publish --ignore-scripts
```

---

## Schnellreferenz

### Komplett-Workflow (Copy-Paste)

```bash
# Erst pruefen ob Token gueltig ist (laeuft ab 2026-05-16):
npm whoami    # -> "lukisch"

# === FileCommander ===
node "%ONEDRIVE_AI_ROOT%\MCP\ellmos-filecommander-mcp\node_modules\typescript\bin\tsc" --project "%ONEDRIVE_AI_ROOT%\MCP\ellmos-filecommander-mcp\tsconfig.json"
cd "%ONEDRIVE_AI_ROOT%\MCP\ellmos-filecommander-mcp"
git add -A && git commit -m "release: vX.Y.Z" && git tag vX.Y.Z && git push origin master --tags
npm publish --ignore-scripts

# === CodeCommander ===
node "%ONEDRIVE_AI_ROOT%\MCP\ellmos-codecommander-mcp\node_modules\typescript\bin\tsc" --project "%ONEDRIVE_AI_ROOT%\MCP\ellmos-codecommander-mcp\tsconfig.json"
cd "%ONEDRIVE_AI_ROOT%\MCP\ellmos-codecommander-mcp"
git add -A && git commit -m "release: vX.Y.Z" && git tag vX.Y.Z && git push origin master --tags
npm publish --ignore-scripts
```

---

## Verwandte Protokolle

- `dev-zyklus.md` - Allgemeiner Entwicklungszyklus
- `cli-aenderung-checkliste.md` - CLI-Aenderungen
- `docs/help/npm-publish.txt` - Kurzreferenz im Help-System
