# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Redaction Service — Erkennung und Schwärzung sensibler Daten.

Basiert auf PDFSchwaerzerPro V2.5 (5-Strategy Fuzzy Matching Engine).
Bietet drei Schichten:
  - RedactionDetector: PII-Erkennung in Text (backward-compatible API)
  - FuzzyMatcher: 5-Strategie Fuzzy-Matching-Engine
  - RedactionEngine: PDF-Schwärzung mit PyMuPDF + OCR Safety Check
"""
import difflib
import io
import os
import re
import shutil
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[\s]?[\dA-Z]{4}[\s]?(?:[\dA-Z]{4}[\s]?){2,7}[\dA-Z]{1,4}\b"),
    "phone_de": re.compile(r"\b(?:\+49|0049|0)\s?[\d\s/\-]{6,14}\b"),
    "date_de": re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b"),
    "svnr": re.compile(r"\b\d{2}\s?\d{6}\s?[A-Z]\s?\d{3}\b"),
    "steuerid": re.compile(r"\b\d{11}\b"),
}


class FuzzyMatcher:
    """5-Strategy Fuzzy Matching Engine (aus PDFSchwaerzerPro V2.5)."""

    def __init__(self, sensitive: List[str], whitelist: Optional[List[str]] = None,
                 threshold: float = 0.85):
        self.sensitive = [s for s in sensitive if s and s.strip()]
        self.whitelist = whitelist or []
        self.threshold = threshold
        self._norm_cache: Optional[Tuple] = None

    @staticmethod
    def normalize(word: str) -> str:
        if not word:
            return ""
        w = word
        try:
            import ftfy
            w = ftfy.fix_text(w)
        except (ImportError, Exception):
            pass
        w = unicodedata.normalize("NFKC", w)
        w = re.sub(r"[-_‐‑‒–—,.;:()\[\]\"'\/\\]", " ", w)
        w = re.sub(r"([a-zßäöü])([A-ZÄÖÜ])", r"\1 \2", w)
        w = re.sub(r"\s+", " ", w)
        return w.strip().lower()

    def _build_norm_lists(self) -> Tuple[List[str], Set[str]]:
        if self._norm_cache is not None:
            return self._norm_cache
        norm_sens = [self.normalize(s) for s in self.sensitive]
        norm_sens = [s for s in norm_sens if s]
        norm_white = {self.normalize(w) for w in self.whitelist if w and w.strip()}
        self._norm_cache = (norm_sens, norm_white)
        return self._norm_cache

    def is_sensitive(self, word: str) -> bool:
        if not word:
            return False
        w = self.normalize(word)
        if not w:
            return False

        norm_sens, norm_white = self._build_norm_lists()
        if w in norm_white:
            return False

        # Strategy 1+2: Exact or fuzzy single-term
        for t in norm_sens:
            if t in norm_white:
                continue
            if w == t:
                return True
            if difflib.SequenceMatcher(None, w, t).ratio() >= self.threshold:
                return True

        # Strategy 3: Concatenated pairs
        for i, a in enumerate(norm_sens):
            if a in norm_white:
                continue
            for j, b in enumerate(norm_sens):
                if i == j or b in norm_white:
                    continue
                combo1, combo2 = a + b, b + a
                if w == combo1 or w == combo2:
                    return True
                if combo1 in w or combo2 in w:
                    return True
                if difflib.SequenceMatcher(None, w, combo1).ratio() >= self.threshold:
                    return True

        # Strategy 4: Multi-token ordered matching
        w_tokens = w.split()
        for t in norm_sens:
            if t in norm_white:
                continue
            t_tokens = t.split()
            if len(t_tokens) > 1:
                idx = 0
                ok = True
                for tk in t_tokens:
                    try:
                        idx = w_tokens.index(tk, idx) + 1
                    except ValueError:
                        ok = False
                        break
                if ok:
                    return True

        # Strategy 5: Substring fallback
        for t in norm_sens:
            if t in norm_white:
                continue
            if t and t in w:
                return True

        return False

    def find_all(self, text: str) -> List[str]:
        found = []
        for word in re.split(r"\s+", text):
            word = word.strip()
            if word and self.is_sensitive(word):
                found.append(word)
        return found


class RedactionDetector:
    """PII-Erkennung in Text (backward-compatible mit dem alten Stub)."""

    @staticmethod
    def detect(text: str) -> dict:
        results: Dict[str, list] = {}
        for name, pattern in _PII_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                results[name] = matches
        return results

    @staticmethod
    def redact(text: str) -> str:
        result = text
        for pattern in _PII_PATTERNS.values():
            result = pattern.sub("[REDACTED]", result)
        return result

    @staticmethod
    def detect_with_fuzzy(text: str, sensitive_words: List[str],
                          whitelist: Optional[List[str]] = None) -> dict:
        results = RedactionDetector.detect(text)
        matcher = FuzzyMatcher(sensitive_words, whitelist)
        fuzzy_hits = matcher.find_all(text)
        if fuzzy_hits:
            results["fuzzy"] = fuzzy_hits
        return results


class RedactionEngine:
    """PDF-Schwärzung mit PyMuPDF + optionalem OCR Safety Check."""

    def __init__(self, sensitive_words: List[str],
                 whitelist: Optional[List[str]] = None,
                 threshold: float = 0.85):
        self.sensitive_words = sensitive_words
        self.whitelist = whitelist or []
        self.matcher = FuzzyMatcher(sensitive_words, whitelist, threshold)

    def redact_pdf(self, input_path: str, output_path: str,
                   password: Optional[str] = None) -> dict:
        import fitz
        doc = fitz.open(input_path)
        temp_path = os.path.join(tempfile.gettempdir(), f"redacted_{int(time.time())}.pdf")
        total_pages = len(doc)
        pages_modified = 0
        total_redactions = 0

        for page in doc:
            page_had_hits = False
            for word in self.sensitive_words:
                if self._is_whitelisted(word):
                    continue
                hits = page.search_for(word)
                if hits:
                    page_had_hits = True
                    total_redactions += len(hits)
                    for rect in hits:
                        page.add_redact_annot(rect, fill=(0, 0, 0))
            if page_had_hits:
                pages_modified += 1
            page.apply_redactions()

        doc.save(temp_path)
        doc.close()
        encrypted = self._finalize_pdf(temp_path, output_path, password)
        if os.path.exists(temp_path):
            os.remove(temp_path)

        return {
            "pages_total": total_pages,
            "pages_modified": pages_modified,
            "redactions": total_redactions,
            "encrypted": encrypted,
        }

    def safety_check(self, pdf_path: str, ocr_lang: str = "deu",
                     tesseract_cmd: Optional[str] = None,
                     poppler_path: Optional[str] = None) -> dict:
        import pytesseract
        from pdf2image import convert_from_path
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader

        if tesseract_cmd and os.path.exists(tesseract_cmd):
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        images = convert_from_path(pdf_path, dpi=300, poppler_path=poppler_path)
        cleaned_pdf = str(Path(pdf_path).with_stem(Path(pdf_path).stem + "_final"))
        c = canvas.Canvas(cleaned_pdf)
        dpi = 300
        px_to_pt = 72.0 / dpi
        warnings_found = []

        for img in images:
            ocr_data = pytesseract.image_to_data(
                img, lang=ocr_lang, output_type=pytesseract.Output.DICT
            )
            width_pts = img.width * px_to_pt
            height_pts = img.height * px_to_pt
            c.setPageSize((width_pts, height_pts))

            img_bytes = io.BytesIO()
            img.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            c.drawImage(ImageReader(img_bytes), 0, 0, width=width_pts, height=height_pts)

            c.setFont("Helvetica", 9)
            try:
                c.setFillAlpha(0.0)
            except Exception:
                pass

            for i, raw in enumerate(ocr_data.get("text", [])):
                word = raw.strip()
                if not word:
                    continue
                if self.matcher.is_sensitive(word):
                    warnings_found.append(word)
                    continue
                x_pts = ocr_data["left"][i] * px_to_pt
                y_pts = height_pts - (ocr_data["top"][i] * px_to_pt)
                try:
                    c.drawString(x_pts, y_pts, word)
                except Exception:
                    continue

            try:
                c.setFillAlpha(1.0)
            except Exception:
                pass
            c.showPage()

        c.save()
        os.replace(cleaned_pdf, pdf_path)

        return {
            "warnings": list(set(warnings_found)),
            "clean": len(warnings_found) == 0,
        }

    def _finalize_pdf(self, source_path: str, dest_path: str,
                      password: Optional[str] = None) -> bool:
        if password:
            try:
                import pikepdf
                pdf = pikepdf.open(source_path)
                enc = pikepdf.Encryption(owner=password, user=password, R=6)
                pdf.save(dest_path, encryption=enc)
                pdf.close()
                return True
            except (ImportError, Exception):
                pass
        shutil.copy(source_path, dest_path)
        return False

    def _is_whitelisted(self, word: str) -> bool:
        norm = word.strip().lower()
        return any(norm == w.strip().lower() for w in self.whitelist)
