# Portabilitaet: UNIVERSAL
# Zuletzt validiert: 2026-02-05 (Claude/BACH wiki-author)
# Naechste Pruefung: 2027-02-05
# Quellen: docs.python.org, selenium.dev, schedule.readthedocs.io, pyautogui.readthedocs.io

PYTHON FUER AUTOMATISIERUNG
===========================

Stand: 2026-02-05

UEBERBLICK
==========
  Python ist die ideale Sprache fuer Automatisierungsaufgaben.
  Einfache Syntax, umfangreiche Bibliotheken und Cross-Platform-
  Kompatibilitaet machen Python zur ersten Wahl.

  Typische Anwendungsfaelle:
    - Dateioperationen und Backups
    - Web-Scraping und Browser-Automatisierung
    - System-Administration
    - Datenverarbeitung und Reports
    - GUI-Automatisierung
    - Scheduled Tasks und Cronjobs
    - API-Integration

DATEI-AUTOMATISIERUNG
=====================

DATEIEN ORGANISIEREN
--------------------
  import os
  import shutil
  from pathlib import Path
  from datetime import datetime

  def organisiere_downloads(quell_ordner):
      """Sortiert Dateien nach Typ in Unterordner."""

      kategorien = {
          'Bilder': ['.jpg', '.jpeg', '.png', '.gif', '.bmp'],
          'Dokumente': ['.pdf', '.doc', '.docx', '.txt', '.xlsx'],
          'Videos': ['.mp4', '.avi', '.mkv', '.mov'],
          'Audio': ['.mp3', '.wav', '.flac', '.aac'],
          'Archive': ['.zip', '.rar', '.7z', '.tar']
      }

      quell = Path(quell_ordner)

      for datei in quell.iterdir():
          if datei.is_file():
              suffix = datei.suffix.lower()

              for kategorie, endungen in kategorien.items():
                  if suffix in endungen:
                      ziel_ordner = quell / kategorie
                      ziel_ordner.mkdir(exist_ok=True)
                      shutil.move(str(datei), str(ziel_ordner / datei.name))
                      print(f"Verschoben: {datei.name} -> {kategorie}")
                      break

  # Ausfuehrung
  organisiere_downloads(r"C:\Users\User\Downloads")

AUTOMATISCHES BACKUP
--------------------
  import shutil
  from pathlib import Path
  from datetime import datetime

  def erstelle_backup(quell_ordner, backup_ziel):
      """Erstellt datiertes Backup eines Ordners."""

      timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
      quell = Path(quell_ordner)
      backup_name = f"{quell.name}_backup_{timestamp}"
      backup_pfad = Path(backup_ziel) / backup_name

      try:
          shutil.copytree(quell, backup_pfad)
          print(f"Backup erstellt: {backup_pfad}")
          return backup_pfad
      except Exception as e:
          print(f"Fehler beim Backup: {e}")
          return None

  def bereinige_alte_backups(backup_ordner, behalte_anzahl=5):
      """Loescht alte Backups, behaelt die neuesten."""

      ordner = Path(backup_ordner)
      backups = sorted(ordner.glob("*_backup_*"),
                       key=lambda x: x.stat().st_mtime,
                       reverse=True)

      for altes_backup in backups[behalte_anzahl:]:
          shutil.rmtree(altes_backup)
          print(f"Geloescht: {altes_backup.name}")

DATEI-WATCHER
-------------
  from watchdog.observers import Observer
  from watchdog.events import FileSystemEventHandler
  import time

  class MeinHandler(FileSystemEventHandler):
      def on_created(self, event):
          if not event.is_directory:
              print(f"Neue Datei: {event.src_path}")
              # Hier Aktion ausfuehren

      def on_modified(self, event):
          if not event.is_directory:
              print(f"Geaendert: {event.src_path}")

      def on_deleted(self, event):
          print(f"Geloescht: {event.src_path}")

  def ueberwache_ordner(pfad):
      observer = Observer()
      observer.schedule(MeinHandler(), pfad, recursive=True)
      observer.start()

      try:
          while True:
              time.sleep(1)
      except KeyboardInterrupt:
          observer.stop()
      observer.join()

  # Installation: pip install watchdog

WEB-AUTOMATISIERUNG
===================

SELENIUM - BROWSER-STEUERUNG
----------------------------
  from selenium import webdriver
  from selenium.webdriver.common.by import By
  from selenium.webdriver.common.keys import Keys
  from selenium.webdriver.support.ui import WebDriverWait
  from selenium.webdriver.support import expected_conditions as EC
  import time

  def automatische_websuche(suchbegriff):
      """Oeffnet Browser und fuehrt Google-Suche durch."""

      # Browser starten (Chrome)
      options = webdriver.ChromeOptions()
      # options.add_argument('--headless')  # Ohne GUI
      driver = webdriver.Chrome(options=options)

      try:
          # Seite laden
          driver.get("https://www.google.com")

          # Cookie-Banner akzeptieren (falls vorhanden)
          try:
              accept_btn = WebDriverWait(driver, 5).until(
                  EC.element_to_be_clickable((By.ID, "L2AGLb"))
              )
              accept_btn.click()
          except:
              pass

          # Suchfeld finden und Text eingeben
          suchfeld = WebDriverWait(driver, 10).until(
              EC.presence_of_element_located((By.NAME, "q"))
          )
          suchfeld.send_keys(suchbegriff)
          suchfeld.send_keys(Keys.RETURN)

          # Warten auf Ergebnisse
          time.sleep(2)

          # Ergebnisse extrahieren
          ergebnisse = driver.find_elements(By.CSS_SELECTOR, "h3")
          for i, erg in enumerate(ergebnisse[:5], 1):
              print(f"{i}. {erg.text}")

      finally:
          driver.quit()

  # Installation: pip install selenium
  # Benoetigt: chromedriver im PATH

FORMULAR AUSFUELLEN
-------------------
  def fulle_formular_aus(url, daten):
      """Fuellt Webformular automatisch aus."""

      driver = webdriver.Chrome()

      try:
          driver.get(url)

          for feld_name, wert in daten.items():
              try:
                  element = driver.find_element(By.NAME, feld_name)
                  element.clear()
                  element.send_keys(wert)
              except Exception as e:
                  print(f"Feld '{feld_name}' nicht gefunden: {e}")

          # Submit-Button klicken
          submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
          submit.click()

          time.sleep(2)
          print("Formular abgesendet!")

      finally:
          driver.quit()

  # Verwendung
  daten = {
      "vorname": "Max",
      "nachname": "Mustermann",
      "email": "max@example.com"
  }
  fulle_formular_aus("https://example.com/register", daten)

WEB-SCRAPING MIT BEAUTIFULSOUP
------------------------------
  import requests
  from bs4 import BeautifulSoup

  def scrape_nachrichten(url):
      """Extrahiert Schlagzeilen von einer Nachrichtenseite."""

      headers = {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
      }

      response = requests.get(url, headers=headers)
      response.raise_for_status()

      soup = BeautifulSoup(response.text, 'html.parser')

      # Beispiel: Alle h2-Ueberschriften
      headlines = soup.find_all('h2')

      nachrichten = []
      for h in headlines:
          text = h.get_text(strip=True)
          link = h.find('a')
          href = link.get('href') if link else None
          nachrichten.append({'titel': text, 'link': href})

      return nachrichten

  # Installation: pip install requests beautifulsoup4

ZEITGESTEUERTE AUFGABEN
=======================

SCHEDULE-BIBLIOTHEK
-------------------
  import schedule
  import time

  def taegliches_backup():
      print("Fuehre taegliches Backup durch...")
      erstelle_backup(r"C:\Projekte", r"D:\Backups")

  def stuendlicher_report():
      print("Erstelle stuendlichen Report...")
      # Report-Logik hier

  def wochentags_aufgabe():
      print("Nur an Wochentagen!")

  # Jobs definieren
  schedule.every().day.at("03:00").do(taegliches_backup)
  schedule.every().hour.do(stuendlicher_report)
  schedule.every().monday.at("09:00").do(wochentags_aufgabe)
  schedule.every(10).minutes.do(lambda: print("Alle 10 Minuten"))

  # Scheduler ausfuehren
  while True:
      schedule.run_pending()
      time.sleep(60)

  # Installation: pip install schedule

WINDOWS TASK SCHEDULER
----------------------
  # Skript als .py speichern, dann Task erstellen:
  # 1. Aufgabenplanung oeffnen (taskschd.msc)
  # 2. "Aufgabe erstellen"
  # 3. Trigger: Zeitplan festlegen
  # 4. Aktion: Programm starten
  #    - Programm: python.exe Pfad
  #    - Argumente: Pfad zum Skript

  # Oder per Kommandozeile:
  # schtasks /create /tn "MeinPythonTask" /tr "python C:\tools\mein_script.py" /sc daily /st 09:00

GUI-AUTOMATISIERUNG
===================

PYAUTOGUI - MAUS UND TASTATUR
-----------------------------
  import pyautogui
  import time

  # Sicherheitseinstellung: Maus in Ecke = Abbruch
  pyautogui.FAILSAFE = True
  pyautogui.PAUSE = 0.5  # Pause zwischen Aktionen

  def automatisiere_desktop():
      """Beispiel fuer Desktop-Automatisierung."""

      # Bildschirmgroesse
      breite, hoehe = pyautogui.size()
      print(f"Bildschirm: {breite}x{hoehe}")

      # Mausposition
      x, y = pyautogui.position()
      print(f"Maus bei: {x}, {y}")

      # Maus bewegen
      pyautogui.moveTo(100, 100, duration=0.5)

      # Klicken
      pyautogui.click()           # Linksklick
      pyautogui.rightClick()      # Rechtsklick
      pyautogui.doubleClick()     # Doppelklick

      # Tastatureingabe
      pyautogui.write('Hallo Welt')  # Text tippen
      pyautogui.press('enter')        # Taste druecken
      pyautogui.hotkey('ctrl', 's')   # Tastenkombination

  # Bild auf Bildschirm suchen
  def finde_und_klicke(bild_pfad):
      """Sucht Bild auf Bildschirm und klickt darauf."""

      try:
          position = pyautogui.locateOnScreen(bild_pfad, confidence=0.9)
          if position:
              zentrum = pyautogui.center(position)
              pyautogui.click(zentrum)
              return True
      except Exception as e:
          print(f"Bild nicht gefunden: {e}")
      return False

  # Installation: pip install pyautogui
  # Fuer locateOnScreen: pip install opencv-python

SCREENSHOT-AUTOMATISIERUNG
--------------------------
  import pyautogui
  from PIL import Image
  from datetime import datetime

  def mache_screenshot(bereich=None, dateiname=None):
      """Erstellt Screenshot (Vollbild oder Bereich)."""

      if dateiname is None:
          timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
          dateiname = f"screenshot_{timestamp}.png"

      if bereich:
          # Bereich: (x, y, breite, hoehe)
          screenshot = pyautogui.screenshot(region=bereich)
      else:
          screenshot = pyautogui.screenshot()

      screenshot.save(dateiname)
      print(f"Screenshot gespeichert: {dateiname}")
      return dateiname

E-MAIL-AUTOMATISIERUNG
======================

EMAILS VERSENDEN (SMTP)
-----------------------
  import smtplib
  from email.mime.text import MIMEText
  from email.mime.multipart import MIMEMultipart
  from email.mime.base import MIMEBase
  from email import encoders

  def sende_email(empfaenger, betreff, text, anhang=None):
      """Sendet E-Mail mit optionalem Anhang."""

      # SMTP-Konfiguration (Beispiel: Gmail)
      smtp_server = "smtp.gmail.com"
      smtp_port = 587
      absender = "deine.email@gmail.com"
      passwort = "dein_app_passwort"  # App-Passwort verwenden!

      # E-Mail erstellen
      msg = MIMEMultipart()
      msg['From'] = absender
      msg['To'] = empfaenger
      msg['Subject'] = betreff

      # Text hinzufuegen
      msg.attach(MIMEText(text, 'plain'))

      # Anhang hinzufuegen
      if anhang:
          with open(anhang, 'rb') as f:
              part = MIMEBase('application', 'octet-stream')
              part.set_payload(f.read())
              encoders.encode_base64(part)
              part.add_header('Content-Disposition',
                            f'attachment; filename={anhang}')
              msg.attach(part)

      # Senden
      try:
          server = smtplib.SMTP(smtp_server, smtp_port)
          server.starttls()
          server.login(absender, passwort)
          server.send_message(msg)
          server.quit()
          print(f"E-Mail gesendet an {empfaenger}")
          return True
      except Exception as e:
          print(f"Fehler: {e}")
          return False

AUTOMATISCHE REPORTS
--------------------
  def sende_taeglichen_report():
      """Erstellt und versendet taeglichen Report."""

      from datetime import datetime

      # Report erstellen
      datum = datetime.now().strftime("%d.%m.%Y")

      report = f"""
      Taeglicher Report - {datum}
      ============================

      Zusammenfassung:
      - Verarbeitete Dateien: 150
      - Fehler: 2
      - Erfolgsquote: 98.7%

      Details siehe Anhang.

      Mit freundlichen Gruessen
      Automatisches Reporting-System
      """

      empfaenger = ["team@example.com", "chef@example.com"]

      for email in empfaenger:
          sende_email(email, f"Report {datum}", report)

EXCEL-AUTOMATISIERUNG
=====================

MIT OPENPYXL
------------
  from openpyxl import Workbook, load_workbook
  from openpyxl.styles import Font, Alignment, PatternFill
  from openpyxl.chart import BarChart, Reference

  def erstelle_report_excel(daten, dateiname):
      """Erstellt Excel-Report mit Formatierung."""

      wb = Workbook()
      ws = wb.active
      ws.title = "Report"

      # Header
      header = ["Datum", "Kategorie", "Menge", "Umsatz"]
      for col, text in enumerate(header, 1):
          cell = ws.cell(row=1, column=col, value=text)
          cell.font = Font(bold=True)
          cell.fill = PatternFill("solid", fgColor="366092")
          cell.font = Font(bold=True, color="FFFFFF")

      # Daten einfuegen
      for row_idx, zeile in enumerate(daten, 2):
          for col_idx, wert in enumerate(zeile, 1):
              ws.cell(row=row_idx, column=col_idx, value=wert)

      # Spaltenbreite anpassen
      for col in ws.columns:
          max_length = max(len(str(cell.value or "")) for cell in col)
          ws.column_dimensions[col[0].column_letter].width = max_length + 2

      # Diagramm erstellen
      chart = BarChart()
      chart.title = "Umsatz nach Kategorie"
      daten_ref = Reference(ws, min_col=4, min_row=1, max_row=len(daten)+1)
      kategorien = Reference(ws, min_col=2, min_row=2, max_row=len(daten)+1)
      chart.add_data(daten_ref, titles_from_data=True)
      chart.set_categories(kategorien)
      ws.add_chart(chart, "F2")

      wb.save(dateiname)
      print(f"Excel erstellt: {dateiname}")

  # Installation: pip install openpyxl

MIT PANDAS
----------
  import pandas as pd

  def verarbeite_excel_dateien(ordner):
      """Kombiniert mehrere Excel-Dateien."""

      from pathlib import Path

      alle_daten = []

      for excel_datei in Path(ordner).glob("*.xlsx"):
          df = pd.read_excel(excel_datei)
          df['Quelle'] = excel_datei.name
          alle_daten.append(df)

      if alle_daten:
          gesamt = pd.concat(alle_daten, ignore_index=True)
          gesamt.to_excel("zusammenfassung.xlsx", index=False)
          print(f"Zusammengefuehrt: {len(alle_daten)} Dateien")

  # Installation: pip install pandas openpyxl

BEST PRACTICES
==============

FEHLERBEHANDLUNG
----------------
  import logging

  logging.basicConfig(
      level=logging.INFO,
      format='%(asctime)s - %(levelname)s - %(message)s',
      filename='automatisierung.log'
  )

  def sichere_ausfuehrung(funktion):
      """Decorator fuer Fehlerbehandlung."""
      def wrapper(*args, **kwargs):
          try:
              return funktion(*args, **kwargs)
          except Exception as e:
              logging.error(f"Fehler in {funktion.__name__}: {e}")
              return None
      return wrapper

  @sichere_ausfuehrung
  def kritische_aufgabe():
      # Code hier
      pass

KONFIGURATIONSDATEIEN
---------------------
  import json
  from pathlib import Path

  def lade_config(pfad="config.json"):
      """Laedt Konfiguration aus JSON."""
      config_datei = Path(pfad)
      if config_datei.exists():
          with open(config_datei) as f:
              return json.load(f)
      return {}

  # config.json:
  # {
  #     "backup_ordner": "D:\\Backups",
  #     "email_empfaenger": ["admin@example.com"],
  #     "intervall_minuten": 60
  # }

TROCKENLAUF-MODUS
-----------------
  def datei_operation(datei, aktion, dry_run=False):
      """Fuehrt Operation aus oder zeigt nur an."""

      if dry_run:
          print(f"[DRY RUN] Wuerde {aktion}: {datei}")
      else:
          print(f"[AUSFUEHRUNG] {aktion}: {datei}")
          # Echte Operation hier

NUETZLICHE BIBLIOTHEKEN
=======================
  Dateioperationen:  pathlib, shutil, watchdog
  Web-Scraping:      requests, beautifulsoup4, selenium
  Scheduling:        schedule, APScheduler
  GUI-Automation:    pyautogui, pywinauto
  Excel:             openpyxl, pandas, xlrd
  E-Mail:            smtplib (Standard), yagmail
  PDF:               PyPDF2, reportlab
  Datenbanken:       sqlite3 (Standard), sqlalchemy
  Logging:           logging (Standard), loguru

SIEHE AUCH
==========
  wiki/python/dateioperationen/    Dateien lesen/schreiben
  wiki/python/regex/               Textmuster fuer Parsing
  wiki/python/api/                 REST-API-Automatisierung
  wiki/automatisierung/            BACH Automatisierungs-Konzepte
  wiki/n8n.txt                     Workflow-Automatisierung
