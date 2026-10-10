# SPDX-License-Identifier: MIT
"""
Betriebsmodi der Foerderbericht-Pipeline.

Drei Wege vom Aktenordner zum Bericht:

  lokal   Ein lokales Modell (Ollama) liest die Akte und schreibt den
          Bericht. Die Daten verlassen den Rechner nicht, deshalb entfaellt
          die Anonymisierung.
  cloud   Wie bisher: Akte anonymisieren, Cloud-Modell bzw. Subscription
          schreibt den Bericht, danach de-anonymisieren.
  hybrid  Ein Cloud-Modell steuert, ein lokales Modell liest und schreibt.
          Die Cloud bekommt nur Strukturdaten (Dokumenttypen, Monat/Jahr,
          Textlaengen, Feldstatus, ICF-Codes) und nie Akteninhalt. Sie
          plant den Bericht und prueft das Ergebnis; das lokale Modell
          setzt Plan und Nachbesserungen um.

Konfiguration (Umgebungsvariablen):
  BACH_FOERDERBERICHT_MODUS          Standardmodus (Default: cloud)
  BACH_FOERDERBERICHT_LOKAL_MODELL   Ollama-Modell (Default: qwen3.8:27b-mlx)
  BACH_FOERDERBERICHT_MAX_CTX        Groesstes lokales Kontextfenster in
                                     Tokens (Default: 65536)
  OLLAMA_URL                         Ollama-Endpunkt (Default: localhost)
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import math
import os
import re
from collections.abc import Callable, Iterable
from typing import Any

MODI = ("lokal", "cloud", "hybrid")
_ALIASE = {"local": "lokal", "ollama": "lokal", "anonym": "cloud", "anonymisiert": "cloud"}

DEFAULT_LOKAL_MODELL = "qwen3.8:27b-mlx"
_MIN_CTX = 8192
_ANTWORT_RESERVE = 8192          # Tokens fuer die JSON-Antwort
_ZEICHEN_JE_TOKEN = 3.0          # vorsichtig fuer deutschen Text

_ICF_CODE_RE = re.compile(r"\b[bdes]\d{3,5}\b")
_SCHLUESSEL_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")


class ModusFehler(Exception):
    """Fehler in einem Pipeline-Modus (Konfiguration, Modell, Datenschutz)."""


# ─────────────────────────────────────────────────────────────
# Konfiguration
# ─────────────────────────────────────────────────────────────

def resolve_modus(value: str | None = None) -> str:
    """Normalisiert einen Modusnamen; ohne Angabe gilt die Konfiguration."""
    raw = value if value else os.environ.get("BACH_FOERDERBERICHT_MODUS", "cloud")
    modus = _ALIASE.get(str(raw).strip().lower(), str(raw).strip().lower())
    if modus not in MODI:
        raise ModusFehler(
            f"Unbekannter Modus '{raw}'. Erlaubt: {', '.join(MODI)}"
        )
    return modus


def lokal_modell(value: str | None = None) -> str:
    return value or os.environ.get("BACH_FOERDERBERICHT_LOKAL_MODELL", DEFAULT_LOKAL_MODELL)


def _max_ctx() -> int:
    try:
        return int(os.environ.get("BACH_FOERDERBERICHT_MAX_CTX", "65536"))
    except ValueError as exc:
        raise ModusFehler("BACH_FOERDERBERICHT_MAX_CTX muss eine ganze Zahl sein") from exc


def benoetigter_kontext(prompt: str) -> int:
    """Kontextfenster (Tokens) fuer Prompt plus Antwort, auf 4096 gerundet.

    Ollama kuerzt zu lange Prompts stillschweigend von vorne; dann fehlten
    dem Modell die Anweisungen. Deshalb wird vorher gerechnet und bei
    Ueberschreitung abgebrochen statt still ein halber Bericht erzeugt.
    """
    tokens = math.ceil(len(prompt) / _ZEICHEN_JE_TOKEN) + _ANTWORT_RESERVE
    ctx = max(_MIN_CTX, math.ceil(tokens / 4096) * 4096)
    grenze = _max_ctx()
    if ctx > grenze:
        raise ModusFehler(
            f"Akte zu gross fuer das lokale Kontextfenster: etwa {tokens} Tokens "
            f"benoetigt, Grenze {grenze}. BACH_FOERDERBERICHT_MAX_CTX erhoehen "
            f"(mehr Arbeitsspeicher) oder Modus 'cloud' verwenden."
        )
    return ctx


# ─────────────────────────────────────────────────────────────
# Lokales Modell
# ─────────────────────────────────────────────────────────────

def _run_sync(coro):
    """Fuehrt eine Coroutine aus, auch wenn bereits ein Event-Loop laeuft
    (etwa wenn der Chat-Runtime das Werkzeug aufruft)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def call_local_llm(prompt: str, model: str | None = None,
                   system: str | None = None, backend=None) -> str:
    """Schickt einen Prompt an das lokale Modell und liefert den Antworttext."""
    model = lokal_modell(model)
    if backend is None:
        from hub._services.llm.model_backend import create_backend
        backend = create_backend({
            "type": "ollama",
            "base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            "default_model": model,
            "num_ctx": benoetigter_kontext((system or "") + prompt),
            "timeout_seconds": 3600,
        })
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    result = _run_sync(backend.chat(messages, think=False, model=model))
    if not isinstance(result, dict):
        raise ModusFehler("Lokales Modell lieferte keine verwertbare Antwort")
    if result.get("error"):
        raise ModusFehler(f"Lokales Modell ({model}): {result['error']}")
    content = str(result.get("content") or "").strip()
    if not content:
        raise ModusFehler(f"Lokales Modell ({model}) lieferte eine leere Antwort")
    return content


# ─────────────────────────────────────────────────────────────
# Hybrid: Strukturdaten fuer die Cloud und Datenschutz-Sperre
# ─────────────────────────────────────────────────────────────

def struktur_uebersicht(documents: Iterable[Any], berichtszeitraum: str) -> dict:
    """Beschreibt die Akte ohne Inhalt: Kategorie, Dokumenttyp, Monat/Jahr,
    Textlaenge. Dateinamen werden bewusst nicht uebernommen (sie enthalten
    oft Namen)."""
    eintraege = []
    for doc in documents:
        category = getattr(getattr(doc, "category", None), "value", "")
        if category == "skip":
            continue
        date_hint = getattr(doc, "date_hint", None)
        eintraege.append({
            "kategorie": category,
            "typ": str(getattr(doc, "doc_type", "") or "sonstiges"),
            "monat": date_hint.strftime("%Y-%m") if date_hint else None,
            "zeichen": int(getattr(doc, "text_length", 0) or getattr(doc, "size_bytes", 0) or 0),
        })
    return {"berichtszeitraum": berichtszeitraum, "dokumente": eintraege}


def entwurf_metadaten(entwurf: dict) -> dict:
    """Beschreibt einen JSON-Berichtsentwurf ohne Inhalt: welche Felder
    gefuellt sind, wie lang, wie viele Eintraege, welche ICF-Codes."""
    felder = {}

    def walk(value, pfad):
        if isinstance(value, dict):
            for key, sub in value.items():
                key = str(key)
                if not _SCHLUESSEL_RE.match(key):
                    key = "<feld>"
                walk(sub, f"{pfad}.{key}" if pfad else key)
        elif isinstance(value, list):
            felder[pfad] = {"typ": "liste", "eintraege": len(value)}
            for item in value[:1]:
                walk(item, f"{pfad}[]")
        else:
            text = "" if value is None else str(value)
            felder.setdefault(pfad, {"typ": "text", "zeichen": len(text.strip())})

    walk(entwurf, "")
    codes = sorted(set(_ICF_CODE_RE.findall(json.dumps(entwurf, ensure_ascii=False))))
    return {"felder": felder, "icf_codes": codes}


def sensible_begriffe(*werte: Any) -> list[str]:
    """Sammelt Namen, Namensteile und Daten, die nie in die Cloud duerfen."""
    begriffe: set[str] = set()
    for wert in werte:
        if not wert:
            continue
        items = wert if isinstance(wert, (list, tuple, set)) else [wert]
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            begriffe.add(text)
            for teil in re.split(r"[\s,;]+", text):
                if len(teil) >= 3:
                    begriffe.add(teil)
    return sorted(begriffe, key=len, reverse=True)


def pruefe_cloud_nutzlast(nutzlast: str, begriffe: Iterable[str]) -> None:
    """Datenschutz-Sperre: bricht ab, wenn ein sensibler Begriff in der
    Cloud-Nutzlast steht."""
    for begriff in begriffe:
        if not begriff:
            continue
        # Ganze Woerter: "Ben" soll nicht in "benoetigt" anschlagen.
        if re.search(rf"(?<!\w){re.escape(begriff)}(?!\w)", nutzlast, re.IGNORECASE):
            raise ModusFehler(
                "Datenschutz-Sperre: Die Nachricht an das Cloud-Modell enthielt "
                "personenbezogene Angaben. Hybrid-Lauf abgebrochen."
            )


# ─────────────────────────────────────────────────────────────
# Hybrid-Ablauf
# ─────────────────────────────────────────────────────────────

_PLAN_PROMPT = """Du steuerst die Erstellung eines Foerderberichts (ICF-basiert).
Du siehst die Akte NICHT. Ein lokales Modell liest die Akte und schreibt den
Bericht als JSON nach einem festen Schema. Deine Aufgabe ist der Arbeitsplan.

Uebersicht der Akte (nur Struktur, kein Inhalt):
{uebersicht}

Schreibe einen knappen Arbeitsplan fuer das lokale Modell (hoechstens 25
Zeilen, Deutsch):
- Welche Dokumenttypen fuer welche Berichtsabschnitte massgeblich sind
  (z. B. Hilfeplan fuer die Ziele, aktuelle Protokolle fuer den Verlauf).
- Welche Gewichtung bei Widerspruechen gilt (neuere Dokumente vor aelteren).
- Worauf bei ICF-Codes, Zielformulierungen und dem Berichtszeitraum zu achten ist.
Nenne keine Personen und erfinde keine Inhalte. Antworte nur mit dem Plan."""

_PRUEF_PROMPT = """Du pruefst einen Foerderbericht-Entwurf, den ein lokales Modell
als JSON geschrieben hat. Du siehst nur Metadaten, keinen Inhalt.

Arbeitsplan:
{plan}

Metadaten des Entwurfs (Feld -> Typ/Laenge, verwendete ICF-Codes):
{metadaten}

Pruefe auf leere oder auffaellig kurze Pflichtfelder, fehlende Ziele bzw.
Abschnitte und ungewoehnliche ICF-Codes. Wenn alles passt, antworte genau
mit: OK
Sonst antworte mit einer nummerierten Liste konkreter Nachbesserungen fuer
das lokale Modell (hoechstens 10 Punkte)."""

_UMSETZ_ANWEISUNG = """=== ARBEITSPLAN DER STEUERUNG ===
Halte dich bei der Auswertung der Akte an diesen Plan:
{plan}"""

_NACHBESSER_PROMPT = """Ueberarbeite den folgenden Foerderbericht-Entwurf
(JSON) anhand der Hinweise. Nutze dafuer die Akte aus dem urspruenglichen
Auftrag. Behalte das JSON-Schema exakt bei und antworte nur mit dem
vollstaendigen, ueberarbeiteten JSON.

=== HINWEISE ===
{hinweise}

=== URSPRUENGLICHER AUFTRAG (mit Akte) ===
{prompt}

=== BISHERIGER ENTWURF ===
{entwurf}"""


def _json_aus(text: str) -> dict | None:
    """Holt das erste JSON-Objekt aus einer Modellantwort."""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    kandidat = match.group(1) if match else None
    if kandidat is None:
        start, ende = text.find("{"), text.rfind("}")
        if start == -1 or ende <= start:
            return None
        kandidat = text[start:ende + 1]
    try:
        data = json.loads(kandidat)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def run_hybrid(prompt: str, uebersicht: dict, sensible: Iterable[str],
               cloud: Callable[[str], str], lokal: Callable[[str], str],
               log: Callable[[str], None] | None = None) -> str:
    """Cloud plant und prueft, das lokale Modell liest und schreibt.

    Args:
        prompt: Vollstaendiger Berichts-Prompt mit Akte (bleibt lokal).
        uebersicht: Strukturdaten aus struktur_uebersicht().
        sensible: Begriffe, die nie in die Cloud duerfen.
        cloud: Aufruf des Cloud-Modells (Prompt -> Text).
        lokal: Aufruf des lokalen Modells (Prompt -> Text).
        log: Optionaler Fortschrittsmelder.

    Returns:
        JSON-Antwort des lokalen Modells (Text).
    """
    sensible = list(sensible)
    note = log or (lambda _msg: None)

    # 1. Cloud plant -- nur Strukturdaten
    plan_prompt = _PLAN_PROMPT.format(
        uebersicht=json.dumps(uebersicht, ensure_ascii=False, indent=1)
    )
    pruefe_cloud_nutzlast(plan_prompt, sensible)
    plan = cloud(plan_prompt).strip()
    note(f"hybrid: Plan der Steuerung ({len(plan)} Zeichen)")

    # 2. Lokal schreibt -- mit Akte und Plan
    entwurf_text = lokal(prompt + "\n\n" + _UMSETZ_ANWEISUNG.format(plan=plan))
    entwurf = _json_aus(entwurf_text)
    note("hybrid: Entwurf lokal geschrieben")
    if entwurf is None:
        # Kein gueltiges JSON: die Pruefung haette keine Metadaten, also
        # unveraendert an die Berichtserzeugung (die den Markdown-Fallback kennt).
        return entwurf_text

    # 3. Cloud prueft -- nur Metadaten
    pruef_prompt = _PRUEF_PROMPT.format(
        plan=plan,
        metadaten=json.dumps(entwurf_metadaten(entwurf), ensure_ascii=False, indent=1),
    )
    pruefe_cloud_nutzlast(pruef_prompt, sensible)
    hinweise = cloud(pruef_prompt).strip()
    if hinweise.upper().strip(" .!") == "OK":
        note("hybrid: Pruefung ohne Befund")
        return entwurf_text

    # 4. Lokal bessert nach -- eine Runde
    note("hybrid: Nachbesserung lokal")
    ueberarbeitet = lokal(_NACHBESSER_PROMPT.format(
        hinweise=hinweise, prompt=prompt,
        entwurf=json.dumps(entwurf, ensure_ascii=False, indent=1),
    ))
    return ueberarbeitet if _json_aus(ueberarbeitet) is not None else entwurf_text
