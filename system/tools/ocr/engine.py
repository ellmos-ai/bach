# SPDX-License-Identifier: MIT
"""
BACH OCR Engine
===============

Core logic for extracting text from images and PDFs using Tesseract and PyMuPDF.
Based on tools/ocr_engine.py but refactored into a reusable package.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Union, TYPE_CHECKING
from dataclasses import dataclass
import logging

if TYPE_CHECKING:
    from PIL import Image as _ImageModule

try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import fitz  # PyMuPDF optional (AGPL) -- benoetigt fuer PDF->Image Rendering
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


@dataclass
class OCRResult:
    """Result of an OCR operation."""
    success: bool
    text: str
    confidence: float = 0.0
    language: str = ""
    error: Optional[str] = None


@dataclass
class OCRPageResult:
    """OCR result for a single page."""
    page_num: int
    text: str
    confidence: float
    word_count: int


class OCREngine:
    """
    Universal OCR Engine using Tesseract and PyMuPDF.
    """
    
    DEFAULT_LANGUAGE = "deu+eng"
    
    def __init__(self, tesseract_path: Optional[str] = None):
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        elif sys.platform == "win32":
            resolved = False

            # 1. System install (standard path)
            default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if Path(default_path).exists():
                pytesseract.pytesseract.tesseract_cmd = default_path
                resolved = True

            # 2. ProFiler portable Tesseract (fallback)
            if not resolved:
                # engine.py is at system/tools/ocr/engine.py
                # BACH_ROOT is system/../ -> extensions/ProFiler/tesseract_portable/
                bach_root = Path(__file__).parent.parent.parent.parent
                portable_path = bach_root / "extensions" / "ProFiler" / "tesseract_portable" / "tesseract.exe"
                if portable_path.exists():
                    pytesseract.pytesseract.tesseract_cmd = str(portable_path)
                    resolved = True

            if not resolved:
                logging.warning(
                    "Tesseract not found. Checked: %s and ProFiler portable. "
                    "Install Tesseract or place it in extensions/ProFiler/tesseract_portable/",
                    default_path
                )

        self.available = self._check_tesseract()
        
    def _check_tesseract(self) -> bool:
        if not TESSERACT_AVAILABLE:
            return False
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def extract_text(self, file_path: str, lang: str = DEFAULT_LANGUAGE) -> str:
        """
        High-level helper: Extracts text from file and returns string.
        Returns error message formatted as string on failure, for simple usage.
        """
        if not self.available:
            return "[Error: Tesseract not available]"

        path = Path(file_path)
        if not path.exists():
            return f"[Error: File not found: {file_path}]"

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            results = self.recognize_pdf(str(path), lang)
            return "\n\n".join(r.text for r in results)
        elif suffix in [".jpg", ".jpeg", ".png", ".tiff", ".bmp"]:
            result = self.recognize_image(str(path), lang)
            return result.text if result.success else f"[Error: {result.error}]"
        else:
            return f"[Error: Unsupported format {suffix}]"

    def recognize_image(self, image_path: str, language: str = DEFAULT_LANGUAGE) -> OCRResult:
        """Recognizes text in an image file."""
        if not self.available:
            return OCRResult(False, "", error="Tesseract not available")
        
        try:
            image = Image.open(image_path)
            return self._recognize_pil_image(image, language)
        except Exception as e:
            return OCRResult(False, "", error=str(e))

    def _recognize_pil_image(self, image: Image.Image, language: str) -> OCRResult:
        """Internal: OCR on PIL Image object."""
        try:
            text = pytesseract.image_to_string(image, lang=language)
            
            # Confidence calculation
            data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
            # Filter layout blocks (-1) and calculate average confidence
            confidences = [int(c) for c in data['conf'] if c != -1]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            return OCRResult(
                success=True,
                text=text.strip(),
                confidence=avg_confidence,
                language=language
            )
        except Exception as e:
            return OCRResult(False, "", error=str(e))

    def recognize_pdf(self, pdf_path: str, language: str = DEFAULT_LANGUAGE, pages: Optional[List[int]] = None) -> List[OCRPageResult]:
        """
        Recognizes text in a PDF by rendering pages to images.
        Requires PyMuPDF.
        """
        if not self.available:
            return []
        
        if not PYMUPDF_AVAILABLE:
            # Fallback could be added here, but PyMuPDF is preferred
            return [OCRPageResult(0, "[Error: PyMuPDF not available]", 0.0, 0)]
        
        results = []
        try:
            doc = fitz.open(pdf_path)
            # FitZ pages are 0-indexed, but valid range check uses count
            page_indices = [p-1 for p in pages] if pages else range(doc.page_count)
            
            for page_idx in page_indices:
                if page_idx < 0 or page_idx >= doc.page_count:
                    continue
                
                page = doc[page_idx]
                
                # Render page to image (300 DPI is usually good for OCR)
                # 72 points per inch -> 300/72 scale factor
                zoom = 300 / 72
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to PIL Image
                # PyMuPDF's pix.samples is bytes
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # Perform OCR
                result = self._recognize_pil_image(img, language)
                
                if result.success:
                    results.append(OCRPageResult(
                        page_num=page_idx + 1,
                        text=result.text,
                        confidence=result.confidence,
                        word_count=len(result.text.split())
                    ))
            
            doc.close()
        except Exception as e:
            # Log error or return partial results
            results.append(OCRPageResult(0, f"[Error processing PDF: {e}]", 0.0, 0))
            
        return results

def get_engine() -> OCREngine:
    return OCREngine()
