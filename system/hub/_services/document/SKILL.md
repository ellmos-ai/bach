---
name: DokuZentrum Service
version: 1.0.0
type: service
author: BACH Team
created: 2026-02-06
updated: 2026-02-06
anthropic_compatible: true
status: active

dependencies:
  tools: []
  services: []
  workflows: []

description: >
  Core Document Processing Service for BACH (Integration of DokuZentrum)
---
# DokuZentrum Service

Dieser Service integriert die Kern-Funktionalitäten der "DokuZentrum" Suite in BACH.

## Funktionen

1. **PDF Service**: Textextraktion, Metadaten, Rendering.
2. **OCR Service**: Texterkennung in Bildern/PDFs (via Tesseract).
3. **Redaction Service**: Erkennung und Schwärzung sensibler Daten (IBAN, etc.).
4. **Search Service**: Indizierung und Volltextsuche (FTS5).

## Architektur

Die Module liegen in `hub/_services/document/`:

- `pdf_service.py`
- `ocr_service.py`
- `redaction_service.py`
- `search_service.py`

## Integration

Ref: `../user/_archive/BACH_TOOLS_INTEGRATION_ANALYSIS.md`

```python
from skills._services.document.pdf_service import PDFProcessor
text = PDFProcessor.extract_text("rechnung.pdf")
```