# E06 Alt-Pfad-Stilllegung – Scan-Befund

- **Task:** #1569
- **Quellen:** `data/agg_out.txt`, `data/healing_report.json`
- **Checkliste:** [`prep/E06_altpfad_stilllegung_checklist.md`](prep/E06_altpfad_stilllegung_checklist.md)
- **Generiert:** 2026-09-29

## Zusammenfassung

- Gescannte Dateien: **3454**
- Geheilte Dateien: **75**
- Fehler: **0**
- Alt-Pfad-Treffer gesamt: **296**
- Betroffene Dateien (unique pro Muster): **136**

## Alt-Pfad-Tabelle

| Alt-Pfad | Migration | Kategorie | Treffer (Zeilen) | Betroffene Dateien | Guarded |
|---|---|---|---|---|---|
| `_partners/` | `partners/` | Partner/Connectors | 1 | 1 | – |
| `_partners\` | `partners\` | Partner/Connectors | 3 | 2 | – |
| `exports/` | `system/exports/` | Export-Pfade | 16 | 10 | 16 |
| `exports\` | `system\exports\` | Export-Pfade | 14 | 6 | 14 |
| `from help.` | `from docs.help.` | Dokumentation (help) | 1 | 1 | 1 |
| `help/` | `docs/help/` | Dokumentation (help) | 93 | 24 | 93 |
| `help\` | `docs\help\` | Dokumentation (help) | 12 | 6 | 12 |
| `skills._agents.` | `agents.` | Agenten-Struktur | 1 | 1 | – |
| `skills._agents.ati.` | `agents.ati.` | Agenten-Struktur | 1 | 1 | – |
| `skills._agents.reflection` | `agents.reflection` | Agenten-Struktur | 1 | 1 | – |
| `skills._connectors.` | `connectors.` | Partner/Connectors | 1 | 1 | – |
| `skills/_agents/` | `agents/` | Agenten-Struktur | 14 | 9 | – |
| `skills/_agents/ati/` | `agents/ati/` | Agenten-Struktur | 14 | 7 | – |
| `skills/_connectors/` | `connectors/` | Partner/Connectors | 2 | 2 | – |
| `skills/_experts/` | `agents/_experts/` | Agenten-Struktur | 6 | 5 | – |
| `skills/_partners/` | `partners/` | Partner/Connectors | 2 | 2 | – |
| `skills/_services/` | `hub/_services/` | Hub-Services | 107 | 51 | – |
| `skills/_workflows/` | `skills/workflows/` | Workflows | 6 | 5 | – |
| `system/config/` | `system/data/config/` | Config | 1 | 1 | – |

**Legende:** `Guarded` = manuell geschützte Ersetzungen (kritische Pfade).

## Test-Ergebnis

- `data/pytest_tuev_handler.log`: **61 passed, 1 warning in 0.58s**

## TO-DECIDE

**A.** Sollen Alt-Pfad-Treffer in Backup-/Cache-Dateien unter `exports/translations/backup_*` ignoriert oder gelöscht werden, da sie vermutlich veraltete Duplikate enthalten?

**B.** Sollen die `guarded` Migrationen (`exports/` → `system/exports/`, `help/` → `docs/help/`) manuell validiert werden, weil sie zentrale Laufzeit- und Dokumentationspfade betreffen?

**C.** Soll `_partners` vollständig in `partners/` migriert oder komplett entfernt werden, da nur 4 Treffer in 3 Dateien existieren und der Pfad ggf. obsolet ist?

**D.** Soll der Treffer `system/config/` → `system/data/config/` als separates Refactoring-Dokument erfasst werden, da er Config-Daten im Dateisystem verschiebt?

## Nächste Schritte

1. Checkliste `prep/E06_altpfad_stilllegung_checklist.md` durcharbeiten.
2. TO-DECIDE A–D entscheiden und in Task #1569 / #1424 dokumentieren.
3. Nach Freigabe: verbleibende Alt-Pfad-Vorkommen entfernen oder final mappen.
