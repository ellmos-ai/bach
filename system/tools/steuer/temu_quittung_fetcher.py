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
Tool: temu_quittung_fetcher
Version: 1.0.0
Author: BACH Team
Created: 2026-02-07
Updated: 2026-02-07
Anthropic-Compatible: True

VERSIONS-HINWEIS: Pruefe auf neuere Versionen mit: bach tools version temu_quittung_fetcher
Verwende immer die hoechste Versionsnummer.

Description:
    Extrahiert Bestellnummern aus Temu-Mail-PDFs und ruft die detaillierten
    Quittungen (mit Einzelposten, MwSt, Haendler-Info) automatisiert ab.

    Funktionsweise:
    1. Scannt Mail-PDFs nach Quittungs-Links (_cmsg_biz=1004)
    2. Extrahiert parent_order_sn aus den Hyperlinks
    3. Oeffnet Edge headless mit dem echten User-Profil (Temu-Login)
    4. Ruft jede Quittungsseite ab und speichert als PDF
    5. Benennt nach Belegnummer (B0607_quittung.pdf, B0607_1_quittung.pdf etc.)

    Dateiname-Konvention der Mail-PDFs:
    B{NNNN}_B{NNNN}_Temu_{YYYY-MM-DD}_PO-076-{ORDER}_mail.pdf

Usage:
    python temu_quittung_fetcher.py [--beleg-dir DIR]
    python temu_quittung_fetcher.py --dry-run
    python temu_quittung_fetcher.py --beleg B0650
    python temu_quittung_fetcher.py --visible --wait 8

Arguments:
    --beleg-dir DIR   Ordner mit den Mail-PDFs (Default: Skript-Verzeichnis)
    --dry-run         Nur anzeigen, nicht abrufen
    --beleg BXXXX     Nur bestimmten Beleg abrufen
    --visible         Browser sichtbar starten (Debug)
    --wait N          Wartezeit pro Seite in Sekunden (Default: 4)
    --force           Vorhandene Quittungen erneut abrufen
    --no-kill         Edge NICHT automatisch schliessen

Examples:
    # Im Beleg-Ordner ausfuehren:
    cd .../Temu_neu
    python path/to/temu_quittung_fetcher.py

    # Oder mit explizitem Pfad:
    python temu_quittung_fetcher.py --beleg-dir "C:/Users/.../Temu_neu"

    # Nur einen Beleg testen:
    python temu_quittung_fetcher.py --beleg B0613 --visible

Dependencies:
    - selenium (pip install selenium)
    - PyMuPDF  (pip install PyMuPDF)  -- importiert als fitz
    - Edge Browser mit aktiver Temu-Anmeldung

Receipt-URL-Muster:
    https://www.temu.com/bgt_order_receipt.html
        ?page_from=100
        &_cmsg_locale=76~de~EUR
        &parent_order_sn={BESTELLNUMMER}
        &_cmsg_channel=mail
        &_cmsg_biz=1004

    Die Bestellnummer (parent_order_sn) wird aus den _cmsg_biz=1004
    Hyperlinks in den Mail-PDFs extrahiert. Sie hat das Format:
    PO-076-{13 Ziffern}3666

Exit Codes:
    0 - Erfolg
    1 - Fehler (Edge nicht startbar, nicht eingeloggt, etc.)
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import os
import sys
import subprocess
import time
import json
import base64
import argparse
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import fitz  # PyMuPDF
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

EDGE_USER_DATA = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")
EDGE_PROFILE = "Default"

RECEIPT_BASE_URL = (
    "https://www.temu.com/bgt_order_receipt.html"
    "?page_from=100"
    "&_cmsg_locale=76~de~EUR"
    "&parent_order_sn={order_sn}"
    "&_cmsg_channel=mail"
    "&_cmsg_biz=1004"
)

# ---------------------------------------------------------------------------
# PDF-Extraktion
# ---------------------------------------------------------------------------

def extract_orders_from_pdfs(folder, beleg_filter=None):
    """Extrahiert alle Bestellnummern aus den Mail-PDFs.

    Sucht in jedem PDF nach Hyperlinks mit _cmsg_biz=1004 (Quittungs-Links)
    und extrahiert daraus die parent_order_sn.

    Returns:
        list[dict]: Sortierte Liste mit beleg, order_sn, filename, out_name, receipt_url
    """
    orders = []

    for fname in sorted(os.listdir(folder)):
        if not fname.endswith("_mail.pdf"):
            continue

        beleg = fname.split("_")[0]
        if beleg_filter and beleg != beleg_filter:
            continue

        path = os.path.join(folder, fname)
        doc = fitz.open(path)
        order_sns = set()

        for page in doc:
            for link in page.get_links():
                uri = link.get("uri", "")
                if "_cmsg_biz=1004" in uri and "parent_order_sn=" in uri:
                    parsed = parse_qs(urlparse(uri).query)
                    sn = parsed.get("parent_order_sn", [None])[0]
                    if sn:
                        order_sns.add(sn)

        doc.close()

        sorted_sns = sorted(order_sns)
        multi = len(sorted_sns) > 1

        for idx, sn in enumerate(sorted_sns, 1):
            suffix = f"_{idx}" if multi else ""
            out_name = f"{beleg}{suffix}_quittung.pdf"

            orders.append({
                "beleg": beleg,
                "order_sn": sn,
                "filename": fname,
                "out_name": out_name,
                "receipt_url": RECEIPT_BASE_URL.format(order_sn=sn),
            })

    return orders


# ---------------------------------------------------------------------------
# Edge-Prozess-Management
# ---------------------------------------------------------------------------

def is_edge_running():
    """Prueft ob Edge-Prozesse laufen."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "(Get-Process msedge -ErrorAction SilentlyContinue).Count"],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=10,
        )
        count = int(result.stdout.strip() or "0")
        return count > 0
    except Exception:
        return False


def kill_edge():
    """Beendet alle Edge-Prozesse sauber (erst sanft, dann forciert)."""
    try:
        subprocess.run(
            ["powershell", "-Command",
             "Get-Process msedge -ErrorAction SilentlyContinue | "
             "ForEach-Object { $_.CloseMainWindow() | Out-Null }"],
            capture_output=True, timeout=10,
        )
        time.sleep(2)

        if is_edge_running():
            subprocess.run(
                ["powershell", "-Command",
                 "Stop-Process -Name msedge -Force -ErrorAction SilentlyContinue"],
                capture_output=True, timeout=10,
            )
            time.sleep(1)

        return not is_edge_running()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Browser-Setup
# ---------------------------------------------------------------------------

def create_driver(headless=True):
    """Erstellt Edge WebDriver mit dem echten User-Profil."""
    options = EdgeOptions()
    options.add_argument(f"--user-data-dir={EDGE_USER_DATA}")
    options.add_argument(f"--profile-directory={EDGE_PROFILE}")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-search-engine-choice-screen")
    options.add_argument("--disable-features=msEdgeSidebarV2")

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1200,900")

    return webdriver.Edge(options=options)


def verify_temu_login(driver):
    """Prueft ob Temu-Login aktiv ist."""
    driver.get("https://www.temu.com/your_orders.html")
    time.sleep(3)
    page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    if "anmelden" in page_text[:300] or "registrieren" in page_text[:300]:
        return False
    return True


# ---------------------------------------------------------------------------
# Quittungs-Abruf
# ---------------------------------------------------------------------------

def fetch_receipt_as_pdf(driver, url, output_path, wait_seconds=4):
    """Ruft eine Quittungsseite ab und speichert sie als PDF."""
    driver.get(url)
    time.sleep(wait_seconds)

    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(1)
    except TimeoutException:
        pass

    page_text = driver.find_element(By.TAG_NAME, "body").text[:500]

    lower_text = page_text.lower()
    if "anmelden" in lower_text[:200] and "registrieren" in lower_text[:200]:
        return {"status": "error", "reason": "not_logged_in"}

    pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
        "printBackground": True,
        "preferCSSPageSize": True,
        "paperWidth": 8.27,
        "paperHeight": 11.69,
        "marginTop": 0.4,
        "marginBottom": 0.4,
        "marginLeft": 0.4,
        "marginRight": 0.4,
    })

    with open(output_path, "wb") as f:
        f.write(base64.b64decode(pdf_data["data"]))

    file_size = os.path.getsize(output_path)
    return {"status": "ok", "size": file_size, "page_text_preview": page_text[:200]}


# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Temu Quittungs-Fetcher - Holt detaillierte Quittungen aus Temu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s --beleg-dir "C:/Users/.../Temu_neu"
  %(prog)s --dry-run
  %(prog)s --beleg B0613 --visible
        """,
    )
    parser.add_argument("--beleg-dir", type=str, default=None,
                        help="Ordner mit Mail-PDFs (Default: Skript-Verzeichnis)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Nur anzeigen, nicht abrufen")
    parser.add_argument("--beleg", type=str, default=None,
                        help="Nur bestimmten Beleg abrufen (z.B. B0650)")
    parser.add_argument("--visible", action="store_true",
                        help="Browser sichtbar starten (Debug)")
    parser.add_argument("--wait", type=int, default=4,
                        help="Wartezeit pro Seite in Sekunden (Default: 4)")
    parser.add_argument("--force", action="store_true",
                        help="Vorhandene Quittungen erneut abrufen")
    parser.add_argument("--no-kill", action="store_true",
                        help="Edge NICHT automatisch schliessen")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    beleg_dir = args.beleg_dir or os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(beleg_dir, "Quittungen")
    log_file = os.path.join(output_dir, "fetch_log.json")

    print("=" * 60)
    print("  Temu Quittungs-Fetcher v" + __version__)
    print("=" * 60)

    # 1. Orders extrahieren
    print(f"\n[1/4] Extrahiere Bestellnummern aus PDFs...")
    print(f"  Ordner: {beleg_dir}")
    orders = extract_orders_from_pdfs(beleg_dir, beleg_filter=args.beleg)

    if not orders:
        print("  Keine Bestellungen gefunden!")
        return 0

    belege = set(o["beleg"] for o in orders)
    print(f"  -> {len(orders)} Bestellungen aus {len(belege)} Belegen")

    os.makedirs(output_dir, exist_ok=True)

    if not args.force:
        todo = [o for o in orders
                if not os.path.exists(os.path.join(output_dir, o["out_name"]))]
        skipped = len(orders) - len(todo)
        if skipped:
            print(f"  -> {skipped} bereits vorhanden (uebersprungen)")
        orders = todo

    if not orders:
        print("\n  Alle Quittungen bereits vorhanden! (--force zum Neuabruf)")
        return 0

    if args.dry_run:
        print(f"\n[DRY-RUN] Wuerde {len(orders)} Quittungen abrufen:")
        for o in orders:
            print(f"  {o['out_name']:30s} <- {o['order_sn']}")
        return 0

    # 2. Edge schliessen
    print(f"\n[2/4] Edge-Profil vorbereiten...")
    if is_edge_running():
        if args.no_kill:
            print("  [FEHLER] Edge laeuft noch! Bitte schliessen oder --no-kill entfernen.")
            return 1
        print("  Edge laeuft -> wird kurz geschlossen...")
        if not kill_edge():
            print("  [FEHLER] Edge konnte nicht beendet werden!")
            return 1
        print("  -> Edge geschlossen")
    else:
        print("  -> Edge ist nicht aktiv")

    # 3. Browser starten
    mode_str = "(sichtbar)" if args.visible else "(headless)"
    print(f"\n[3/4] Starte Edge {mode_str} mit deinem Profil...")

    try:
        driver = create_driver(headless=not args.visible)
    except WebDriverException as e:
        print(f"\n[FEHLER] Edge konnte nicht gestartet werden:\n  {e}")
        return 1

    print("  -> Pruefe Temu-Login...")
    if not verify_temu_login(driver):
        print("\n  [!] Nicht bei Temu eingeloggt!")
        print("      Bitte in Edge bei temu.com einloggen und erneut starten.")
        driver.quit()
        return 1
    print("  -> Login OK!")

    # 4. Quittungen abrufen
    print(f"\n[4/4] Rufe {len(orders)} Quittungen ab...\n")

    log = {
        "timestamp": datetime.now().isoformat(),
        "tool": "temu_quittung_fetcher",
        "version": __version__,
        "beleg_dir": beleg_dir,
        "total": len(orders),
        "success": 0,
        "errors": 0,
        "results": [],
    }

    try:
        for i, order in enumerate(orders, 1):
            out_name = order["out_name"]
            out_path = os.path.join(output_dir, out_name)
            url = order["receipt_url"]

            print(f"  [{i:3d}/{len(orders)}] {out_name:30s} ...", end=" ", flush=True)

            try:
                result = fetch_receipt_as_pdf(driver, url, out_path, args.wait)

                if result["status"] == "ok":
                    size_kb = result["size"] / 1024
                    print(f"OK ({size_kb:.0f} KB)")
                    log["success"] += 1
                else:
                    reason = result.get("reason", "unbekannt")
                    print(f"FEHLER: {reason}")
                    log["errors"] += 1
                    if reason == "not_logged_in":
                        print("\n  [!] Session abgelaufen!")
                        break

                result["out_name"] = out_name
                result["order_sn"] = order["order_sn"]
                log["results"].append(result)

            except Exception as e:
                print(f"FEHLER: {e}")
                log["errors"] += 1
                log["results"].append({
                    "out_name": out_name,
                    "order_sn": order["order_sn"],
                    "status": "exception",
                    "error": str(e),
                })

            if i < len(orders):
                time.sleep(1)

    finally:
        driver.quit()

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"  Ergebnis: {log['success']} OK, {log['errors']} Fehler")
    print(f"  Gespeichert in: {output_dir}")
    print(f"  Log: {log_file}")
    print(f"{'=' * 60}")
    print(f"\n  Edge kann jetzt wieder normal gestartet werden.")

    return 0 if log["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
