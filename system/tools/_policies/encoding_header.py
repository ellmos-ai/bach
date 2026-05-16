#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
POLICY: encoding_header
VERSION: 1.0
SIZE: small (inline injection)
DESCRIPTION: UTF-8 Encoding Header und Windows Console Fix

Injiziert:
  - Shebang
  - UTF-8 Coding Declaration
  - Windows Console Encoding Fix
"""

# === POLICY:encoding_header:1.0 ===
# (Dieser Code wird am Dateianfang injiziert, nicht als Block)

SHEBANG = "#!/usr/bin/env python3"
ENCODING = "# -*- coding: utf-8 -*-"

CONSOLE_FIX = '''
# Windows Console Encoding Fix
import sys
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass
'''
# === END:encoding_header ===
