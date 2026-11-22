# SPDX-License-Identifier: MIT
"""
Kredit Handler - Kredite und Umschuldung (dünner Adapter auf credits-core)
==========================================================================

bach kredit import DATEI      Kredite aus umschuldung-state/1 (JSON) übernehmen
bach kredit list              Alle Kredite anzeigen
bach kredit ueberblick        Raten, Ablösebetrag, offene Zahlungen
bach kredit vergleich --angebot ZINS/MONATE [--angebot ...] [--kosten EUR]
                              [--mit-unklaren] [--ids 1,2]

Fachlogik und Speicher leben im Ocean-Modul credits-core (Finanzbündel
ellmos-finance-assist-bundle). Hier liegt nur die Übersetzung des
umschuldung-state/1-Formats und die CLI-Ausgabe. Tabelle: credit_contracts
(Migration 055). Daten bleiben in der lokalen bach.db.
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import BaseHandler
from ._services.alltag_import import AlltagImportError, load_payload
from hub._services.ocean_stack_bridge import load_credits_core_module

STATE_SCHEMA = "umschuldung-state/1"
SOURCE = "umschuldung-state"


def _num(value, label: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AlltagImportError(f"{label}: Zahl erwartet.")
    return float(value)


def _range(value, label: str) -> tuple:
    if value is None:
        return None, None
    if isinstance(value, list):
        if len(value) != 2:
            raise AlltagImportError(f"{label}: Spanne braucht genau zwei Werte.")
        lo, hi = _num(value[0], label), _num(value[1], label)
        return (lo, hi) if lo <= hi else (hi, lo)
    n = _num(value, label)
    return n, n


def _active(status: str):
    s = (status or "").strip().lower()
    if s.startswith("laeuft") or s.startswith("läuft"):
        return 1
    if s == "erledigt":
        return 0
    return None  # unklar, "vermutlich erledigt" usw.: nicht raten


def _basis(rest_art) -> str:
    """rest_art ist Freitext; nur eindeutige Fälle werden zugeordnet."""
    if not rest_art:
        return "unknown"
    t = str(rest_art).lower()
    with_interest = "inkl. zinsen" in t or "offene raten" in t
    without_interest = "ohne zinsen" in t
    if with_interest and not without_interest:
        return "payments"
    if without_interest and not with_interest:
        return "principal"
    return "unknown"


def records_from_state(payload: dict) -> list[dict]:
    credits = payload.get("kredite")
    if not isinstance(credits, list):
        raise AlltagImportError("Feld 'kredite' muss eine Liste sein.")
    records, seen = [], set()
    for item in credits:
        if not isinstance(item, dict):
            raise AlltagImportError("Jeder Kredit muss ein Objekt sein.")
        sid = str(item.get("id") or "").strip()
        label = f"Kredit {sid or '?'}"
        if not sid or sid in seen:
            raise AlltagImportError(f"{label}: fehlende oder doppelte id.")
        seen.add(sid)
        eff_lo, eff_hi = _range(item.get("zins_eff"), f"{label} zins_eff")
        rest_lo, rest_hi = _range(item.get("rest_geschaetzt"), f"{label} rest_geschaetzt")
        term = item.get("laufzeit_monate")
        if term is not None and (isinstance(term, bool) or not isinstance(term, int) or term <= 0):
            raise AlltagImportError(f"{label}: laufzeit_monate muss eine positive ganze Zahl sein.")
        nominal = item.get("zins_soll")
        records.append({
            "source": SOURCE,
            "source_id": sid,
            "creditor": str(item.get("glaeubiger") or "").strip(),
            "kind": item.get("art"),
            "reference": item.get("kennung"),
            "status": item.get("status"),
            "active": _active(item.get("status")),
            "start_date": item.get("beginn"),
            "principal": _num(item.get("betrag"), f"{label} betrag"),
            "monthly_payment": _num(item.get("rate"), f"{label} rate"),
            "term_months": term,
            "eff_rate_min": eff_lo,
            "eff_rate_max": eff_hi,
            "nominal_rate": nominal if isinstance(nominal, (int, float)) and not isinstance(nominal, bool) else None,
            "remaining_min": rest_lo,
            "remaining_max": rest_hi,
            "remaining_basis": _basis(item.get("rest_art")),
            "notes": json.dumps({"rest_art": item.get("rest_art"), "offen": item.get("offen") or []},
                                ensure_ascii=False),
        })
    return records


def _eur(value) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def _span(lo, hi) -> str:
    return _eur(lo) if round(lo, 2) == round(hi, 2) else f"{_eur(lo)} bis {_eur(hi)}"


def _parse_offer(text: str) -> tuple[float, int]:
    try:
        rate, months = text.replace(",", ".").split("/")
        rate_f, months_i = float(rate), int(months)
    except ValueError as exc:
        raise ValueError(f"Angebot {text!r}: Format ZINS/MONATE, z. B. 6.9/84") from exc
    if months_i <= 0 or rate_f < 0:
        raise ValueError(f"Angebot {text!r}: Zins >= 0 und Laufzeit > 0 nötig")
    return rate_f, months_i


class KreditHandler(BaseHandler):
    """CLI-Oberfläche für credits-core."""

    @property
    def profile_name(self) -> str:
        return "kredit"

    @property
    def target_file(self) -> Path:
        return self.base_path / "data"

    def get_operations(self) -> dict:
        return {
            "import": "Kredite aus umschuldung-state/1 übernehmen",
            "list": "Alle Kredite anzeigen",
            "ueberblick": "Raten, Ablösebetrag, offene Zahlungen",
            "vergleich": "Mit Umschuldungsangeboten vergleichen (--angebot ZINS/MONATE)",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        try:
            cc = load_credits_core_module()
        except ImportError:
            return False, "[ERROR] Ocean-Modul credits-core ist nicht installiert."
        store = cc.CreditStore(str(self._canonical_db))
        try:
            if operation == "import":
                return self._import(store, args, dry_run)
            if operation == "list":
                return self._list(store)
            if operation == "ueberblick":
                return self._overview(cc, store)
            if operation == "vergleich":
                return self._compare(cc, store, args)
        except (AlltagImportError, ValueError) as exc:
            return False, f"[ERROR] {exc}"
        except Exception as exc:  # sqlite3.OperationalError: Tabelle fehlt
            if "no such table" in str(exc):
                return False, "[ERROR] Tabelle credit_contracts fehlt: bach update migrations run --only 055_credit_contracts.sql"
            raise
        ops = "\n".join(f"  bach kredit {k:<11} {v}" for k, v in self.get_operations().items())
        return operation == "help", f"=== KREDITE ===\n{ops}"

    def _import(self, store, args, dry_run):
        if not args:
            return False, "Usage: bach kredit import <umschuldung-state.json> [--dry-run]"
        payload = load_payload(Path(args[0]), STATE_SCHEMA)
        counts = store.upsert_many(records_from_state(payload), dry_run=dry_run)
        prefix = "[DRY-RUN]" if dry_run else "[OK]"
        return True, f"{prefix} Kredit-Import: {counts['created']} neu, {counts['updated']} aktualisiert."

    def _list(self, store):
        rows = store.list()
        if not rows:
            return True, "Keine Kredite gespeichert."
        state = {1: "aktiv", 0: "erledigt", None: "unklar"}
        lines = [f"{'ID':>3}  {'Gläubiger':<28} {'Status':<9} {'Rate':>14}  Restschuld"]
        for r in rows:
            rest = "-" if r["remaining_min"] is None else _span(r["remaining_min"], r["remaining_max"])
            lines.append(f"{r['id']:>3}  {str(r['creditor'])[:28]:<28} {state[r['active']]:<9} "
                         f"{_eur(r['monthly_payment']):>14}  {rest} ({r['remaining_basis']})")
        return True, "\n".join(lines)

    def _overview(self, cc, store):
        o = cc.overview(store.list())
        lines = [
            "=== KREDIT-ÜBERBLICK ===",
            f"Kredite: {o['count_total']} (aktiv {o['count_active']}, unklar {o['count_unclear']}, "
            f"erledigt {o['count_closed']})",
            f"Bekannte Monatsraten (aktiv): {_eur(o['monthly_known'])}",
            f"Berechenbar: {o['count_computable']} von {o['count_active']} aktiven",
            f"Ablösebetrag heute: {_span(o['payoff_low'], o['payoff_high'])}",
            f"Offene Zahlungen:   {_span(o['payments_low'], o['payments_high'])}",
        ]
        for e in o["credits"]:
            if not e["computable"]:
                lines.append(f"  - {e['creditor']}: nicht berechenbar ({e['reason']})")
        return True, "\n".join(lines)

    def _compare(self, cc, store, args):
        offers, extra, ids, unclear = [], 0.0, None, False
        it = iter(args)
        for a in it:
            if a == "--angebot":
                offers.append(_parse_offer(next(it, "")))
            elif a == "--kosten":
                extra = float(next(it, "0").replace(",", "."))
            elif a == "--ids":
                ids = {int(x) for x in next(it, "").split(",") if x.strip()}
            elif a == "--mit-unklaren":
                unclear = True
            else:
                raise ValueError(f"Unbekannte Option {a!r}")
        if not offers:
            raise ValueError("Mindestens ein --angebot ZINS/MONATE angeben, z. B. --angebot 6.9/84")
        c = cc.compare(store.list(), offers, extra_costs=extra, include_unclear=unclear, ids=ids)
        lines = [
            "=== UMSCHULDUNG: VERGLEICH ===",
            f"Abgelöst würden {c['count_refinanced']} Kredite, Monatsraten bisher {_eur(c['old_monthly'])}",
            f"Ablösebetrag inkl. Kosten: {_span(c['amount_low'], c['amount_high'])}",
            f"Offene Zahlungen bisher:   {_span(c['old_payments_low'], c['old_payments_high'])}",
        ]
        for o in c["offers"]:
            lines.append(
                f"Angebot {o['eff_pct']:.2f} % eff. / {o['months']} Monate: Rate "
                f"{_span(o['new_monthly_low'], o['new_monthly_high'])}, gesamt "
                f"{_span(o['new_payments_low'], o['new_payments_high'])}, Ersparnis "
                f"{_span(o['savings_low'], o['savings_high'])}"
            )
        for e in c["skipped"]:
            lines.append(f"  - nicht einbezogen: {e['creditor']} ({e['reason']})")
        return True, "\n".join(lines)
