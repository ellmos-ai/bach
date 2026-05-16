#!/usr/bin/env python3
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

"""
Tool: c_md_to_pdf
Version: 2.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-14
Anthropic-Compatible: True

VERSIONS-HINWEIS: Pruefe auf neuere Versionen mit: bach tools version c_md_to_pdf

Description:
    Markdown zu PDF Converter fuer das BACH-System.
    Primaer: MD -> HTML -> PDF via Edge Headless (beste Qualitaet).
    Fallback: MD -> PDF via ReportLab (wenn Edge nicht verfuegbar).

    Unterstuetzt: Headers, Listen (verschachtelt), Tabellen, Code-Bloecke,
    Bold/Italic, Checkboxen, Blockzitate, Links, Sonderzeichen/Umlaute.

Usage:
    python c_md_to_pdf.py report.md
    python c_md_to_pdf.py report.md -o output.pdf
    python c_md_to_pdf.py report.md --no-page-numbers --no-footer
    python c_md_to_pdf.py report.md --engine reportlab
    python c_md_to_pdf.py  # Alle .md im Workspace
"""

__version__ = "2.0.0"
__author__ = "BACH Team"

import os
import re
import subprocess
import sys
import tempfile
import argparse
from datetime import datetime
from pathlib import Path

# === Pfade ===
BASE = Path(__file__).resolve().parent.parent.parent.parent  # converters/ -> tools/ -> system/ -> BACH_ROOT
WORKSPACE = BASE / "workspace"
MESSAGEBOX_INBOX = BASE / "user" / "MessageBox" / "inbox"
STORAGE_REPORTS = BASE / "system" / "storage" / "reports"

EDGE_PATHS_WIN = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

EDGE_PATHS_MAC = [
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
]

EDGE_PATHS_LINUX = [
    Path("/usr/bin/microsoft-edge"),
    Path("/usr/bin/microsoft-edge-stable"),
]


# ============================================================
# EDGE DETECTION
# ============================================================

def find_edge() -> str:
    """Findet Edge-Binary. Gibt Pfad oder None zurueck."""
    if sys.platform == "win32":
        candidates = EDGE_PATHS_WIN
    elif sys.platform == "darwin":
        candidates = EDGE_PATHS_MAC
    else:
        candidates = EDGE_PATHS_LINUX
    for p in candidates:
        if p.exists():
            return str(p)
    import shutil
    found = shutil.which("msedge") or shutil.which("microsoft-edge")
    return found


# ============================================================
# ENGINE 1: HTML + EDGE HEADLESS (Primary)
# ============================================================

class MarkdownToHTML:
    """Konvertiert Markdown zu HTML mit vollem Feature-Support."""

    def __init__(self, show_header=True, show_footer=True,
                 show_date=True, show_page_numbers=True,
                 source_path=""):
        self.show_header = show_header
        self.show_footer = show_footer
        self.show_date = show_date
        self.show_page_numbers = show_page_numbers
        self.source_path = source_path

    def convert(self, markdown: str, title: str = "Dokument") -> str:
        """Konvertiert Markdown-String zu komplettem HTML-Dokument."""
        body = self._parse(markdown)
        return self._wrap_html(body, title)

    # ---------- INLINE FORMATTING ----------

    @staticmethod
    def _inline(text: str) -> str:
        """Inline-Formatierung: Code, Bold, Italic, Images, Links, Checkboxen."""
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
        # Badge images [![alt](img)](url) - before standalone images and links
        text = re.sub(r'\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)',
                       r'<a href="\3"><img src="\2" alt="\1"></a>', text)
        # Standalone images ![alt](url) - before links
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1">', text)
        # Links
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
        text = text.replace('- [x]', '&#9745;').replace('- [X]', '&#9745;')
        text = text.replace('- [ ]', '&#9744;')
        return text

    # ---------- BLOCK PARSING ----------

    def _parse(self, markdown: str) -> str:
        lines = markdown.split('\n')
        parts = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i].rstrip()

            # Code-Block
            if line.lstrip().startswith('```'):
                lang = line.strip()[3:].strip()
                code_lines = []
                i += 1
                while i < n and not lines[i].rstrip().lstrip().startswith('```'):
                    code_lines.append(
                        lines[i].rstrip()
                        .replace('&', '&amp;')
                        .replace('<', '&lt;')
                        .replace('>', '&gt;')
                    )
                    i += 1
                i += 1  # Skip closing ```
                parts.append(
                    f'<pre><code class="language-{lang}">'
                    + '\n'.join(code_lines)
                    + '</code></pre>'
                )
                continue

            # Tabelle
            if '|' in line and line.strip().startswith('|') and line.strip().endswith('|'):
                table_lines = []
                while i < n and '|' in lines[i] and lines[i].strip().startswith('|'):
                    table_lines.append(lines[i].strip())
                    i += 1
                parts.append(self._parse_table(table_lines))
                continue

            # Blockzitat
            if line.startswith('>'):
                bq_lines = []
                while i < n and lines[i].rstrip().startswith('>'):
                    bq_lines.append(self._inline(lines[i].rstrip().lstrip('>').strip()))
                    i += 1
                parts.append(
                    '<blockquote><p>' + '<br>'.join(bq_lines) + '</p></blockquote>'
                )
                continue

            # Leerzeile
            if line.strip() == '':
                i += 1
                continue

            # Horizontale Linie
            if re.match(r'^(-{3,}|={3,}|\*{3,})$', line.strip()):
                parts.append('<hr>')
                i += 1
                continue

            # Headers
            m = re.match(r'^(#{1,6})\s+(.+)$', line)
            if m:
                lvl = len(m.group(1))
                parts.append(f'<h{lvl}>{self._inline(m.group(2))}</h{lvl}>')
                i += 1
                continue

            # Listen (geordnet und ungeordnet)
            lm = re.match(r'^(\s*)([-*]|\d+\.)\s+(.+)$', line)
            if lm:
                list_items, i = self._parse_list(lines, i)
                parts.append(list_items)
                continue

            # Normaler Absatz
            parts.append(f'<p>{self._inline(line)}</p>')
            i += 1

        return '\n'.join(parts)

    def _parse_table(self, table_lines: list) -> str:
        """Parst Markdown-Tabelle zu HTML."""
        if len(table_lines) < 2:
            return '<p>' + self._inline(table_lines[0]) + '</p>'

        rows = []
        for tl in table_lines:
            cells = [c.strip() for c in tl.strip('|').split('|')]
            rows.append(cells)

        html = '<table>\n<thead>\n<tr>'
        for cell in rows[0]:
            html += f'<th>{self._inline(cell)}</th>'
        html += '</tr>\n</thead>\n<tbody>\n'

        for row in rows[2:]:
            html += '<tr>'
            for cell in row:
                html += f'<td>{self._inline(cell)}</td>'
            html += '</tr>\n'

        html += '</tbody>\n</table>'
        return html

    def _parse_list(self, lines: list, start: int) -> tuple:
        """Parst verschachtelte Listen. Gibt (html, next_index) zurueck."""
        n = len(lines)
        result = []
        stack = []  # (indent_level, tag)
        i = start

        while i < n:
            line = lines[i].rstrip()
            m = re.match(r'^(\s*)([-*]|\d+\.)\s+(.+)$', line)
            if not m:
                break

            indent = len(m.group(1))
            marker = m.group(2)
            content = self._inline(m.group(3))
            tag = 'ol' if marker[0].isdigit() else 'ul'
            depth = indent // 2

            # Stack anpassen: schliessen was zu tief ist
            while len(stack) > depth + 1:
                old_tag = stack.pop()
                result.append(f'</{old_tag}>')

            # Neue Ebene oeffnen wenn noetig
            while len(stack) <= depth:
                result.append(f'<{tag}>')
                stack.append(tag)

            result.append(f'<li>{content}</li>')
            i += 1

        # Alle offenen Tags schliessen
        while stack:
            result.append(f'</{stack.pop()}>')

        return '\n'.join(result), i

    # ---------- HTML DOCUMENT ----------

    def _wrap_html(self, body: str, title: str) -> str:
        now = datetime.now()
        date_str = now.strftime('%d.%m.%Y %H:%M')

        # Bedingte Elemente
        header_html = ""
        if self.show_header:
            header_html = f'<div class="doc-header">{title}</div>'

        footer_parts = []
        if self.show_date:
            footer_parts.append(f'Erstellt: {date_str}')
        if self.source_path:
            footer_parts.append(str(self.source_path))
        footer_parts.append('BACH System')
        footer_text = ' | '.join(footer_parts)

        footer_html = ""
        if self.show_footer:
            footer_html = f'<div class="doc-footer">{footer_text}</div>'

        # CSS fuer Page-Numbers
        page_number_css = ""
        if self.show_page_numbers:
            page_number_css = """
            @page {
                @bottom-right {
                    content: "Seite " counter(page);
                    font-size: 8pt;
                    color: #95a5a6;
                }
            }"""

        return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        @page {{
            margin: 2cm 2.5cm 2.5cm 2.5cm;
            size: A4;
            {page_number_css}
        }}
        body {{
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            line-height: 1.7;
            color: #2c3e50;
            margin: 0;
            padding: 0;
            font-size: 11pt;
        }}
        .doc-header {{
            text-align: center;
            font-size: 8pt;
            color: #95a5a6;
            border-bottom: 1px solid #e0e0e0;
            padding-bottom: 6px;
            margin-bottom: 20px;
        }}
        .doc-footer {{
            margin-top: 40px;
            padding-top: 12px;
            border-top: 1px solid #e0e0e0;
            font-size: 8pt;
            color: #95a5a6;
            text-align: right;
        }}
        h1 {{
            color: #1a252f;
            border-bottom: 3px solid #3498db;
            padding-bottom: 12px;
            margin-top: 0;
            font-size: 22pt;
        }}
        h2 {{
            color: #2c3e50;
            border-bottom: 1px solid #bdc3c7;
            padding-bottom: 6px;
            margin-top: 28px;
            font-size: 16pt;
        }}
        h3 {{
            color: #34495e;
            margin-top: 22px;
            font-size: 13pt;
        }}
        h4 {{
            color: #7f8c8d;
            margin-top: 18px;
            font-size: 11pt;
            font-style: italic;
        }}
        p {{
            margin: 8px 0;
        }}
        code {{
            background: #f0f3f5;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
            font-size: 0.9em;
            color: #c0392b;
        }}
        pre {{
            background: #1e1e2e;
            color: #cdd6f4;
            padding: 16px 20px;
            border-radius: 8px;
            overflow-x: auto;
            font-size: 9.5pt;
            line-height: 1.5;
            margin: 14px 0;
        }}
        pre code {{
            background: none;
            color: inherit;
            padding: 0;
            font-size: inherit;
        }}
        blockquote {{
            border-left: 4px solid #3498db;
            margin: 16px 0;
            padding: 10px 20px;
            background: #f8f9fa;
            color: #555;
            border-radius: 0 6px 6px 0;
        }}
        blockquote p {{
            margin: 4px 0;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 16px 0;
            font-size: 10pt;
        }}
        th {{
            background: #2c3e50;
            color: white;
            padding: 10px 14px;
            text-align: left;
            font-weight: 600;
        }}
        td {{
            border: 1px solid #ddd;
            padding: 8px 14px;
        }}
        tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        ul, ol {{
            margin: 6px 0;
            padding-left: 24px;
        }}
        li {{
            margin: 4px 0;
        }}
        ul ul, ol ol, ul ol, ol ul {{
            margin: 2px 0;
        }}
        a {{
            color: #2980b9;
            text-decoration: none;
        }}
        hr {{
            border: none;
            border-top: 1px solid #e0e0e0;
            margin: 24px 0;
        }}
    </style>
</head>
<body>
{header_html}
{body}
{footer_html}
</body>
</html>"""


def convert_html_to_pdf_edge(html_content: str, output_pdf: Path, edge_path: str) -> bool:
    """Konvertiert HTML-String zu PDF via Edge Headless."""
    # Temporaere HTML-Datei
    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.html', delete=False, encoding='utf-8'
    )
    try:
        tmp.write(html_content)
        tmp.close()
        tmp_path = Path(tmp.name)

        output_pdf.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            edge_path,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            f"--print-to-pdf={output_pdf}",
            "--print-to-pdf-no-header",
            tmp_path.as_uri()
        ]

        creation_flags = 0x08000000 if sys.platform == "win32" else 0
        result = subprocess.run(
            cmd, capture_output=True, timeout=30,
            creationflags=creation_flags
        )
        return output_pdf.exists() and output_pdf.stat().st_size > 0
    except Exception as e:
        print(f"  [EDGE ERROR] {e}")
        return False
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass


# ============================================================
# ENGINE 2: REPORTLAB (Fallback)
# ============================================================

def _reportlab_available() -> bool:
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


class MarkdownToPDFReportLab:
    """Fallback: Konvertiert Markdown zu PDF via ReportLab."""

    def __init__(self, show_header=True, show_footer=True,
                 show_date=True, show_page_numbers=True,
                 source_path=""):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        )

        self.colors = colors
        self.A4 = A4
        self.cm = cm
        self.TA_CENTER = TA_CENTER
        self.TA_RIGHT = TA_RIGHT
        self.SimpleDocTemplate = SimpleDocTemplate
        self.Paragraph = Paragraph
        self.Spacer = Spacer
        self.Table = Table
        self.TableStyle = TableStyle

        self.show_header = show_header
        self.show_footer = show_footer
        self.show_date = show_date
        self.show_page_numbers = show_page_numbers
        self.source_path = source_path

        self.styles = self._create_styles(getSampleStyleSheet, ParagraphStyle,
                                          colors, TA_CENTER, TA_RIGHT, TA_LEFT)

    def _create_styles(self, getSampleStyleSheet, ParagraphStyle,
                       colors, TA_CENTER, TA_RIGHT, TA_LEFT):
        styles = getSampleStyleSheet()

        styles.add(ParagraphStyle(
            name='DocTitle', parent=styles['Heading1'],
            fontSize=22, textColor=colors.HexColor('#1a252f'),
            spaceAfter=20, alignment=TA_CENTER
        ))
        styles.add(ParagraphStyle(
            name='Metadata', parent=styles['Normal'],
            fontSize=8, textColor=colors.grey,
            alignment=TA_RIGHT, spaceAfter=20
        ))
        styles.add(ParagraphStyle(
            name='CodeBlock', parent=styles['Normal'],
            fontName='Courier', fontSize=8.5,
            textColor=colors.HexColor('#cdd6f4'),
            backColor=colors.HexColor('#1e1e2e'),
            borderPadding=8, leftIndent=10, rightIndent=10,
            spaceAfter=6, spaceBefore=6
        ))
        styles.add(ParagraphStyle(
            name='BlockQuote', parent=styles['Normal'],
            leftIndent=30, textColor=colors.HexColor('#555555'),
            borderColor=colors.HexColor('#3498db'),
            borderWidth=2, borderPadding=8,
            spaceAfter=10, spaceBefore=10
        ))

        # Listen-Styles fuer verschiedene Tiefen
        for depth in range(4):
            name = f'ListItem{depth}'
            if name not in [s.name for s in styles.byName.values()]:
                bullet = ['&#x2022;', '&#x25E6;', '&#x25AA;', '&#x25AB;'][depth]
                styles.add(ParagraphStyle(
                    name=name, parent=styles['Normal'],
                    leftIndent=20 + depth * 20,
                    bulletIndent=8 + depth * 20,
                    spaceBefore=2, spaceAfter=2
                ))

        return styles

    @staticmethod
    def _inline_format(text: str) -> str:
        """Inline-Markdown zu ReportLab XML."""
        text = re.sub(r'`([^`]+)`', r'<font face="Courier" color="#c0392b">\1</font>', text)
        # Bold+Italic (***text***) zuerst
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
        # Bold (**text**) - greedy innerhalb, um verschachtelte * mitzunehmen
        text = re.sub(r'\*\*(.+?)\*\*', lambda m: '<b>' + m.group(1).replace('*', '') + '</b>', text)
        # Italic (*text*) - nur wenn keine ** drumherum
        text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<i>\1</i>', text)
        # Badge images [![alt](img)](url) - before standalone images and links
        text = re.sub(r'\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)',
                       r'<a href="\3" color="#2980b9">[Bild: \1]</a>', text)
        # Standalone images ![alt](url) - before links (ReportLab kann keine <img>)
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'[Bild: \1]', text)
        # Links
        text = re.sub(r'\[(.+?)\]\((.+?)\)',
                       r'<a href="\2" color="#2980b9">\1</a>', text)
        text = text.replace('- [x]', '&#9745;').replace('- [X]', '&#9745;')
        text = text.replace('- [ ]', '&#9744;')
        return text

    def convert(self, md_file: Path, output_file: Path):
        """Konvertiert MD-Datei zu PDF via ReportLab."""
        md_content = md_file.read_text(encoding='utf-8')
        lines = md_content.split('\n')

        doc = self.SimpleDocTemplate(
            str(output_file), pagesize=self.A4,
            leftMargin=2 * self.cm, rightMargin=2 * self.cm,
            topMargin=2.5 * self.cm, bottomMargin=2.5 * self.cm,
            title=md_file.stem
        )

        story = []

        # Title
        if self.show_header:
            title = md_file.stem.replace('_', ' ').replace('-', ' ')
            story.append(self.Paragraph(title, self.styles['DocTitle']))

        # Metadata
        if self.show_date or self.show_footer:
            parts = []
            if self.show_date:
                parts.append(datetime.now().strftime('%Y-%m-%d %H:%M'))
            if self.source_path:
                parts.append(str(self.source_path))
            parts.append('BACH System')
            story.append(self.Paragraph(' | '.join(parts), self.styles['Metadata']))

        story.append(self.Spacer(1, 10))

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i].rstrip()

            # Code-Block
            if line.strip().startswith('```'):
                code_lines = []
                i += 1
                while i < n and not lines[i].strip().startswith('```'):
                    code_lines.append(
                        lines[i].rstrip()
                        .replace('&', '&amp;')
                        .replace('<', '&lt;')
                        .replace('>', '&gt;')
                    )
                    i += 1
                i += 1
                code_text = '<br/>'.join(code_lines) if code_lines else '&nbsp;'
                story.append(self.Paragraph(code_text, self.styles['CodeBlock']))
                continue

            # Tabelle
            if '|' in line and line.strip().startswith('|') and line.strip().endswith('|'):
                table_data = []
                while i < n and '|' in lines[i] and lines[i].strip().startswith('|'):
                    row = lines[i].strip()
                    cells = [c.strip() for c in row.strip('|').split('|')]
                    # Separator ueberspringen
                    if not all(re.match(r'^[-:]+$', c) for c in cells):
                        table_data.append([
                            self.Paragraph(self._inline_format(c), self.styles['Normal'])
                            for c in cells
                        ])
                    i += 1
                if table_data:
                    tbl = self.Table(table_data, repeatRows=1)
                    tbl.setStyle(self.TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), self.colors.HexColor('#2c3e50')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), self.colors.white),
                        ('FONTSIZE', (0, 0), (-1, 0), 10),
                        ('FONTSIZE', (0, 1), (-1, -1), 9),
                        ('GRID', (0, 0), (-1, -1), 0.5, self.colors.HexColor('#dddddd')),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                         [self.colors.white, self.colors.HexColor('#f8f9fa')]),
                        ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                        ('LEFTPADDING', (0, 0), (-1, -1), 10),
                    ]))
                    story.append(self.Spacer(1, 8))
                    story.append(tbl)
                    story.append(self.Spacer(1, 8))
                continue

            # Blockzitat
            if line.startswith('>'):
                bq_parts = []
                while i < n and lines[i].rstrip().startswith('>'):
                    bq_parts.append(
                        self._inline_format(lines[i].rstrip().lstrip('>').strip())
                    )
                    i += 1
                story.append(self.Paragraph(
                    '<br/>'.join(bq_parts), self.styles['BlockQuote']
                ))
                continue

            # Leerzeile
            if line.strip() == '':
                story.append(self.Spacer(1, 6))
                i += 1
                continue

            # Horizontale Linie
            if re.match(r'^(-{3,}|={3,}|\*{3,})$', line.strip()):
                story.append(self.Spacer(1, 12))
                i += 1
                continue

            # Headers
            m = re.match(r'^(#{1,6})\s+(.+)$', line)
            if m:
                lvl = len(m.group(1))
                style_name = f'Heading{min(lvl, 4)}'
                story.append(self.Paragraph(
                    self._inline_format(m.group(2)), self.styles[style_name]
                ))
                i += 1
                continue

            # Listen
            lm = re.match(r'^(\s*)([-*]|\d+\.)\s+(.+)$', line)
            if lm:
                while i < n:
                    lm2 = re.match(r'^(\s*)([-*]|\d+\.)\s+(.+)$', lines[i].rstrip())
                    if not lm2:
                        break
                    indent = len(lm2.group(1))
                    depth = min(indent // 2, 3)
                    marker = lm2.group(2)
                    content = self._inline_format(lm2.group(3))
                    bullet = ['&#x2022;', '&#x25E6;', '&#x25AA;', '&#x25AB;'][depth]
                    is_ordered = marker[0].isdigit()
                    prefix = f'{marker} ' if is_ordered else f'{bullet} '
                    style = self.styles[f'ListItem{depth}']
                    story.append(self.Paragraph(
                        f'{prefix}{content}', style
                    ))
                    i += 1
                continue

            # Normaler Absatz
            story.append(self.Paragraph(
                self._inline_format(line), self.styles['Normal']
            ))
            i += 1

        # Footer
        if self.show_footer and self.show_page_numbers:
            story.append(self.Spacer(1, 20))
            story.append(self.Paragraph(
                '<font color="#95a5a6" size="7">'
                'Hinweis: Seitenzahlen nur in Edge-Engine verfuegbar'
                '</font>',
                self.styles['Normal']
            ))

        doc.build(story)
        return output_file


# ============================================================
# ORCHESTRATOR
# ============================================================

def convert_file(md_file: Path, output_file: Path = None,
                 engine: str = "auto",
                 show_header=True, show_footer=True,
                 show_date=True, show_page_numbers=True) -> Path:
    """
    Konvertiert eine Markdown-Datei zu PDF.

    Args:
        md_file: Pfad zur .md Datei
        output_file: Pfad fuer Output-PDF (auto = gleicher Name)
        engine: "auto", "edge" oder "reportlab"
        show_header: Title-Header anzeigen
        show_footer: Pfad/BACH-Footer anzeigen
        show_date: Datum/Uhrzeit anzeigen
        show_page_numbers: Seitenzahlen anzeigen

    Returns:
        Path zum erstellten PDF
    """
    md_file = Path(md_file)
    if not md_file.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {md_file}")

    if output_file is None:
        output_file = md_file.with_suffix('.pdf')
    output_file = Path(output_file).resolve()

    md_content = md_file.read_text(encoding='utf-8')

    # Title aus erstem H1 oder Dateiname
    title_match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
    title = title_match.group(1) if title_match else md_file.stem.replace('_', ' ')

    # Engine waehlen
    edge_path = find_edge()
    use_edge = False

    if engine == "edge":
        if not edge_path:
            print("  [WARN] Edge nicht gefunden, erzwungener Edge-Modus fehlgeschlagen")
            print("  [FALLBACK] Nutze ReportLab")
        else:
            use_edge = True
    elif engine == "reportlab":
        use_edge = False
    else:  # auto
        use_edge = edge_path is not None

    if use_edge:
        print(f"  [ENGINE] Edge Headless")
        converter = MarkdownToHTML(
            show_header=show_header, show_footer=show_footer,
            show_date=show_date, show_page_numbers=show_page_numbers,
            source_path=md_file.name
        )
        html = converter.convert(md_content, title)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        if convert_html_to_pdf_edge(html, output_file, edge_path):
            return output_file
        else:
            print(f"  [WARN] Edge-Konvertierung fehlgeschlagen")
            if _reportlab_available():
                print(f"  [FALLBACK] Nutze ReportLab")
                use_edge = False
            else:
                raise RuntimeError("Edge-Konvertierung fehlgeschlagen und ReportLab nicht installiert")

    if not use_edge:
        if not _reportlab_available():
            raise ImportError(
                "Weder Edge noch ReportLab verfuegbar.\n"
                "  Edge: Installiere Microsoft Edge\n"
                "  ReportLab: pip install reportlab"
            )
        print(f"  [ENGINE] ReportLab (Fallback)")
        converter = MarkdownToPDFReportLab(
            show_header=show_header, show_footer=show_footer,
            show_date=show_date, show_page_numbers=show_page_numbers,
            source_path=md_file.name
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        converter.convert(md_file, output_file)
        return output_file


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='BACH Markdown zu PDF Converter v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python c_md_to_pdf.py report.md
  python c_md_to_pdf.py report.md -o output.pdf
  python c_md_to_pdf.py report.md --no-page-numbers --no-footer
  python c_md_to_pdf.py report.md --engine reportlab
  python c_md_to_pdf.py  # Alle .md im Workspace

Engines:
  auto       Edge Headless (primaer) mit ReportLab-Fallback
  edge       Edge Headless erzwingen
  reportlab  ReportLab erzwingen
        """
    )

    parser.add_argument('files', nargs='*',
                        help='Markdown-Dateien (Standard: alle *.md im Workspace)')
    parser.add_argument('-o', '--output',
                        help='Custom Output-Pfad (nur bei einer Datei)')
    parser.add_argument('--engine', choices=['auto', 'edge', 'reportlab'],
                        default='auto', help='Engine waehlen (default: auto)')
    parser.add_argument('--workspace-only', action='store_true',
                        help='Nur in Workspace speichern')
    parser.add_argument('--no-page-numbers', action='store_true',
                        help='Seitenzahlen ausblenden')
    parser.add_argument('--no-date', action='store_true',
                        help='Datum/Uhrzeit ausblenden')
    parser.add_argument('--no-header', action='store_true',
                        help='Title-Header ausblenden')
    parser.add_argument('--no-footer', action='store_true',
                        help='Pfad/BACH-Footer ausblenden')

    args = parser.parse_args()

    # Header
    edge = find_edge()
    engine_info = f"Edge: {'gefunden' if edge else 'NICHT gefunden'}"
    rl_info = f"ReportLab: {'verfuegbar' if _reportlab_available() else 'NICHT installiert'}"

    print("=" * 70)
    print(f"BACH: Markdown -> PDF Converter v{__version__}")
    print(f"  {engine_info} | {rl_info}")
    print(f"  Engine: {args.engine}")
    print("=" * 70)
    print()

    # Files
    if args.files:
        md_files = [Path(f) for f in args.files]
    else:
        md_files = sorted(WORKSPACE.glob("*.md"))

    if not md_files:
        print("[ERROR] Keine Markdown-Dateien gefunden!")
        print(f"   Verzeichnis: {WORKSPACE}")
        return 1

    print(f"[INFO] {len(md_files)} Datei(en) gefunden")
    print()

    # Optionen
    opts = dict(
        engine=args.engine,
        show_header=not args.no_header,
        show_footer=not args.no_footer,
        show_date=not args.no_date,
        show_page_numbers=not args.no_page_numbers,
    )

    # Targets
    if args.output and len(md_files) == 1:
        targets = [(Path(args.output).parent, Path(args.output).name)]
    elif args.workspace_only:
        targets = [(WORKSPACE, None)]
    else:
        targets = [
            (WORKSPACE, None),
            (MESSAGEBOX_INBOX, None),
            (STORAGE_REPORTS, None),
        ]

    total = 0
    for md_file in md_files:
        if not md_file.exists():
            print(f"[SKIP] {md_file} nicht gefunden")
            continue

        print(f"[PROCESS] {md_file.name}")

        for target_dir, custom_name in targets:
            if custom_name:
                out = target_dir / custom_name
            else:
                out = target_dir / (md_file.stem + ".pdf")

            try:
                result = convert_file(md_file, out, **opts)
                size = result.stat().st_size
                print(f"  [OK] {result} ({size:,} bytes)")
                total += 1
            except Exception as e:
                print(f"  [ERROR] {e}")
        print()

    print("=" * 70)
    print(f"[DONE] {total} PDF(s) erstellt")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[ABORT] Abgebrochen!")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
