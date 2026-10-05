#!/usr/bin/env python3
"""Einmaliges Reparatur-Skript fuer BACH Workflow-Markdown-Dateien.

Behebt:
- fehlende YAML-Frontmatter
- fehlende H1 / Description / Changelog / Footer
- fehlerhafte type-Werte (z.B. protocol statt workflow)

Arbeitet atomar: tempfile + rename. Erstellt .bak-Backups.
"""

import re
import os
import tempfile
from pathlib import Path
from datetime import datetime

WF_DIR = Path('/Users/lukas/services/bach/system/skills/workflows')
BACKUP_DIR = WF_DIR / '.backup_2026_fix_workflows'
TODAY = datetime.now().strftime('%Y-%m-%d')

REQUIRED_FM = [
    'name', 'version', 'type', 'author', 'created', 'updated',
    'anthropic_compatible', 'description',
]

FOOTER = """---

## Changelog

| Version | Datum | Aenderung |
|---------|-------|-----------|
| 1.0.0   | {today} | Initiale Version |

---

*BACH Skill-Architektur v2.0 – Workflows & Skills*"""


def parse_frontmatter(text: str):
    """Gibt (frontmatter_dict, body, end_pos) oder (None, text, 0) zurueck."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not m:
        m = re.match(r'^---\s*\n(.*?)\n---\s*$', text, re.DOTALL)
    if not m:
        return None, text, 0
    fm_text = m.group(1)
    body = text[m.end():]
    fm = {}
    for line in fm_text.splitlines():
        if ':' in line and not line.startswith(' '):
            k, _, v = line.partition(':')
            fm[k.strip()] = v.strip()
    return fm, body, m.end()


def fm_to_yaml(fm: dict) -> str:
    """Minimaler YAML-Header ohne externe Abhaengigkeit."""
    lines = ['---']
    for k in REQUIRED_FM:
        if k in fm:
            v = fm[k]
            if '\n' in str(v):
                lines.append(f'{k}: >')
                for vl in str(v).splitlines():
                    lines.append(f'  {vl}')
            else:
                lines.append(f'{k}: {v}')
    # Zusaetzliche Felder erhalten
    for k, v in fm.items():
        if k in REQUIRED_FM:
            continue
        if '\n' in str(v):
            lines.append(f'{k}: >')
            for vl in str(v).splitlines():
                lines.append(f'  {vl}')
        else:
            lines.append(f'{k}: {v}')
    lines.append('---')
    return '\n'.join(lines) + '\n'


def slug_to_title(name: str) -> str:
    return name.replace('-', ' ').replace('_', ' ').title()


def extract_h1(body: str, filename: str) -> str:
    m = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return f"{slug_to_title(Path(filename).stem)} Workflow"


def extract_description(body: str) -> str:
    """Extrahiert ersten sinnvollen Absatz nach einer Ueberschrift."""
    # Suche: Ueberschrift + Leerzeile + Nicht-Heading-Zeile
    m = re.search(r'^#\s+.*\n\n([^\n#].{20,})(?:\n\n|$)', body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    # Fallback: erster Satz > 40 Zeichen
    sentences = re.split(r'(?<=[.!?])\s+', body.strip())
    for s in sentences:
        s = s.strip()
        if len(s) > 40 and not s.startswith('#') and not s.startswith('```'):
            return s
    return "Standardarbeitsablauf innerhalb der BACH-Infrastruktur."


def has_changelog(body: str) -> bool:
    return bool(re.search(r'^##\s+Changelog', body, re.MULTILINE | re.IGNORECASE))


def has_footer(body: str) -> bool:
    return 'BACH Skill-Architektur v2.0' in body


def strip_trailing_noise(body: str) -> str:
    """Entfernt alte unvollstaendige Fusszeilen/Leerzeilen am Ende."""
    return body.rstrip()


def ensure_body_structure(body: str, filename: str) -> str:
    """Stellt H1, Description, Changelog, Footer sicher."""
    body = strip_trailing_noise(body)

    # H1 sicherstellen
    h1 = extract_h1(body, filename)
    if not re.search(r'^#\s+\S', body, re.MULTILINE):
        body = f"# {h1}\n\n{body}"
    else:
        # Stelle sicher, dass die H1 ganz oben im Body steht
        lines = body.splitlines()
        h1_idx = next((i for i, l in enumerate(lines) if re.match(r'^#\s+\S', l)), None)
        if h1_idx is not None and h1_idx > 0:
            body = '\n'.join([lines[h1_idx]] + lines[:h1_idx] + lines[h1_idx+1:])
        h1 = re.search(r'^#\s+(.+)$', body, re.MULTILINE).group(1).strip()

    # Description-Absatz nach H1 sicherstellen
    desc = extract_description(body)
    m = re.search(r'^(#\s+.*\n)(\n[^\n#].*)', body, re.MULTILINE)
    if not m:
        # Kein Absatz direkt nach H1 -> fuege generierten ein
        body = re.sub(r'^(#\s+.*)$', r'\1\n\n' + desc, body, count=1, flags=re.MULTILINE)

    # Changelog + Footer ergaenzen falls fehlend
    if not has_changelog(body) or not has_footer(body):
        footer_text = FOOTER.format(today=TODAY)
        body = body + '\n' + footer_text

    return body.strip() + '\n'


def fix_file(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    orig_text = text
    fm, body, fm_end = parse_frontmatter(text)

    result = {'file': str(path), 'actions': []}

    if fm is None:
        # Keine Frontmatter: neu erzeugen
        name = path.stem
        h1 = extract_h1(body, path.name)
        desc = extract_description(body)
        fm = {
            'name': name,
            'version': '1.0.0',
            'type': 'workflow',
            'author': 'BACH Team',
            'created': TODAY,
            'updated': TODAY,
            'anthropic_compatible': 'true',
            'description': desc,
        }
        body = ensure_body_structure(body, path.name)
        result['actions'].append('created_frontmatter')
    else:
        # Vorhandene Frontmatter korrigieren/ergaenzen
        name = path.stem
        fm.setdefault('name', name)
        fm.setdefault('version', '1.0.0')
        # Spezieller Fix: webseiten-lesen hat type=protocol
        if path.name == 'webseiten-lesen.md':
            fm['type'] = 'workflow'
            result['actions'].append('fixed_type_to_workflow')
        else:
            fm.setdefault('type', 'workflow')
        fm.setdefault('author', 'BACH Team')
        fm.setdefault('created', TODAY)
        fm.setdefault('updated', TODAY)
        fm.setdefault('anthropic_compatible', 'true')
        if 'description' not in fm:
            desc = extract_description(body)
            fm['description'] = desc
            result['actions'].append('added_description_to_frontmatter')

        # Body-Struktur pruefen/ergaenzen
        new_body = ensure_body_structure(body, path.name)
        if new_body != body:
            result['actions'].append('repaired_body_structure')
        body = new_body

    new_text = fm_to_yaml(fm) + '\n' + body

    if new_text == orig_text:
        result['actions'].append('no_change')
        return result

    # Backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / path.name
    backup_path.write_text(orig_text, encoding='utf-8')

    # Atomar schreiben
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f'.tmp_{path.name}_', suffix='.md')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(new_text)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return result


def main():
    files = sorted(WF_DIR.rglob('*.md'))
    # Das Skript selbst ausschliessen (falls es irrtuemlich .md ist)
    files = [f for f in files if f.name != 'fix_workflows.py']
    print(f"Gefundene Dateien: {len(files)}")
    for f in files:
        if f.name == 'fix_workflows.py':
            continue
        try:
            res = fix_file(f)
            acts = ', '.join(res['actions'])
            print(f"  {f.name}: {acts}")
        except Exception as e:
            print(f"  {f.name}: FEHLER {e}")
    print(f"\nBackups unter: {BACKUP_DIR}")


if __name__ == '__main__':
    main()
