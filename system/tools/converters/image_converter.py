#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool: c_image_converter
Version: 1.0.0
Author: BACH Team (basiert auf pic2pic V1)

Batch-Bildkonvertierung zwischen 9 Formaten.

Nutzung:
  python image_converter.py bild.png --to jpg webp
  python image_converter.py ordner/ --to png --recursive
  python image_converter.py bild.png --to all
"""
__version__ = "1.0.0"

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

FORMATS: Dict[str, dict] = {
    "jpg":  {"pil_format": "JPEG", "ext": ".jpg"},
    "jpeg": {"pil_format": "JPEG", "ext": ".jpeg"},
    "png":  {"pil_format": "PNG",  "ext": ".png"},
    "gif":  {"pil_format": "GIF",  "ext": ".gif"},
    "ico":  {"pil_format": "ICO",  "ext": ".ico"},
    "webp": {"pil_format": "WEBP", "ext": ".webp"},
    "bmp":  {"pil_format": "BMP",  "ext": ".bmp"},
    "tiff": {"pil_format": "TIFF", "ext": ".tiff"},
    "avif": {"pil_format": "AVIF", "ext": ".avif"},
}

ACCEPTED_INPUT_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".ico", ".avif",
}


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ACCEPTED_INPUT_EXTS


def iter_image_files(path: Path, recursive: bool = False):
    if path.is_file():
        if is_image_file(path):
            yield path
    elif path.is_dir():
        if recursive:
            for root, _, files in os.walk(path):
                for name in files:
                    p = Path(root) / name
                    if is_image_file(p):
                        yield p
        else:
            for p in sorted(path.iterdir()):
                if is_image_file(p):
                    yield p


def safe_output_path(folder: Path, base: str, token: str, ext: str) -> Path:
    candidate = folder / f"{base}_{token}{ext}"
    if not candidate.exists():
        return candidate
    i = 2
    while True:
        candidate_i = folder / f"{base}_{token}_{i}{ext}"
        if not candidate_i.exists():
            return candidate_i
        i += 1


def convert_image(src_path: Path, targets: List[str],
                  output_dir: Optional[Path] = None,
                  quality: int = 90) -> dict:
    from PIL import Image, UnidentifiedImageError

    out_dir = output_dir or src_path.parent
    results = {"source": str(src_path), "ok": 0, "fail": 0, "outputs": [], "errors": []}

    try:
        im = Image.open(src_path)
    except (UnidentifiedImageError, OSError) as e:
        results["fail"] = len(targets)
        results["errors"].append(str(e))
        return results

    def has_alpha(img) -> bool:
        if img.mode in ("RGBA", "LA"):
            return True
        return img.mode == "P" and "transparency" in img.info

    for token in targets:
        spec = FORMATS.get(token)
        if not spec:
            results["fail"] += 1
            results["errors"].append(f"Unbekanntes Format: {token}")
            continue

        pil_format = spec["pil_format"]
        ext = spec["ext"]
        img_out = im

        try:
            if pil_format == "GIF" and img_out.mode not in ("P", "L"):
                img_out = img_out.convert("P", palette=Image.ADAPTIVE)
            elif pil_format == "JPEG":
                if has_alpha(img_out):
                    rgb_bg = Image.new("RGB", img_out.size, (255, 255, 255))
                    img_rgba = img_out.convert("RGBA")
                    rgb_bg.paste(img_rgba, mask=img_rgba.split()[3])
                    img_out = rgb_bg
                elif img_out.mode != "RGB":
                    img_out = img_out.convert("RGB")
            elif pil_format == "ICO" and img_out.mode not in ("RGBA", "RGB"):
                img_out = img_out.convert("RGBA" if has_alpha(img_out) else "RGB")
            elif pil_format == "BMP" and has_alpha(img_out):
                img_out = img_out.convert("RGB")

            out_path = safe_output_path(out_dir, src_path.stem, token.lower(), ext)
            save_kwargs = {}
            if pil_format == "JPEG":
                save_kwargs = {"quality": quality, "progressive": True, "optimize": True}
            elif pil_format == "WEBP":
                save_kwargs = {"quality": quality, "method": 6}

            img_out.save(out_path, format=pil_format, **save_kwargs)
            results["ok"] += 1
            results["outputs"].append(str(out_path))
        except Exception as e:
            results["fail"] += 1
            results["errors"].append(f"{token}: {e}")

    try:
        im.close()
    except Exception:
        pass

    return results


def convert_batch(paths: List[Path], targets: List[str],
                  output_dir: Optional[Path] = None,
                  quality: int = 90) -> dict:
    summary = {"total": len(paths), "ok": 0, "fail": 0, "results": []}
    for p in paths:
        r = convert_image(p, targets, output_dir, quality)
        summary["ok"] += r["ok"]
        summary["fail"] += r["fail"]
        summary["results"].append(r)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Batch-Bildkonvertierung (9 Formate)")
    parser.add_argument("input", nargs="+", help="Bilder oder Ordner")
    parser.add_argument("--to", nargs="+", required=True,
                        help=f"Zielformate: {', '.join(FORMATS.keys())} oder 'all'")
    parser.add_argument("--output", "-o", help="Ausgabeordner (Standard: neben Quelldatei)")
    parser.add_argument("--recursive", "-r", action="store_true", help="Ordner rekursiv durchsuchen")
    parser.add_argument("--quality", "-q", type=int, default=90, help="JPEG/WebP Qualität (1-100)")
    args = parser.parse_args()

    targets = list(FORMATS.keys()) if "all" in args.to else args.to
    for t in targets:
        if t not in FORMATS:
            print(f"Unbekanntes Format: {t}. Verfügbar: {', '.join(FORMATS.keys())}")
            sys.exit(1)

    out_dir = Path(args.output) if args.output else None
    if out_dir and not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for inp in args.input:
        p = Path(inp)
        files.extend(iter_image_files(p, args.recursive))

    if not files:
        print("Keine Bilddateien gefunden.")
        sys.exit(0)

    print(f"Konvertiere {len(files)} Bild(er) nach {', '.join(targets)}...")
    summary = convert_batch(files, targets, out_dir, args.quality)
    print(f"Ergebnis: {summary['ok']} erstellt, {summary['fail']} Fehler")

    for r in summary["results"]:
        if r["errors"]:
            print(f"  {r['source']}: {'; '.join(r['errors'])}")


if __name__ == "__main__":
    main()
