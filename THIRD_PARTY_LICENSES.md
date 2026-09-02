# BACH - Third-Party Licenses
<!-- AUTO-GENERATED via SQ034 (2026-02-18) - update when dependencies change -->

This document lists all third-party Python packages used by BACH,
their versions (as tested), and their respective licenses.

> **SQ072/ENT-32 (2026-02-19):** PyMuPDF (fitz) wurde als Core-Dependency entfernt.
> Core PDF-Lesen nutzt jetzt pypdf (MIT) + pdfplumber (MIT).
> PyMuPDF bleibt als OPTIONALE Dependency fuer: PDF-Rendering fuer OCR,
> PDF-Schwaerzung (_vendor/), Redaction-Erkennung.
> Steuer-Agent-Dateien (dist_type=0) sind nicht Teil des Release.
> Damit ist BACH als MIT-Projekt publizierbar ohne AGPL-Infizierung durch PyMuPDF.

---

## Core Dependencies

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `requests` | 2.32.5 | Apache-2.0 | HTTP client |
| `httpx` | 0.28.1 | BSD-3-Clause | Async HTTP |
| `aiohttp` | 3.13.0 | Apache-2.0 AND MIT | Async HTTP sessions |
| `PyYAML` | 6.0.2 | MIT | YAML parsing |
| `toml` | 0.10.2 | MIT | TOML parsing |
| `python-dotenv` | 1.2.1 | BSD (see metadata) | .env file loading |
| `pydantic` | 2.12.5 | MIT (see metadata) | Data validation |
| `xmltodict` | 1.0.2 | MIT | XML ↔ dict |
| `defusedxml` | 0.7.1 | PSFL (Python SF License) | Secure XML parsing |
| `lxml` | 6.0.0 | BSD-3-Clause | XML/HTML processing |
| `emoji` | 2.15.0 | BSD | Emoji handling |
| `ftfy` | 6.3.1 | Apache-2.0 | Unicode/encoding repair |
| `rapidfuzz` | 3.14.3 | MIT (see metadata) | Fuzzy string matching |
| `markdown` | 3.10 | BSD (see metadata) | Markdown → HTML |
| `watchdog` | 6.0.0 | Apache-2.0 | File system monitoring |
| `psutil` | 7.0.0 | BSD-3-Clause | System/process info |
| `GitPython` | 3.1.46 | BSD-3-Clause | Git operations |
| `colorama` | 0.4.6 | BSD | ANSI terminal colors |
| `rich` | 14.2.0 | MIT | Rich terminal output |
| `click` | 8.2.1 | BSD (see metadata) | CLI argument parsing |
| `typer` | 0.21.1 | MIT (see metadata) | Typed CLI building |
| `tqdm` | 4.67.1 | MPL-2.0 AND MIT | Progress bars |
| `cryptography` | 45.0.5 | Apache-2.0 OR BSD-3-Clause | Encryption |
| `keyring` | 25.7.0 | MIT (see metadata) | OS keychain |
| `peewee` | 3.19.0 | MIT (see metadata) | Lightweight ORM |
| `pypdf` | 6.4.0 | MIT (see metadata) | PDF text extraction (core, replaces PyMuPDF for reading) |
| `pdfplumber` | 0.11.7 | MIT | PDF text/table extraction (core, fallback after pypdf) |
| `pikepdf` | 10.0.2 | MPL-2.0 (see metadata) | PDF low-level editing |
| `pyperclip` | 1.9.0 | BSD | Clipboard access |
| `pyautogui` | 0.9.54 | BSD | GUI automation |

---

## Optional Dependencies

### Document Processing

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `PyMuPDF` | 1.26.4 | **AGPL-3.0 OR Commercial** | ⚠️ OPTIONAL: PDF render/redact/OCR-render (fitz). SQ072/ENT-32: Core PDF reading replaced by pypdf+pdfplumber. Install only for OCR-rendering or redaction features. |
| `extract_msg` | 0.55.0 | **GPL** | ⚠️ OPTIONAL: Parse .msg Outlook files (report_generator). SQ072/ENT-32: Moved to optional due to GPL incompatibility with MIT. Install only if you need Outlook .msg parsing. |
| `pdf2image` | 1.17.0 | MIT | PDF → image (requires poppler) |
| `reportlab` | 4.4.5 | BSD | PDF generation |
| `fpdf2` | 2.8.3 | **LGPL-3.0** | Lightweight PDF creation |
| `weasyprint` | 68.1 | BSD | HTML/CSS → PDF |
| `Pillow` | 10.4.0 | HPND (PIL License) | Image processing |
| `pytesseract` | 0.3.13 | Apache-2.0 | OCR wrapper |
| `python-docx` | 1.2.0 | MIT | Word .docx files |
| `python-pptx` | 1.0.2 | MIT | PowerPoint .pptx files |
| `openpyxl` | 3.1.5 | MIT | Excel .xlsx files |

### AI / LLM Partners

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `anthropic` | 0.79.0 | MIT | Claude API (primary LLM) |
| `ollama` | 0.6.1 | MIT (see metadata) | Ollama local LLM |
| `openai-whisper` | 20250625 | MIT | Speech-to-text (Whisper) |

### Data Analysis / Market

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `numpy` | 2.3.1 | BSD | Numerical computing |
| `pandas` | 2.3.1 | BSD | Data analysis |
| `scipy` | 1.16.0 | BSD | Scientific computing |
| `matplotlib` | 3.10.6 | PSF License | Plotting |
| `yfinance` | 1.0 | Apache | Yahoo Finance data |

### Vector Database / RAG

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `chromadb` | 1.4.1 | Apache-2.0 | Embedded vector DB |

### GUI / Web Server

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `PyQt6` | 6.10.0 | GPL-3.0 (see metadata) | ⚠️ Qt GUI framework |
| `fastapi` | 0.128.0 | MIT (see metadata) | Web API framework |
| `uvicorn` | 0.40.0 | BSD (see metadata) | ASGI server |
| `starlette` | 0.50.0 | BSD (see metadata) | ASGI framework |
| `pystray` | 0.19.5 | LGPL-3.0 | System tray icon |
| `tkinterdnd2` | 0.4.3 | MIT | Drag & drop (Tk) |
| `selenium` | 4.38.0 | Apache-2.0 | Browser automation |
| `ellmos-unified-gui` | optional Git commit `a0d59af` | MIT | Operator console via the `console` install extra |

### Google Services

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `google-api-python-client` | 2.187.0 | Apache-2.0 | Google APIs |
| `google-auth-oauthlib` | 1.2.3 | Apache-2.0 | Google OAuth2 |

### Voice / Audio

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `pyttsx3` | 2.99 | MIT (see metadata) | Text-to-speech |

### Windows-Specific

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `pywin32` | 311 | PSF | Windows COM/API |

### Development / Testing

| Package | Version | License | Notes |
|---------|---------|---------|-------|
| `pytest` | 9.0.2 | MIT (see metadata) | Test runner |

---

## Packages Referenced But Not Installed

These are referenced in the source code but not currently installed
(planned integrations, optional features, or legacy code):

| Import name | PyPI package | Notes |
|-------------|-------------|-------|
| `fitz` | PyMuPDF | Already listed above (different import name) |
| `sklearn` | `scikit-learn` | ML market analysis models |
| `tensorflow` | `tensorflow` | Neural network (market analysis) |
| `statsmodels` | `statsmodels` | Statistical models (market analysis) |
| `playwright` | `playwright` | Web automation (testing examples only) |
| `html2text` | `html2text` | HTML → Markdown (web parse) |
| `croniter` | `croniter` | Cron expressions (GUI scheduler) |
| `google` | `google-generativeai` | Gemini API (planned) |
| `mcp` | `mcp` | MCP SDK (tools/mcp_server.py) |
| `pyaudio` | `pyaudio` | Audio I/O (voice STT) |
| `vosk` | `vosk` | Offline speech recognition |
| `openwakeword` | `openWakeWord` | Wake word detection |
| `piper` | `piper-tts` | Neural TTS (voice) |
| `whisper` | `openai-whisper` | Already listed above |
| `telegram` | `python-telegram-bot` | Telegram connector |
| `textract` | `textract` | Document text extraction |

---

## ⚠️ License Compatibility Notes

Critical items requiring attention before public release:

1. **PyMuPDF (AGPL-3.0):** ✅ RESOLVED by SQ072 (2026-02-19). Core PDF-Lesen
   migriert zu pypdf+pdfplumber (MIT). PyMuPDF ist jetzt NUR optional fuer
   Spezial-Features (OCR-Rendering, Schwaerzung). Steuer-Expert-Dateien
   (dist_type=0) sind vom Release ausgenommen. AGPL-Infizierung des
   MIT-Release ist damit beseitigt.

2. **extract_msg (GPL):** Used in 2 files for .msg email parsing.
   GPL is similarly restrictive. Can be made optional (only install
   if .msg parsing is needed).

3. **PyQt6 (GPL-3.0):** Used only in `gui/prompt_manager.py` and
   `pdf_schwaerzer_pro.py`. Both are optional/tool components.
   Can be classified as optional.

4. **fpdf2 (LGPL-3.0):** LGPL allows linking from non-GPL code
   without copyleft propagation. Generally compatible.

5. **pystray (LGPL-3.0):** Same as fpdf2, generally compatible.

**Recommended BACH license given the above:**
If retaining PyMuPDF and PyQt6: **GPL-3.0 or AGPL-3.0**
If replacing/making optional: **MIT or Apache-2.0** (preferred for open source)

---

*Generated: 2026-02-18 | BACH v2.6.0 (Vanilla) | Python 3.12*
*To regenerate: python BACH_Dev/tools/scan_imports.py (SQ034)*
