#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool: c_pdf_ocr_batch
Version: 1.0.0
Author: BACH Team (basiert auf PDFtoPDFocr)

Batch-OCR für gescannte PDFs: Bettet unsichtbare Textschicht ein.

Nutzung:
  python pdf_ocr_batch.py scan.pdf
  python pdf_ocr_batch.py scan.pdf --lang deu+eng
  python pdf_ocr_batch.py ordner/ --recursive
  python pdf_ocr_batch.py scan.pdf -o output.pdf
"""
__version__ = "1.0.0"

import argparse
import io
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional


def ocr_pdf(src_path: Path, output_path: Optional[Path] = None,
            lang: str = "deu+eng", dpi: int = 300) -> dict:
    """Bettet OCR-Textschicht in ein gescanntes PDF ein.

    Nutzt PyMuPDF zum Rendern und pytesseract zum Erkennen.
    Fallback auf pdf2image falls PyMuPDF nicht verfügbar.
    """
    import pytesseract
    from PIL import Image

    dst = output_path or src_path.with_stem(src_path.stem + "_ocr")
    result = {"source": str(src_path), "output": str(dst),
              "pages": 0, "ok": False, "error": None}

    try:
        images = _pdf_to_images(src_path, dpi)
    except Exception as e:
        result["error"] = f"PDF-Rendering fehlgeschlagen: {e}"
        return result

    result["pages"] = len(images)

    try:
        import pikepdf
        out_pdf = pikepdf.Pdf.new()

        for img in images:
            if img.mode != "RGB":
                img = img.convert("RGB")
            pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                img, lang=lang, extension="pdf"
            )
            if not pdf_bytes:
                continue
            try:
                src_pdf = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))
            except Exception:
                tmp_f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                tmp_f.write(pdf_bytes)
                tmp_f.close()
                src_pdf = pikepdf.Pdf.open(tmp_f.name)
                os.unlink(tmp_f.name)
            out_pdf.pages.extend(src_pdf.pages)
            src_pdf.close()

        dst.parent.mkdir(parents=True, exist_ok=True)
        out_pdf.save(str(dst))
        out_pdf.close()
        result["ok"] = True
    except ImportError:
        result["error"] = "pikepdf nicht installiert: pip install pikepdf"
    except Exception as e:
        result["error"] = str(e)

    return result


def _pdf_to_images(src_path: Path, dpi: int) -> list:
    try:
        import fitz
        doc = fitz.open(str(src_path))
        from PIL import Image
        images = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            images.append(img)
        doc.close()
        return images
    except ImportError:
        pass

    from pdf2image import convert_from_path
    return convert_from_path(str(src_path), dpi=dpi)


def ocr_batch(paths: List[Path], output_dir: Optional[Path] = None,
              lang: str = "deu+eng", dpi: int = 300) -> dict:
    summary = {"total": len(paths), "ok": 0, "fail": 0, "results": []}
    for p in paths:
        out = (output_dir / (p.stem + "_ocr.pdf")) if output_dir else None
        r = ocr_pdf(p, out, lang, dpi)
        if r["ok"]:
            summary["ok"] += 1
        else:
            summary["fail"] += 1
        summary["results"].append(r)
    return summary


def iter_pdf_files(path: Path, recursive: bool = False):
    if path.is_file() and path.suffix.lower() == ".pdf":
        yield path
    elif path.is_dir():
        pattern = "**/*.pdf" if recursive else "*.pdf"
        for p in sorted(path.glob(pattern)):
            if p.is_file():
                yield p


def main():
    parser = argparse.ArgumentParser(
        description="Batch-OCR: Textschicht in gescannte PDFs einbetten"
    )
    parser.add_argument("input", nargs="+", help="PDF-Dateien oder Ordner")
    parser.add_argument("--lang", "-l", default="deu+eng",
                        help="Tesseract-Sprachen (Standard: deu+eng)")
    parser.add_argument("--output", "-o", help="Ausgabeordner")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="Ordner rekursiv durchsuchen")
    parser.add_argument("--dpi", type=int, default=300,
                        help="Render-DPI (Standard: 300)")
    args = parser.parse_args()

    out_dir = Path(args.output) if args.output else None
    if out_dir and not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for inp in args.input:
        files.extend(iter_pdf_files(Path(inp), args.recursive))

    if not files:
        print("Keine PDF-Dateien gefunden.")
        sys.exit(0)

    print(f"OCR für {len(files)} PDF(s), Sprache: {args.lang}, DPI: {args.dpi}...")
    summary = ocr_batch(files, out_dir, args.lang, args.dpi)
    print(f"Ergebnis: {summary['ok']} erstellt, {summary['fail']} Fehler")

    for r in summary["results"]:
        if r["error"]:
            print(f"  {r['source']}: {r['error']}")
        elif r["ok"]:
            print(f"  {r['source']} → {r['output']} ({r['pages']} Seiten)")


if __name__ == "__main__":
    main()
