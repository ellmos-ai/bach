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
Tool: c_youtube_extractor
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_youtube_extractor

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_youtube_extractor.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# coding: utf-8
"""
c_youtube_extractor.py - Extrahiert YouTube Video-IDs aus URLs

Unterstuetzte Formate:
  - https:/www.youtube.com/watch?v=VIDEO_ID
  - https:/youtu.be/VIDEO_ID
  - https:/www.youtube.com/shorts/VIDEO_ID
  - https:/www.youtube.com/embed/VIDEO_ID
  - Direkte Video-ID (11 Zeichen)

Extrahiert aus: TOOLS/MEDIA/ForYou-Playlist/YouTubePlaylist.py

Usage:
    python c_youtube_extractor.py <url>
    python c_youtube_extractor.py <url1> <url2> <url3>
    python c_youtube_extractor.py --file urls.txt
    python c_youtube_extractor.py --json <url>
    echo "https:/youtu.be/dQw4w9WgXcQ" | python c_youtube_extractor.py --stdin

Autor: Claude (adaptiert)
Abhaengigkeiten: keine (nur stdlib)
"""

import re
import sys
import json
from urllib.parse import urlparse, parse_qs
from pathlib import Path


def extract_youtube_id(url: str) -> str:
    """
    Extrahiert die YouTube-Video-ID aus gaengigen Linkformaten.
    
    Unterstuetzt:
    - https:/www.youtube.com/watch?v=VIDEOID
    - https:/youtu.be/VIDEOID
    - https:/www.youtube.com/shorts/VIDEOID
    - https:/www.youtube.com/embed/VIDEOID
    - Mit zusaetzlichen Parametern (t, list, etc.)
    - Direkte Video-ID (11 Zeichen)
    
    Args:
        url: YouTube-URL oder Video-ID
        
    Returns:
        Video-ID (11 Zeichen) oder leerer String bei Fehler
    """
    if not url:
        return ""
    url = url.strip()

    # Direkte Video-ID?
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url

    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    # youtu.be/<id>
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        vid = parsed.path.lstrip("/")
        vid = vid.split("/")[0]
        # Entferne Query-Parameter die evtl. anhaengen
        vid = vid.split("?")[0]
        return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) else ""

    host = (parsed.hostname or "").lower()

    # youtube.com Varianten
    if host in {"youtube.com", "youtube-nocookie.com"} or host.endswith(".youtube.com") or host.endswith(".youtube-nocookie.com"):
        # watch?v=<id>
        if parsed.path == "/watch":
            q = parse_qs(parsed.query)
            v = q.get("v", [""])[0]
            return v if re.fullmatch(r"[A-Za-z0-9_-]{11}", v) else ""
        
        # shorts/<id>
        if parsed.path.startswith("/shorts/"):
            parts = parsed.path.split("/")
            vid = parts[2] if len(parts) > 2 else ""
            vid = vid.split("?")[0]  # Query-Parameter entfernen
            return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) else ""
        
        # embed/<id>
        if parsed.path.startswith("/embed/"):
            parts = parsed.path.split("/")
            vid = parts[2] if len(parts) > 2 else ""
            vid = vid.split("?")[0]
            return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) else ""
        
        # v/<id> (altes Format)
        if parsed.path.startswith("/v/"):
            parts = parsed.path.split("/")
            vid = parts[2] if len(parts) > 2 else ""
            vid = vid.split("?")[0]
            return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) else ""

    return ""


def get_video_url(video_id: str) -> str:
    """Erstellt Standard-YouTube-URL aus Video-ID."""
    if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return f"https:/www.youtube.com/watch?v={video_id}"
    return ""


def get_thumbnail_url(video_id: str, quality: str = "default") -> str:
    """
    Erstellt Thumbnail-URL fuer ein YouTube-Video.
    
    Args:
        video_id: YouTube Video-ID
        quality: 'default', 'medium', 'high', 'standard', 'maxres'
        
    Returns:
        Thumbnail-URL
    """
    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return ""
    
    quality_map = {
        'default': 'default',      # 120x90
        'medium': 'mqdefault',     # 320x180
        'high': 'hqdefault',       # 480x360
        'standard': 'sddefault',   # 640x480
        'maxres': 'maxresdefault'  # 1280x720
    }
    
    q = quality_map.get(quality, 'default')
    return f"https:/img.youtube.com/vi/{video_id}/{q}.jpg"


def process_urls(urls: list) -> list:
    """Verarbeitet eine Liste von URLs."""
    results = []
    for url in urls:
        url = url.strip()
        if not url or url.startswith('#'):
            continue
        
        video_id = extract_youtube_id(url)
        results.append({
            'input': url,
            'video_id': video_id,
            'valid': bool(video_id),
            'url': get_video_url(video_id) if video_id else None,
            'thumbnail': get_thumbnail_url(video_id, 'high') if video_id else None
        })
    
    return results


def main():
    if len(sys.argv) < 2 and sys.stdin.isatty():
        print(__doc__)
        sys.exit(1)
    
    json_output = '--json' in sys.argv
    from_file = '--file' in sys.argv
    # WICHTIG: Nur bei explizitem --stdin Flag von stdin lesen
    # (nicht bei !isatty, da das in subprocess-Kontexten problematisch ist)
    from_stdin = '--stdin' in sys.argv
    
    # Args bereinigen
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    
    # URLs sammeln
    urls = []
    
    if from_stdin:
        urls = sys.stdin.read().strip().split('\n')
    elif from_file and args:
        filepath = args[0]
        if Path(filepath).exists():
            urls = Path(filepath).read_text(encoding='utf-8').strip().split('\n')
        else:
            print(f"[FEHLER] Datei nicht gefunden: {filepath}")
            sys.exit(1)
    else:
        urls = args
    
    if not urls:
        print("[FEHLER] Keine URLs angegeben")
        sys.exit(1)
    
    # Verarbeiten
    results = process_urls(urls)
    
    if json_output:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            if r['valid']:
                print(f"[OK] {r['video_id']} <- {r['input'][:50]}")
            else:
                print(f"[--] Keine Video-ID gefunden: {r['input'][:50]}")
        
        # Zusammenfassung
        valid_count = sum(1 for r in results if r['valid'])
        print(f"\n{valid_count}/{len(results)} URLs erfolgreich extrahiert")


if __name__ == "__main__":
    main()
