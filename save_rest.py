with open('SKILL_EN.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()
with open('SKILL_EN.md.rest.tmp', 'w', encoding='utf-8') as f:
    f.writelines(lines[215:])
