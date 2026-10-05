#!/usr/bin/env python3
"""Temporäre Analyse der Workflow-Dateien."""
import re
from pathlib import Path

wf_dir = Path('/Users/lukas/services/bach/system/skills/workflows')
files = sorted(wf_dir.rglob('*.md'))

required_fm = ['name', 'version', 'type', 'author', 'created', 'updated', 'anthropic_compatible', 'description']

for f in files:
    text = f.read_text(encoding='utf-8')
    m = re.match(r'^---\s*\n(.*?)\n---\s*', text, re.DOTALL)
    if m:
        fm_text = m.group(1)
        body = text[m.end():]
        fm = {}
        for line in fm_text.splitlines():
            if ':' in line and not line.startswith(' '):
                k, _, v = line.partition(':')
                fm[k.strip()] = v.strip()
        missing = [k for k in required_fm if k not in fm]
        has_h1 = bool(re.search(r'^#\s+\S', body, re.MULTILINE))
        # description paragraph: first non-empty line after H1 that isn't a heading
        has_desc = bool(re.search(r'^(#\s+.*\n\n)([^\n#].*)', body, re.MULTILINE))
        has_changelog = '## Changelog' in body
        has_footer = 'BACH Skill-Architektur v2.0' in body
        only_fm = len(body.strip()) == 0
        status = []
        if missing: status.append(f'missing:{missing}')
        if not has_h1: status.append('no_h1')
        if not has_desc and not only_fm: status.append('no_desc')
        if not has_changelog: status.append('no_changelog')
        if not has_footer: status.append('no_footer')
        if only_fm: status.append('FRONTMATTER_ONLY')
        if status:
            print(f"{f.name}: {', '.join(status)}")
        else:
            print(f"{f.name}: OK")
    else:
        print(f"{f.name}: NO_FRONTMATTER")
print(f"\nTotal: {len(files)}")
