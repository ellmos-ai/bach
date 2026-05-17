# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

# Wrapper for compare_systems.py to include BachForelle
import sys
import os
from pathlib import Path

# Add current dir to path to import compare_systems
current_dir = Path(__file__).parent
sys.path.append(str(current_dir))

import compare_systems

# Inject BachForelle path
onedrive_root = Path.home() / "OneDrive"
compare_systems.KNOWN_SYSTEMS["BachForelle"] = str(onedrive_root / ".AI" / "BachForelle")
# Ensure BACH path is correct (Vanilla v2)
compare_systems.KNOWN_SYSTEMS["BACH_v2"] = str(onedrive_root / ".AI" / "BACH")

# Run comparison
print("Running comparison for: BACH_v2 vs BachForelle...")
comparison = compare_systems.compare_systems(["BACH_v2", "BachForelle"])
report = compare_systems.generate_markdown_report(comparison)

print(report)

# Save to file
out_path = current_dir / "results" / "COMPARISON_BachForelle.md"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(report, encoding="utf-8")
print(f"\nReport saved to: {out_path}")
