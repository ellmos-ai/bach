import re
PHONE_PATTERN = re.compile(
    r'(?<!\w)(?:'
    r'(?:\+49|0049)(?:[ \t]*/[ \t]*|[ \t\-/]{1,3})\d{2,4}(?:(?:[ \t]*/[ \t]*|[ \t\-/]{0,3})\d{2,4}){1,3}|'
    r'0\d{2,4}(?:[ \t]*/[ \t]*|[ \t\-/]{0,3})\d{2,4}(?:(?:[ \t]*/[ \t]*|[ \t\-/]{0,3})\d{2,4}){0,2}'
    r')(?!\w)',
    re.IGNORECASE
)
for p in ['07623 / 555123', '0761 / 2012345', '07623 555123', '0761/2012345']:
    m = PHONE_PATTERN.search('Telefon: ' + p)
    print(repr(p), '->', m.group(0) if m else 'NO MATCH')