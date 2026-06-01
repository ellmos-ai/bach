#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Text Extractor - Extract text from various document formats
============================================================

Supports: PDF, DOCX, TXT, MD, XLSX, MSG, EML, and more.
Includes OCR fallback for image-based PDFs.
"""

import email
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class ExtractionResult:
    """Result of text extraction."""
    success: bool
    text: str
    word_count: int = 0
    error: str = ""
    method: str = ""  # e.g., "native", "ocr", "conversion"


class TextExtractor:
    """
    Extract text content from various document formats.

    Supports:
    - Plain text: .txt, .md, .rst, .log
    - Documents: .pdf, .docx, .doc, .rtf
    - Data: .json, .xml, .yaml, .csv
    - Spreadsheets: .xlsx, .xls
    - Email: .eml, .msg
    - Code: .py, .js, .java, etc.
    """

    def __init__(self, enable_ocr: bool = True):
        """
        Initialize the extractor.

        Args:
            enable_ocr: Enable OCR for image-based PDFs
        """
        self.enable_ocr = enable_ocr
        self._check_dependencies()

    def _check_dependencies(self) -> dict:
        """Check which optional dependencies are available."""
        self._deps = {
            "docx": False,
            "fitz": False,
            "openpyxl": False,
            "pytesseract": False,
            "extract_msg": False,
        }

        try:
            import docx
            self._deps["docx"] = True
        except ImportError:
            pass

        try:
            import fitz
            self._deps["fitz"] = True
        except ImportError:
            pass

        try:
            import openpyxl
            self._deps["openpyxl"] = True
        except ImportError:
            pass

        try:
            import pytesseract
            from PIL import Image
            self._deps["pytesseract"] = True
        except ImportError:
            pass

        try:
            import extract_msg
            self._deps["extract_msg"] = True
        except ImportError:
            pass

        return self._deps

    def extract(self, filepath: Path) -> ExtractionResult:
        """
        Extract text from a file.

        Args:
            filepath: Path to the file

        Returns:
            ExtractionResult with text content or error
        """
        filepath = Path(filepath)

        if not filepath.exists():
            return ExtractionResult(False, "", error=f"File not found: {filepath}")

        if filepath.is_dir():
            return ExtractionResult(False, "", error="Cannot extract text from directory")

        suffix = filepath.suffix.lower()

        try:
            # Plain text files
            if suffix in {".txt", ".md", ".rst", ".log", ".py", ".js", ".ts",
                         ".java", ".cpp", ".c", ".h", ".json", ".xml", ".yaml",
                         ".yml", ".csv", ".html", ".css"}:
                return self._extract_text_file(filepath)

            # PDF
            elif suffix == ".pdf":
                return self._extract_pdf(filepath)

            # Word documents
            elif suffix == ".docx":
                return self._extract_docx(filepath)

            elif suffix == ".doc":
                return self._extract_doc(filepath)

            # RTF (treat as plain text after stripping control codes)
            elif suffix == ".rtf":
                return self._extract_rtf(filepath)

            # PowerPoint
            elif suffix == ".pptx":
                return self._extract_pptx(filepath)

            # Excel
            elif suffix in {".xlsx", ".xls"}:
                return self._extract_excel(filepath)

            # Email
            elif suffix == ".eml":
                return self._extract_eml(filepath)

            elif suffix == ".msg":
                return self._extract_msg(filepath)

            else:
                return ExtractionResult(
                    False, "",
                    error=f"Unsupported file format: {suffix}"
                )

        except Exception as e:
            return ExtractionResult(False, "", error=str(e))

    def _extract_text_file(self, filepath: Path) -> ExtractionResult:
        """Extract text from plain text files."""
        try:
            text = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = filepath.read_text(encoding="latin-1")
            except Exception as e:
                return ExtractionResult(False, "", error=f"Encoding error: {e}")

        return ExtractionResult(
            success=True,
            text=text,
            word_count=len(text.split()),
            method="native"
        )

    def _extract_pdf(self, filepath: Path) -> ExtractionResult:
        """Extract text from PDF, with OCR fallback."""
        if not self._deps["fitz"]:
            return ExtractionResult(
                False, "",
                error="PyMuPDF (fitz) not installed. Install with: pip install pymupdf"
            )

        import fitz

        try:
            doc = fitz.open(str(filepath))
            text_parts = []
            pages_with_text = 0

            for page in doc:
                page_text = page.get_text().strip()
                if page_text:
                    text_parts.append(page_text)
                    pages_with_text += 1

            doc.close()

            # If no text found, try OCR
            if not text_parts and self.enable_ocr:
                return self._extract_pdf_ocr(filepath)

            text = "\n\n".join(text_parts)
            return ExtractionResult(
                success=True,
                text=text,
                word_count=len(text.split()),
                method="native"
            )

        except Exception as e:
            return ExtractionResult(False, "", error=f"PDF error: {e}")

    def _extract_pdf_ocr(self, filepath: Path) -> ExtractionResult:
        """Extract text from image-based PDF using OCR."""
        if not self._deps["pytesseract"]:
            return ExtractionResult(
                False, "",
                error="OCR not available. Install pytesseract and Tesseract."
            )

        if not self._deps["fitz"]:
            return ExtractionResult(False, "", error="PyMuPDF required for OCR")

        import fitz
        import pytesseract
        from PIL import Image
        import io

        try:
            doc = fitz.open(str(filepath))
            text_parts = []

            for page_num, page in enumerate(doc):
                # Render page to image
                mat = fitz.Matrix(2, 2)  # 2x zoom for better OCR
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")

                # OCR the image
                image = Image.open(io.BytesIO(img_data))
                page_text = pytesseract.image_to_string(image, lang="deu+eng")

                if page_text.strip():
                    text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")

            doc.close()

            if not text_parts:
                return ExtractionResult(False, "", error="OCR found no text")

            text = "\n\n".join(text_parts)
            return ExtractionResult(
                success=True,
                text=text,
                word_count=len(text.split()),
                method="ocr"
            )

        except Exception as e:
            return ExtractionResult(False, "", error=f"OCR error: {e}")

    def _extract_docx(self, filepath: Path) -> ExtractionResult:
        """Extract text from Word document (.docx)."""
        if not self._deps["docx"]:
            return ExtractionResult(
                False, "",
                error="python-docx not installed. Install with: pip install python-docx"
            )

        from docx import Document

        try:
            doc = Document(str(filepath))
            parts = []

            # Paragraphs
            for para in doc.paragraphs:
                if para.text.strip():
                    parts.append(para.text.strip())

            # Tables
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))

            text = "\n\n".join(parts)
            return ExtractionResult(
                success=True,
                text=text,
                word_count=len(text.split()),
                method="native"
            )

        except Exception as e:
            return ExtractionResult(False, "", error=f"DOCX error: {e}")

    def _extract_doc(self, filepath: Path) -> ExtractionResult:
        """Extract text from old Word format (.doc)."""
        import subprocess
        import shutil

        # Try antiword first
        if shutil.which("antiword"):
            try:
                result = subprocess.run(
                    ["antiword", str(filepath)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    text = result.stdout.strip()
                    return ExtractionResult(
                        success=True,
                        text=text,
                        word_count=len(text.split()),
                        method="antiword"
                    )
            except Exception:
                pass

        # Try LibreOffice conversion
        if shutil.which("soffice"):
            try:
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    subprocess.run(
                        ["soffice", "--headless", "--convert-to", "txt:Text",
                         "--outdir", tmpdir, str(filepath)],
                        capture_output=True,
                        timeout=60
                    )
                    txt_file = Path(tmpdir) / (filepath.stem + ".txt")
                    if txt_file.exists():
                        text = txt_file.read_text(encoding="utf-8", errors="replace")
                        return ExtractionResult(
                            success=True,
                            text=text,
                            word_count=len(text.split()),
                            method="libreoffice"
                        )
            except Exception:
                pass

        return ExtractionResult(
            False, "",
            error=".doc extraction requires antiword or LibreOffice"
        )

    def _extract_rtf(self, filepath: Path) -> ExtractionResult:
        """Extract text from RTF files by stripping control codes."""
        try:
            raw = filepath.read_bytes()
            # Simple RTF text extraction: strip control words
            import re
            text = raw.decode("utf-8", errors="replace")
            # Remove RTF header/control groups
            text = re.sub(r'\\[a-z]+\d*\s?', ' ', text)
            text = re.sub(r'[{}]', '', text)
            text = re.sub(r'\s+', ' ', text).strip()

            if not text:
                return ExtractionResult(False, "", error="RTF enthielt keinen extrahierbaren Text")

            return ExtractionResult(
                success=True,
                text=text,
                word_count=len(text.split()),
                method="native"
            )
        except Exception as e:
            return ExtractionResult(False, "", error=f"RTF error: {e}")

    def _extract_pptx(self, filepath: Path) -> ExtractionResult:
        """Extract text from PowerPoint (.pptx) files."""
        try:
            from zipfile import ZipFile
            import xml.etree.ElementTree as ET

            parts = []
            with ZipFile(str(filepath)) as z:
                # pptx slides are in ppt/slides/slide*.xml
                slide_names = sorted([
                    n for n in z.namelist()
                    if n.startswith("ppt/slides/slide") and n.endswith(".xml")
                ])

                ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

                for i, slide_name in enumerate(slide_names, 1):
                    with z.open(slide_name) as f:
                        tree = ET.parse(f)
                    texts = [t.text for t in tree.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t") if t.text]
                    if texts:
                        parts.append(f"--- Slide {i} ---")
                        parts.append("\n".join(texts))

            if not parts:
                return ExtractionResult(False, "", error="Keine Textinhalte in PPTX gefunden")

            text = "\n\n".join(parts)
            return ExtractionResult(
                success=True,
                text=text,
                word_count=len(text.split()),
                method="native"
            )
        except Exception as e:
            return ExtractionResult(False, "", error=f"PPTX error: {e}")

    def _extract_excel(self, filepath: Path) -> ExtractionResult:
        """Extract text from Excel files."""
        if not self._deps["openpyxl"]:
            return ExtractionResult(
                False, "",
                error="openpyxl not installed. Install with: pip install openpyxl"
            )

        import openpyxl

        try:
            wb = openpyxl.load_workbook(str(filepath), data_only=True)
            parts = []

            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                parts.append(f"[Sheet: {sheet_name}]")

                for row in sheet.iter_rows(values_only=True):
                    cells = [str(c) if c else "" for c in row]
                    if any(cells):
                        parts.append(" | ".join(cells))

            wb.close()

            text = "\n".join(parts)
            return ExtractionResult(
                success=True,
                text=text,
                word_count=len(text.split()),
                method="native"
            )

        except Exception as e:
            return ExtractionResult(False, "", error=f"Excel error: {e}")

    def _extract_eml(self, filepath: Path) -> ExtractionResult:
        """Extract text from .eml email files."""
        try:
            with open(filepath, 'rb') as f:
                msg = BytesParser(policy=policy.default).parse(f)

            parts = []

            if msg['Date']:
                parts.append(f"Date: {msg['Date']}")
            if msg['From']:
                parts.append(f"From: {msg['From']}")
            if msg['To']:
                parts.append(f"To: {msg['To']}")
            if msg['Subject']:
                parts.append(f"Subject: {msg['Subject']}")

            parts.append("")

            # Extract body
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        charset = part.get_content_charset() or 'utf-8'
                        try:
                            body = part.get_payload(decode=True).decode(charset)
                            parts.append(body)
                            break
                        except Exception:
                            pass
            else:
                charset = msg.get_content_charset() or 'utf-8'
                try:
                    body = msg.get_payload(decode=True).decode(charset)
                    parts.append(body)
                except Exception:
                    parts.append(str(msg.get_payload()))

            text = "\n".join(parts)
            return ExtractionResult(
                success=True,
                text=text,
                word_count=len(text.split()),
                method="native"
            )

        except Exception as e:
            return ExtractionResult(False, "", error=f"EML error: {e}")

    def _extract_msg(self, filepath: Path) -> ExtractionResult:
        """Extract text from Outlook .msg files."""
        if not self._deps["extract_msg"]:
            return ExtractionResult(
                False, "",
                error="extract-msg not installed. Install with: pip install extract-msg"
            )

        import extract_msg

        try:
            msg = extract_msg.Message(str(filepath))
            parts = []

            if msg.date:
                parts.append(f"Date: {msg.date}")
            if msg.sender:
                parts.append(f"From: {msg.sender}")
            if msg.to:
                parts.append(f"To: {msg.to}")
            if msg.subject:
                parts.append(f"Subject: {msg.subject}")

            parts.append("")

            if msg.body:
                parts.append(msg.body)

            msg.close()

            text = "\n".join(parts)
            return ExtractionResult(
                success=True,
                text=text,
                word_count=len(text.split()),
                method="native"
            )

        except Exception as e:
            return ExtractionResult(False, "", error=f"MSG error: {e}")

    def get_dependencies_status(self) -> dict:
        """Get status of optional dependencies."""
        return {
            "python-docx": {"installed": self._deps["docx"], "for": "DOCX files"},
            "PyMuPDF": {"installed": self._deps["fitz"], "for": "PDF files"},
            "openpyxl": {"installed": self._deps["openpyxl"], "for": "Excel files"},
            "pytesseract": {"installed": self._deps["pytesseract"], "for": "OCR (image PDFs)"},
            "extract-msg": {"installed": self._deps["extract_msg"], "for": "Outlook MSG files"},
        }
