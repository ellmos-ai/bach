# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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

import sys
import os
import json
import time
import shutil
import tempfile
import logging
import threading
import subprocess

# === PyQt6 Modules ===
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QLineEdit, QFileDialog, QTableWidget, 
    QTableWidgetItem, QHeaderView, QProgressBar, QCheckBox, 
    QTabWidget, QListWidget, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor

# === Processing Modules ===
import fitz  # PyMuPDF
import pikepdf # Für sichere AES-256 Verschlüsselung
from PIL import Image

# === KONSTANTEN ===
APP_TITLE = "PDFSchwärzer Pro – V2.1 (Fixed Security Logic)"
CONFIG_FILE = "config.json"
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

# === LOGGING ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# === WORKER THREAD ===
class WorkerThread(QThread):
    progress_signal = pyqtSignal(int, int, int) # idx, percent, status (0=Run, 1=Done, 2=Error, 3=Info)
    log_signal = pyqtSignal(str)
    finished_all = pyqtSignal()

    def __init__(self, file_list, sensitive_words, whitelist_words, config):
        super().__init__()
        self.file_list = file_list
        self.sensitive_words = sensitive_words
        self.whitelist_words = whitelist_words
        self.config = config
        self.is_running = True

    def run(self):
        master_pw = self.config.get("master_pw", "").strip()
        encrypt_only = self.config.get("encrypt_only", False)

        for idx, file_data in enumerate(self.file_list):
            if not self.is_running: break
            
            input_path = file_data["path"]
            # Individuelles Passwort aus der Tabelle holen
            individual_pw = file_data.get("password", "").strip()
            
            # --- LOGIK IMPLEMENTIERUNG ---
            target_password = None

            if individual_pw:
                # Priorität 1: Individuelles Passwort gesetzt -> Nutze es
                target_password = individual_pw
                self.log_signal.emit(f"🔒 {os.path.basename(input_path)}: Nutze individuelles PW.")
            elif master_pw:
                # Priorität 2: Kein individuelles, aber Master PW gesetzt -> Fallback auf Master
                target_password = master_pw
                self.log_signal.emit(f"🔐 {os.path.basename(input_path)}: Nutze Master-PW.")
            else:
                # Priorität 3: Weder noch -> Keine Verschlüsselung
                target_password = None
                self.log_signal.emit(f"🔓 {os.path.basename(input_path)}: Keine Verschlüsselung.")
            
            # --- START VERARBEITUNG ---
            self.progress_signal.emit(idx, 10, 0) 

            try:
                # 1. Konvertierung zu PDF (falls nötig)
                pdf_path = self.convert_to_pdf(input_path)
                if not pdf_path:
                    raise Exception("Konvertierung fehlgeschlagen")
                
                self.progress_signal.emit(idx, 30, 0)

                # 2. Output Pfad generieren
                folder = os.path.dirname(input_path)
                filename = os.path.splitext(os.path.basename(input_path))[0]
                suffix = "_secure.pdf" if encrypt_only else "_redacted.pdf"
                out_path = os.path.join(folder, filename + suffix)

                # 3. Hauptlogik
                if encrypt_only:
                    # Fall: Nur Verschlüsselung (Häkchen gesetzt)
                    # Wir nehmen das PDF und speichern es (verschlüsselt oder normal)
                    self.finalize_pdf(pdf_path, out_path, target_password)
                else:
                    # Fall: Schwärzen + Verschlüsselung
                    self.process_redaction_and_save(pdf_path, out_path, target_password)

                # Cleanup Temp Files (nur wenn konvertiert wurde)
                if pdf_path != input_path and os.path.exists(pdf_path):
                    try: os.remove(pdf_path)
                    except OSError: pass

                self.progress_signal.emit(idx, 100, 1) # Fertig

            except Exception as e:
                self.log_signal.emit(f"❌ Fehler bei {os.path.basename(input_path)}: {str(e)}")
                self.progress_signal.emit(idx, 0, 2) # Fehler

        self.finished_all.emit()

    def convert_to_pdf(self, path):
        """Konvertiert Word/Bilder/Text zu einem temporären PDF."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            return path
        
        temp_pdf = os.path.join(tempfile.gettempdir(), f"temp_{int(time.time())}_{os.path.basename(path)}.pdf")
        
        # Word (Windows COM)
        if ext in [".docx", ".doc", ".rtf"]:
            try:
                import win32com.client
                word = win32com.client.Dispatch("Word.Application")
                word.Visible = False
                doc = word.Documents.Open(os.path.abspath(path))
                doc.ExportAsFixedFormat(OutputFileName=temp_pdf, ExportFormat=17) # 17 = PDF
                doc.Close(False)
                return temp_pdf
            except Exception as e:
                self.log_signal.emit(f"Word-Konvertierung fehlgeschlagen: {e}")
                return None

        # Bilder
        if ext in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
            try:
                img = Image.open(path)
                img.convert("RGB").save(temp_pdf)
                return temp_pdf
            except Exception as e:
                self.log_signal.emit(f"Bild-Konvertierung fehlgeschlagen: {e}")
                return None
        
        # Text
        if ext == ".txt":
            try:
                doc = fitz.open()
                page = doc.new_page()
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                page.insert_text((50, 50), text, fontsize=11)
                doc.save(temp_pdf)
                return temp_pdf
            except Exception:
                return None

        return None

    def process_redaction_and_save(self, in_pdf, out_pdf, password):
        """OCR/Suche -> Schwärzen -> Speichern (mit/ohne PW)."""
        doc = fitz.open(in_pdf)
        
        # Temporäres PDF für das geschwärzte Resultat (noch unverschlüsselt)
        temp_redacted = os.path.join(tempfile.gettempdir(), f"redacted_{int(time.time())}.pdf")
        
        # --- SCHWÄRZUNGS-LOGIK ---
        pages_modified = 0
        for page in doc:
            for word in self.sensitive_words:
                if self.is_safe(word): continue
                
                # Case-Insensitive Suche
                hits = page.search_for(word)
                if hits:
                    pages_modified += 1
                    for rect in hits:
                        page.add_redact_annot(rect, fill=(0, 0, 0))
            
            # Anwenden der Schwärzungen
            page.apply_redactions()

        if pages_modified == 0:
            self.log_signal.emit("ℹ️ Keine sensiblen Begriffe gefunden.")
        
        # Zwischenspeichern (unverschlüsselt)
        doc.save(temp_redacted)
        doc.close()

        # Finales Speichern (Verschlüsselung anwenden falls PW da ist)
        self.finalize_pdf(temp_redacted, out_pdf, password)
        
        # Temp cleanup
        if os.path.exists(temp_redacted):
            os.remove(temp_redacted)

    def finalize_pdf(self, source_path, dest_path, password):
        """Übernimmt eine PDF und speichert sie am Zielort - verschlüsselt ODER kopiert."""
        if password:
            try:
                # AES-256 Verschlüsselung mit Pikepdf
                pdf = pikepdf.open(source_path)
                enc = pikepdf.Encryption(
                    owner=password, 
                    user=password, 
                    R=6 
                )
                pdf.save(dest_path, encryption=enc)
                pdf.close()
            except Exception as e:
                self.log_signal.emit(f"⚠️ Encryption-Fehler: {e}. Speichere unverschlüsselt.")
                shutil.copy(source_path, dest_path)
        else:
            # Kein Passwort -> Einfaches Kopieren
            shutil.copy(source_path, dest_path)

    def is_safe(self, word):
        """Prüft, ob ein Wort auf der Whitelist steht."""
        norm_word = word.strip().lower()
        for white in self.whitelist_words:
            if norm_word == white.strip().lower():
                return True
        return False

# === MAIN GUI CLASS ===
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 750)
        self.setAcceptDrops(True)

        # Daten
        self.file_list = [] 
        self.sensitive = []
        self.whitelist = []
        self.config = self.load_config()

        # UI Setup
        self.init_ui()
        self.apply_stylesheet()
        
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError): pass
        return {"master_pw": "", "lang": "deu", "encrypt_only": False}

    def save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # --- LINKE SPALTE (Settings & Listen) ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(350)

        # Listen-Bereich
        tabs = QTabWidget()
        self.list_sens = QListWidget()
        self.list_white = QListWidget()
        tabs.addTab(self.list_sens, "🔴 Sensibel")
        tabs.addTab(self.list_white, "🟢 Whitelist")
        
        # Eingabe für neue Wörter
        self.input_word = QLineEdit()
        self.input_word.setPlaceholderText("Neues Wort hinzufügen...")
        self.input_word.returnPressed.connect(self.add_word)
        
        btn_add = QPushButton("Hinzufügen")
        btn_add.clicked.connect(self.add_word)
        
        h_input = QHBoxLayout()
        h_input.addWidget(self.input_word)
        h_input.addWidget(btn_add)

        left_layout.addWidget(QLabel("<b>Begriffs-Management</b>"))
        left_layout.addLayout(h_input)
        left_layout.addWidget(tabs)
        
        # Buttons zum Laden
        btn_load_sens = QPushButton("📂 Sensible Liste laden")
        btn_load_sens.clicked.connect(lambda: self.load_list_from_file("sens"))
        left_layout.addWidget(btn_load_sens)

        # Optionen Box
        group_opts = QGroupBox("Optionen")
        layout_opts = QVBoxLayout()
        
        self.chk_encrypt_only = QCheckBox("Nur Verschlüsselung (Keine Schwärzung)")
        self.chk_encrypt_only.setChecked(self.config.get("encrypt_only", False))
        self.chk_encrypt_only.toggled.connect(self.update_config_vars)
        
        self.input_master_pw = QLineEdit()
        self.input_master_pw.setPlaceholderText("Master-Passwort (Fallback)")
        self.input_master_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_master_pw.setText(self.config.get("master_pw", ""))
        self.input_master_pw.textChanged.connect(self.update_config_vars)

        layout_opts.addWidget(self.chk_encrypt_only)
        layout_opts.addWidget(QLabel("Master-Passwort:"))
        layout_opts.addWidget(self.input_master_pw)
        group_opts.setLayout(layout_opts)
        
        left_layout.addWidget(group_opts)
        left_layout.addStretch()

        # --- RECHTE SPALTE (Dateien & Verarbeitung) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Dropzone
        self.drop_label = QLabel("\n📂 Dateien hier hineinziehen\n(Drag & Drop)\n")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setObjectName("DropZone")
        right_layout.addWidget(self.drop_label)

        # Tabelle
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Datei", "Indiv. Passwort", "Status", "Fortschritt"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(3, 150)
        right_layout.addWidget(self.table)

        # Action Buttons
        h_btns = QHBoxLayout()
        btn_clear = QPushButton("Liste leeren")
        btn_clear.clicked.connect(self.clear_list)
        
        self.btn_start = QPushButton("▶ Verarbeitung Starten")
        self.btn_start.setObjectName("StartButton")
        self.btn_start.clicked.connect(self.start_processing)
        self.btn_start.setMinimumHeight(50)

        h_btns.addWidget(btn_clear)
        h_btns.addWidget(self.btn_start)
        right_layout.addLayout(h_btns)

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)

    def apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2b2b2b; color: #ffffff;
                font-family: 'Segoe UI', Arial; font-size: 14px;
            }
            QGroupBox { border: 1px solid #555; margin-top: 20px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
            QLineEdit, QListWidget, QTableWidget {
                background-color: #363636; border: 1px solid #555;
                border-radius: 4px; padding: 5px; color: #fff;
            }
            QTabWidget::pane { border: 1px solid #555; }
            QTabBar::tab { background: #363636; padding: 8px 20px; }
            QTabBar::tab:selected { background: #505050; }
            QPushButton { background-color: #0d6efd; color: white; border: none; padding: 8px 15px; border-radius: 4px; }
            QPushButton:hover { background-color: #0b5ed7; }
            QLabel#DropZone {
                border: 2px dashed #666; border-radius: 10px;
                background-color: #333; font-size: 16px; color: #aaa; margin-bottom: 10px;
            }
            QLabel#DropZone:hover { border-color: #0d6efd; color: #fff; }
            QPushButton#StartButton { background-color: #198754; font-size: 16px; font-weight: bold; }
            QPushButton#StartButton:hover { background-color: #157347; }
            QProgressBar { border: 1px solid #555; border-radius: 5px; text-align: center; }
            QProgressBar::chunk { background-color: #0d6efd; }
        """)

    # === DRAG & DROP ===
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        self.add_files(files)

    # === LOGIC ===
    def add_files(self, paths):
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            if ext not in ALLOWED_EXTENSIONS: continue

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(path)))
            
            # Passwort Feld
            pw_edit = QLineEdit()
            pw_edit.setPlaceholderText("Optionales PW")
            pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.table.setCellWidget(row, 1, pw_edit)
            
            self.table.setItem(row, 2, QTableWidgetItem("Wartend"))
            
            pbar = QProgressBar()
            pbar.setValue(0)
            self.table.setCellWidget(row, 3, pbar)
            
            self.file_list.append({"path": path, "row": row})

    def add_word(self):
        word = self.input_word.text().strip()
        if not word: return
        target_list = self.list_sens if self.list_sens.isVisible() else self.list_white
        target_data = self.sensitive if self.list_sens.isVisible() else self.whitelist
        
        if word not in target_data:
            target_data.append(word)
            target_list.addItem(word)
        self.input_word.clear()

    def load_list_from_file(self, target):
        path, _ = QFileDialog.getOpenFileName(self, "Liste laden", "", "Text/Excel (*.txt *.xlsx)")
        if not path: return
        try:
            words = []
            if path.endswith(".xlsx"):
                import pandas as pd
                df = pd.read_excel(path)
                words = df.values.flatten().astype(str).tolist()
            else:
                with open(path, "r", encoding="utf-8") as f:
                    words = [line.strip() for line in f if line.strip()]
            
            list_widget = self.list_sens if target == "sens" else self.list_white
            data_list = self.sensitive if target == "sens" else self.whitelist
            
            for w in words:
                if w not in data_list:
                    data_list.append(w)
                    list_widget.addItem(w)
            QMessageBox.information(self, "Erfolg", f"{len(words)} Wörter geladen.")
        except Exception as e:
            QMessageBox.critical(self, "Fehler", str(e))

    def update_config_vars(self):
        # Wird bei Änderungen an den GUI-Elementen aufgerufen
        self.config["master_pw"] = self.input_master_pw.text()
        self.config["encrypt_only"] = self.chk_encrypt_only.isChecked()
        self.save_config()

    def clear_list(self):
        self.table.setRowCount(0)
        self.file_list = []

    def start_processing(self):
        if not self.file_list:
            QMessageBox.warning(self, "Achtung", "Keine Dateien in der Liste.")
            return

        self.btn_start.setEnabled(False)
        self.btn_start.setText("Verarbeitung läuft...")
        
        # Sicherstellen, dass die Config aktuell ist
        self.update_config_vars()

        # Passwörter aus der Tabelle lesen und in self.file_list speichern
        for i, f_data in enumerate(self.file_list):
            row = f_data["row"]
            widget = self.table.cellWidget(row, 1) # Spalte 1 = Passwort
            if isinstance(widget, QLineEdit):
                pw = widget.text().strip()
                f_data["password"] = pw # Speichern im Dictionary für den Thread

        # Thread starten
        self.worker = WorkerThread(self.file_list, self.sensitive, self.whitelist, self.config)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.log_signal.connect(print) 
        self.worker.finished_all.connect(self.on_finished)
        self.worker.start()

    def update_progress(self, idx, percent, status_code):
        row = self.file_list[idx]["row"]
        pbar = self.table.cellWidget(row, 3)
        if pbar: pbar.setValue(percent)
        
        status_item = self.table.item(row, 2)
        if status_code == 0:
            status_item.setText("Läuft...")
            status_item.setForeground(QColor("#FFA500"))
        elif status_code == 1:
            status_item.setText("Fertig")
            status_item.setForeground(QColor("#00FF00"))
        elif status_code == 2:
            status_item.setText("Fehler")
            status_item.setForeground(QColor("#FF0000"))

    def on_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_start.setText("▶ Verarbeitung Starten")
        QMessageBox.information(self, "Abgeschlossen", "Alle Aufgaben erledigt.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())