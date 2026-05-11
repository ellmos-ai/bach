#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
HaushaltHandler - Haushaltsmanagement CLI

Operationen:
  status            Haushalts-Dashboard (Zusammenfassung)
  routines          Alle Routinen (delegiert an RoutineHandler)
  due               Faellige Aufgaben (Routinen + Termine)
  today             Was steht heute an?
  week              Wochenplan
  shopping          Einkaufsliste anzeigen/verwalten
  inventory         Vorratsbestand mit Ampel
  add-item          Artikel zum Inventar hinzufuegen
  stock-in          Wareneingang buchen
  stock-out         Verbrauch buchen
  pull-check        Einkaufs-Pull-Liste (Was muss gekauft werden?)
  ampel             Ampel-Uebersicht aller Artikel
  order             Order fuer Artikel anlegen
  supplier          Lieferanten anzeigen
  add-supplier      Lieferant hinzufuegen
  costs             Monatliche Fixkosten-Uebersicht
  kosten-monat      Erwartete irregulare Kosten pro Monat
  add-kosten        Irregulare Kosten hinzufuegen
  help              Hilfe anzeigen

Nutzt: bach.db / household_routines, household_inventory, household_orders,
       household_suppliers, household_stock_transactions,
       assistant_calendar, fin_contracts (Unified DB seit v1.1.84)
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from hub.base import BaseHandler
from hub.lang import t


class HaushaltHandler(BaseHandler):

    WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.user_db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "haushalt"

    @property
    def target_file(self) -> Path:
        return self.user_db_path

    def get_operations(self) -> dict:
        return {
            "status": "Haushalts-Dashboard",
            "due": "Faellige Aufgaben",
            "today": "Was steht heute an?",
            "week": "Wochenplan",
            "costs": "Fixkosten-Uebersicht",
            "kosten-monat": "Irregulare Kosten pro Monat",
            "add-kosten": "Irregulare Kosten hinzufuegen",
            "kosten-list": "Alle irregularen Kosten",
            "insurance-check": "Versicherungs-Portfolio analysieren",
            "shopping": "Einkaufsliste",
            "add-shopping": "Einkaufsartikel hinzufuegen",
            "done-shopping": "Einkaufsartikel als erledigt markieren",
            "inventory": "Vorratsbestand mit Ampel",
            "add-item": "Artikel zum Inventar hinzufuegen",
            "stock-in": "Wareneingang buchen",
            "stock-out": "Verbrauch buchen",
            "pull-check": "Einkaufs-Pull-Liste",
            "ampel": "Ampel-Uebersicht",
            "order": "Order anlegen",
            "supplier": "Lieferanten anzeigen",
            "add-supplier": "Lieferant hinzufuegen",
            "export-routine": "Tagesplan als formatierten Text exportieren",
            "help": "Hilfe",
        }

    def _get_db(self):
        conn = sqlite3.connect(str(self.user_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        op = operation.lower().replace("_", "-")
        if op == "status":
            return self._status(args)
        elif op == "due":
            return self._due(args)
        elif op == "today":
            return self._today(args)
        elif op == "week":
            return self._week(args)
        elif op == "costs":
            return self._costs(args)
        elif op == "kosten-monat":
            return self._kosten_monat(args)
        elif op == "add-kosten":
            return self._add_kosten(args)
        elif op == "kosten-list":
            return self._kosten_list(args)
        elif op == "insurance-check":
            return self._insurance_check(args)
        elif op == "shopping":
            return self._shopping(args)
        elif op == "add-shopping":
            return self._add_shopping(args)
        elif op == "done-shopping":
            return self._done_shopping(args)
        elif op == "inventory":
            return self._inventory(args)
        elif op == "add-item":
            return self._add_item(args)
        elif op == "stock-in":
            return self._stock_in(args)
        elif op == "stock-out":
            return self._stock_out(args)
        elif op == "pull-check":
            return self._pull_check(args)
        elif op == "ampel":
            return self._ampel(args)
        elif op == "order":
            return self._order(args)
        elif op == "supplier":
            return self._supplier(args)
        elif op == "add-supplier":
            return self._add_supplier(args)
        elif op == "export-routine":
            return self._export_routine(args)
        elif op in ("", "help"):
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach haushalt help"

    # ------------------------------------------------------------------
    # STATUS - Dashboard
    # ------------------------------------------------------------------
    def _status(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            now = datetime.now()
            now_str = now.strftime("%Y-%m-%d")
            week_str = (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

            # Routinen-Stats
            total_routines = conn.execute("SELECT COUNT(*) FROM household_routines WHERE is_active = 1").fetchone()[0]
            overdue = conn.execute("""
                SELECT COUNT(*) FROM household_routines
                WHERE is_active = 1 AND next_due <= ?
            """, (now_str + " 23:59:59",)).fetchone()[0]
            due_week = conn.execute("""
                SELECT COUNT(*) FROM household_routines
                WHERE is_active = 1 AND next_due <= ?
            """, (week_str,)).fetchone()[0]

            # Fixkosten
            try:
                monthly_costs = conn.execute("""
                    SELECT SUM(
                        CASE
                            WHEN intervall = 'monatlich' THEN betrag
                            WHEN intervall = 'jaehrlich' THEN betrag / 12.0
                            WHEN intervall = 'quartalsweise' THEN betrag / 3.0
                            ELSE betrag
                        END
                    ) as monthly
                    FROM fin_contracts WHERE kuendigungs_status = 'aktiv'
                """).fetchone()["monthly"] or 0
            except Exception:
                monthly_costs = 0

            try:
                insurance_monthly = conn.execute("""
                    SELECT SUM(
                        CASE
                            WHEN zahlweise = 'monatlich' THEN beitrag
                            WHEN zahlweise = 'jaehrlich' THEN beitrag / 12.0
                            WHEN zahlweise = 'quartalsweise' THEN beitrag / 3.0
                            ELSE beitrag
                        END
                    ) as monthly
                    FROM fin_insurances WHERE status = 'aktiv'
                """).fetchone()["monthly"] or 0
            except Exception:
                insurance_monthly = 0

            # Shopping list
            try:
                shopping_count = conn.execute("SELECT COUNT(*) FROM household_shopping WHERE is_done = 0").fetchone()[0]
            except Exception:
                shopping_count = 0

            # Top 5 ueberfaellige Routinen
            overdue_items = conn.execute("""
                SELECT name, next_due, category FROM household_routines
                WHERE is_active = 1 AND next_due <= ?
                ORDER BY next_due ASC LIMIT 5
            """, (now_str + " 23:59:59",)).fetchall()

            # Inventar-Ampel
            try:
                from hub._services.household.inventory_engine import InventoryEngine, AMPEL_ROT, AMPEL_GELB, AMPEL_GRUEN
                engine = InventoryEngine(self.user_db_path)
                overview = engine.get_ampel_overview()
                inv_total = len(overview)
                inv_rot = sum(1 for x in overview if x["ampel"] == AMPEL_ROT)
                inv_gelb = sum(1 for x in overview if x["ampel"] == AMPEL_GELB)
                inv_gruen = sum(1 for x in overview if x["ampel"] == AMPEL_GRUEN)
            except Exception:
                inv_total = inv_rot = inv_gelb = inv_gruen = 0

            lines = [
                "=== HAUSHALTS-DASHBOARD ===",
                "",
                f"  Routinen aktiv:    {total_routines}",
                f"  Heute faellig:     {overdue}",
                f"  Diese Woche:       {due_week}",
                f"  Einkaufsliste:     {shopping_count} Artikel",
                "",
            ]

            if inv_total > 0:
                lines.append(f"  VORRAT ({inv_total} Artikel):")
                lines.append(f"    ROT: {inv_rot}  GELB: {inv_gelb}  GRUEN: {inv_gruen}")
                if inv_rot > 0:
                    lines.append(f"    -> bach haushalt pull-check")
                lines.append("")

            lines.extend([
                f"  FIXKOSTEN/MONAT:",
                f"    Vertraege:       {monthly_costs:,.2f} EUR",
                f"    Versicherungen:  {insurance_monthly:,.2f} EUR",
                f"    GESAMT:          {monthly_costs + insurance_monthly:,.2f} EUR",
                "",
            ])

            if overdue_items:
                lines.append("  UEBERFAELLIGE ROUTINEN:")
                for r in overdue_items:
                    due = (r["next_due"] or "---")[:10]
                    lines.append(f"    - {r['name']:<30} (faellig: {due}, {r['category']})")
                lines.append("")

            lines.append("  Befehle: bach haushalt due | today | week | costs | shopping")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DUE - Faellige Aufgaben
    # ------------------------------------------------------------------
    def _due(self, args: List[str]) -> Tuple[bool, str]:
        days = 7
        for a in args:
            try:
                days = int(a)
                break
            except ValueError:
                pass

        conn = self._get_db()
        try:
            cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            now_str = datetime.now().strftime("%Y-%m-%d")

            routines = conn.execute("""
                SELECT id, name, category, next_due FROM household_routines
                WHERE is_active = 1 AND next_due <= ?
                ORDER BY next_due ASC
            """, (cutoff,)).fetchall()

            if not routines:
                return True, f"[HAUSHALT] Keine faelligen Aufgaben in den naechsten {days} Tagen."

            overdue = [r for r in routines if (r["next_due"] or "")[:10] <= now_str]
            upcoming = [r for r in routines if (r["next_due"] or "")[:10] > now_str]

            lines = [f"[HAUSHALT] Faellige Aufgaben ({days} Tage): {len(routines)}\n"]

            if overdue:
                lines.append(f"  *** UEBERFAELLIG ({len(overdue)}) ***")
                for r in overdue:
                    due = (r["next_due"] or "---")[:10]
                    lines.append(f"    [{r['id']:>3}] {r['name']:<30} faellig: {due}  ({r['category']})")
                lines.append("")

            if upcoming:
                lines.append(f"  Demnächst ({len(upcoming)}):")
                for r in upcoming:
                    due = (r["next_due"] or "---")[:10]
                    lines.append(f"    [{r['id']:>3}] {r['name']:<30} faellig: {due}  ({r['category']})")

            lines.append(f"\n  Erledigen: bach routine done <id> [id2 id3...]")
            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # TODAY - Was steht heute an?
    # ------------------------------------------------------------------
    def _today(self, args: List[str]) -> Tuple[bool, str]:
        try:
            from hub._services.dashboard.daily_overview import DailyOverview
            svc = DailyOverview(self.user_db_path)
            return True, svc.format_today()
        except Exception as e:
            return False, f"Fehler beim Laden der Tagesuebersicht: {e}"

    # ------------------------------------------------------------------
    # WEEK - Wochenplan
    # ------------------------------------------------------------------
    def _week(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            now = datetime.now()
            # Start ab Montag dieser Woche
            monday = now - timedelta(days=now.weekday())
            sunday = monday + timedelta(days=6)

            lines = [f"=== WOCHENPLAN {monday.strftime('%d.%m.')} - {sunday.strftime('%d.%m.%Y')} ===\n"]

            for i in range(7):
                day = monday + timedelta(days=i)
                day_str = day.strftime("%Y-%m-%d")
                weekday = self.WEEKDAYS_DE[day.weekday()]
                is_today = day.date() == now.date()
                marker = " <<< HEUTE" if is_today else ""

                # Routinen fuer diesen Tag
                routines = conn.execute("""
                    SELECT id, name, category FROM household_routines
                    WHERE is_active = 1 AND date(next_due) = ?
                    ORDER BY category ASC
                """, (day_str,)).fetchall()

                # Ueberfallige Routinen am heutigen Tag anzeigen
                if is_today:
                    overdue = conn.execute("""
                        SELECT id, name, category FROM household_routines
                        WHERE is_active = 1 AND date(next_due) < ?
                        ORDER BY next_due ASC
                    """, (day_str,)).fetchall()
                else:
                    overdue = []

                # Termine
                cal_events = []
                try:
                    cal_events = conn.execute("""
                        SELECT title, event_time FROM assistant_calendar
                        WHERE date(event_date) = ? AND status != 'erledigt'
                        ORDER BY event_time ASC
                    """, (day_str,)).fetchall()
                except Exception:
                    pass

                has_items = routines or overdue or cal_events

                if has_items or is_today:
                    lines.append(f"  [{weekday} {day.strftime('%d.%m.')}] {'=' * 40}{marker}")

                    if overdue:
                        for r in overdue:
                            lines.append(f"    !!! [{r['id']:>3}] {r['name']} ({r['category']}) [UEBERFAELLIG]")

                    for r in routines:
                        lines.append(f"    [{r['id']:>3}] {r['name']} ({r['category']})")

                    for e in cal_events:
                        time = e["event_time"] or "--:--"
                        lines.append(f"    {time}  {e['title']}")

                    if not has_items:
                        lines.append("    (nichts geplant)")
                    lines.append("")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # COSTS - Fixkosten-Uebersicht
    # ------------------------------------------------------------------
    def _costs(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            lines = ["=== MONATLICHE FIXKOSTEN ===\n"]

            # Vertraege
            try:
                contracts = conn.execute("""
                    SELECT name, kategorie, betrag, intervall
                    FROM fin_contracts
                    WHERE kuendigungs_status = 'aktiv'
                    ORDER BY kategorie ASC, betrag DESC
                """).fetchall()

                if contracts:
                    lines.append("  VERTRAEGE / ABOS:")
                    total_contracts = 0
                    current_cat = None
                    for c in contracts:
                        cat = c["kategorie"] or "Sonstige"
                        if cat != current_cat:
                            current_cat = cat
                            lines.append(f"    [{cat}]")

                        intervall = c["intervall"] or "monatlich"
                        betrag = c["betrag"] or 0
                        if intervall == "jaehrlich":
                            monthly = betrag / 12.0
                        elif intervall == "quartalsweise":
                            monthly = betrag / 3.0
                        else:
                            monthly = betrag
                        total_contracts += monthly

                        lines.append(f"      {c['name']:<30} {monthly:>8.2f} EUR/Mo  ({betrag:.2f} {intervall})")

                    lines.append(f"    {'':->50}")
                    lines.append(f"    {'Summe Vertraege':<30} {total_contracts:>8.2f} EUR/Mo")
                    lines.append("")
            except Exception:
                total_contracts = 0

            # Versicherungen
            try:
                insurances = conn.execute("""
                    SELECT anbieter, sparte, beitrag, zahlweise
                    FROM fin_insurances
                    WHERE status = 'aktiv'
                    ORDER BY sparte ASC, beitrag DESC
                """).fetchall()

                if insurances:
                    lines.append("  VERSICHERUNGEN:")
                    total_insurance = 0
                    for ins in insurances:
                        zahlweise = ins["zahlweise"] or "jaehrlich"
                        beitrag = ins["beitrag"] or 0
                        if zahlweise == "jaehrlich":
                            monthly = beitrag / 12.0
                        elif zahlweise == "quartalsweise":
                            monthly = beitrag / 3.0
                        else:
                            monthly = beitrag
                        total_insurance += monthly

                        lines.append(f"      {ins['sparte']:<20} ({ins['anbieter']:<15}) {monthly:>8.2f} EUR/Mo  ({beitrag:.2f} {zahlweise})")

                    lines.append(f"    {'':->50}")
                    lines.append(f"    {'Summe Versicherungen':<30} {total_insurance:>8.2f} EUR/Mo")
                    lines.append("")
            except Exception:
                total_insurance = 0

            grand_total = total_contracts + total_insurance
            lines.append(f"  {'=' * 50}")
            lines.append(f"  GESAMTE FIXKOSTEN:  {grand_total:>8.2f} EUR/Mo  ({grand_total * 12:>10.2f} EUR/Jahr)")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # KOSTEN-MONAT - Erwartete irregulare Kosten pro Monat
    # ------------------------------------------------------------------
    def _kosten_monat(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt erwartete irregulare Kosten fuer einen bestimmten Monat."""
        # Parse Monat aus args
        monat = None
        for arg in args:
            try:
                m = int(arg)
                if 1 <= m <= 12:
                    monat = m
                    break
            except ValueError:
                continue

        if not monat:
            monat = datetime.now().month

        monat_namen = ["", "Januar", "Februar", "Maerz", "April", "Mai", "Juni",
                       "Juli", "August", "September", "Oktober", "November", "Dezember"]

        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT * FROM irregular_costs
                WHERE expected_month = ? AND is_recurring = 1
                ORDER BY category ASC, expected_amount DESC
            """, (monat,)).fetchall()

            if not rows:
                return True, f"[KOSTEN] Keine erwarteten Kosten fuer {monat_namen[monat]}.\nNutze: bach haushalt add-kosten \"Name\" --monat {monat} --betrag 100"

            lines = [f"[KOSTEN] Erwartete Kosten fuer {monat_namen[monat]}:\n"]

            total = 0
            current_cat = None
            for r in rows:
                cat = r["category"] or "Sonstige"
                if cat != current_cat:
                    current_cat = cat
                    lines.append(f"  [{cat.upper()}]")

                betrag = r["expected_amount"] or 0
                total += betrag
                last_paid = f" (zuletzt: {r['last_paid_date'][:10]})" if r["last_paid_date"] else ""
                lines.append(f"    [{r['id']:>3}] {r['name']:<30} {betrag:>8.2f} EUR{last_paid}")

            lines.append("")
            lines.append(f"  {'=' * 50}")
            lines.append(f"  ERWARTETE SUMME: {total:>8.2f} EUR")

            return True, "\n".join(lines)
        finally:
            conn.close()

    def _add_kosten(self, args: List[str]) -> Tuple[bool, str]:
        """Fuegt eine irregulare Kostenposition hinzu."""
        if not args:
            return False, (
                "Usage: bach haushalt add-kosten \"Name\" [Optionen]\n\n"
                "Optionen:\n"
                "  --monat, -m     Erwarteter Monat (1-12)\n"
                "  --betrag, -b    Erwarteter Betrag in EUR\n"
                "  --kategorie,-k  Kategorie (Steuer, Versicherung, Mitgliedschaft, etc.)\n"
                "  --beschreibung  Beschreibung\n"
                "  --einmalig      Einmalige Kosten (nicht wiederkehrend)"
            )

        # Parse args
        name = None
        for a in args:
            if not a.startswith("-"):
                name = a
                break

        if not name:
            return False, "Kein Name angegeben."

        monat_str = self._get_arg(args, "--monat") or self._get_arg(args, "-m")
        betrag_str = self._get_arg(args, "--betrag") or self._get_arg(args, "-b")
        kategorie = self._get_arg(args, "--kategorie") or self._get_arg(args, "-k")
        beschreibung = self._get_arg(args, "--beschreibung")
        is_recurring = 0 if "--einmalig" in args else 1

        try:
            monat = int(monat_str) if monat_str else None
            if monat and not (1 <= monat <= 12):
                return False, f"Ungueltiger Monat: {monat}. Erwartet: 1-12"
        except ValueError:
            return False, f"Ungueltiger Monat: {monat_str}"

        try:
            betrag = float(betrag_str) if betrag_str else None
        except ValueError:
            return False, f"Ungueltiger Betrag: {betrag_str}"

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO irregular_costs
                (name, description, category, expected_month, expected_amount, is_recurring)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, beschreibung, kategorie, monat, betrag, is_recurring))
            conn.commit()

            monat_txt = f" im Monat {monat}" if monat else ""
            betrag_txt = f" ({betrag:.2f} EUR)" if betrag else ""
            return True, f"[OK] Kostenposition #{cursor.lastrowid}: {name}{betrag_txt}{monat_txt}"
        finally:
            conn.close()

    def _kosten_list(self, args: List[str]) -> Tuple[bool, str]:
        """Listet alle irregularen Kosten auf."""
        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT * FROM irregular_costs
                ORDER BY expected_month ASC NULLS LAST, category ASC, expected_amount DESC
            """).fetchall()

            if not rows:
                return True, "[KOSTEN] Keine irregularen Kosten erfasst.\nNutze: bach haushalt add-kosten \"Name\" --monat 3 --betrag 100 --kategorie Steuer"

            monat_namen = ["---", "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                           "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

            lines = [f"[KOSTEN] {len(rows)} Kostenposition(en):\n"]
            lines.append(f"  {'ID':>4} {'Name':<30} {'Kategorie':<15} {'Monat':<6} {'Betrag':>10} {'Typ'}")
            lines.append("  " + "-" * 80)

            total_yearly = 0
            for r in rows:
                monat = monat_namen[r["expected_month"]] if r["expected_month"] else "---"
                betrag = r["expected_amount"] or 0
                kategorie = (r["category"] or "---")[:15]
                typ = "wdhd" if r["is_recurring"] else "einm"
                if r["is_recurring"]:
                    total_yearly += betrag
                lines.append(f"  {r['id']:>4} {r['name']:<30} {kategorie:<15} {monat:<6} {betrag:>10.2f} {typ}")

            lines.append("")
            lines.append(f"  Jaehrliche wiederkehrende Summe: {total_yearly:.2f} EUR")

            return True, "\n".join(lines)
        finally:
            conn.close()

    def _get_arg(self, args: List[str], flag: str) -> Optional[str]:
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(flag + "="):
                return a[len(flag) + 1:]
        return None

    # ------------------------------------------------------------------
    # INSURANCE-CHECK - Versicherungs-Portfolio Analyse
    # ------------------------------------------------------------------
    def _insurance_check(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            insurances = conn.execute("""
                SELECT id, anbieter, tarif_name, sparte, beitrag, zahlweise,
                       status, steuer_relevant_typ
                FROM fin_insurances WHERE status = 'aktiv'
                ORDER BY sparte
            """).fetchall()

            if not insurances:
                return True, "[HAUSHALT] Keine aktiven Versicherungen gefunden."

            lines = [
                "=== VERSICHERUNGS-PORTFOLIO CHECK ===",
                "",
            ]

            # Kosten berechnen
            total_monthly = 0
            by_category = {}
            no_cost = []
            for ins in insurances:
                monthly = ins["beitrag"] or 0
                zw = ins["zahlweise"] or "monatlich"
                if zw == "jaehrlich":
                    monthly /= 12
                elif zw == "quartalsweise":
                    monthly /= 3
                total_monthly += monthly

                cat = ins["sparte"] or "Sonstige"
                by_category[cat] = by_category.get(cat, 0) + monthly

                if not ins["beitrag"] or ins["beitrag"] == 0:
                    no_cost.append(ins)

            lines.append(f"  Aktive Versicherungen: {len(insurances)}")
            lines.append(f"  Kosten monatlich:      {total_monthly:.2f} EUR")
            lines.append(f"  Kosten jaehrlich:      {total_monthly * 12:.2f} EUR")
            lines.append("")

            # Aufteilung
            lines.append("  AUFTEILUNG:")
            for cat, cost in sorted(by_category.items(), key=lambda x: -x[1]):
                pct = (cost / total_monthly * 100) if total_monthly > 0 else 0
                bar = "#" * int(pct / 5)
                lines.append(f"    {cat:<22} {cost:>8.2f} EUR/Mo  ({pct:>3.0f}%) {bar}")
            lines.append("")

            # Analyse
            warnings = []
            infos = []

            # 1. Fehlende Beitraege
            if no_cost:
                warnings.append(f"{len(no_cost)} Versicherungen ohne Beitragsdaten:")
                for i in no_cost:
                    warnings.append(f"  -> #{i['id']} {i['anbieter']} ({i['sparte']})")
                warnings.append("  Empfehlung: Beitraege nachtragen")

            # 2. Mehrfach-Versicherungen
            from collections import Counter
            sparten = [i["sparte"] for i in insurances]
            dups = {s: c for s, c in Counter(sparten).items() if c > 1}
            if dups:
                for s, c in dups.items():
                    items = [i for i in insurances if i["sparte"] == s]
                    total = sum((i["beitrag"] or 0) for i in items)
                    if s == "KFZ":
                        infos.append(f"{c}x {s}-Versicherungen ({total:.2f} EUR/Mo) - Mehrere Fahrzeuge?")
                    else:
                        warnings.append(f"{c}x {s}-Versicherungen - Duplikat pruefen!")

            # 3. Steuer-Check
            steuer_basis = 0
            steuer_sonst = 0
            for ins in insurances:
                yearly = (ins["beitrag"] or 0)
                zw = ins["zahlweise"] or "monatlich"
                if zw == "monatlich":
                    yearly *= 12
                elif zw == "quartalsweise":
                    yearly *= 4

                if ins["steuer_relevant_typ"] == "Basisvorsorge":
                    steuer_basis += yearly
                elif ins["steuer_relevant_typ"] == "Sonstige_Vorsorge":
                    steuer_sonst += yearly

            lines.append("  STEUERLICHE ABSETZBARKEIT:")
            lines.append(f"    Basisvorsorge:     {steuer_basis:>8.2f} EUR/Jahr (voll absetzbar)")
            lines.append(f"    Sonstige Vorsorge: {steuer_sonst:>8.2f} EUR/Jahr (max 1.900 EUR)")
            if steuer_sonst > 1900:
                diff = steuer_sonst - 1900
                warnings.append(f"Hoechstbetrag Sonstige Vorsorge um {diff:.2f} EUR ueberschritten")
                warnings.append(f"  -> {diff:.2f} EUR jaehrlich nicht absetzbar")
            lines.append("")

            # 4. Fehlende wichtige Versicherungen
            wichtige = {"Haftpflicht": "Privathaftpflicht schuetzt vor Schadenersatz",
                        "Hausrat": "Schuetzt Wohnungsinventar",
                        "PKV": "Krankenversicherung ist Pflicht"}
            vorhandene = {i["sparte"] for i in insurances}
            for v, desc in wichtige.items():
                if v not in vorhandene:
                    warnings.append(f"Fehlend: {v} - {desc}")

            # 5. Empfehlungen
            empfehlungen = []
            if total_monthly > 800:
                empfehlungen.append("Versicherungskosten hoch (>800 EUR/Mo) - Vergleich empfohlen")
            if "Rechtsschutz" in vorhandene and any(i["beitrag"] == 0 for i in insurances if i["sparte"] == "Rechtsschutz"):
                empfehlungen.append("Rechtsschutz: Beitrag unbekannt - ggf. nicht mehr aktiv?")
            if "Risiko-LV" not in vorhandene:
                empfehlungen.append("Risikolebensversicherung fehlt - sinnvoll bei Familie/Kredit")

            # Output
            if warnings:
                lines.append("  [!] WARNUNGEN:")
                for w in warnings:
                    lines.append(f"    ! {w}")
                lines.append("")

            if infos:
                lines.append("  [i] HINWEISE:")
                for i in infos:
                    lines.append(f"    i {i}")
                lines.append("")

            if empfehlungen:
                lines.append("  [*] EMPFEHLUNGEN:")
                for e in empfehlungen:
                    lines.append(f"    * {e}")
                lines.append("")

            # Score
            score = 10
            score -= len(warnings)
            score -= len(no_cost) * 0.5
            score = max(1, min(10, score))
            lines.append(f"  Portfolio-Score: {score:.0f}/10")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SHOPPING - Einkaufsliste
    # ------------------------------------------------------------------
    def _shopping(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            self._ensure_shopping_table(conn)

            show_done = "--all" in args
            query = "SELECT * FROM household_shopping"
            if not show_done:
                query += " WHERE is_done = 0"
            query += " ORDER BY category ASC, item_name ASC"

            rows = conn.execute(query).fetchall()

            if not rows:
                return True, "[HAUSHALT] Einkaufsliste ist leer.\nNutze: bach haushalt add-shopping \"Milch\" --cat Lebensmittel"

            lines = [f"[HAUSHALT] Einkaufsliste ({len(rows)} Artikel):\n"]
            current_cat = None

            for r in rows:
                cat = r["category"] or "Sonstige"
                if cat != current_cat:
                    current_cat = cat
                    lines.append(f"  [{cat}]")

                done = "[x]" if r["is_done"] else "[ ]"
                qty = f" ({r['quantity']})" if r["quantity"] else ""
                lines.append(f"    {done} [{r['id']:>3}] {r['item_name']}{qty}")

            lines.append(f"\n  Erledigt: bach haushalt done-shopping <id>")
            lines.append(f"  Hinzufuegen: bach haushalt add-shopping \"Artikel\" --cat Lebensmittel")
            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD-SHOPPING
    # ------------------------------------------------------------------
    def _add_shopping(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach haushalt add-shopping \"Artikel\" [Optionen]\n\n"
                "Optionen:\n"
                "  --cat, -c    Kategorie (Lebensmittel|Haushalt|Drogerie|Getraenke|Sonstige)\n"
                "  --qty, -q    Menge (z.B. 2, 500g, 1L)"
            )

        name = None
        for a in args:
            if not a.startswith("-"):
                name = a
                break

        if not name:
            return False, "Kein Artikelname angegeben."

        cat = self._get_arg(args, "--cat") or self._get_arg(args, "-c") or "Sonstige"
        qty = self._get_arg(args, "--qty") or self._get_arg(args, "-q")

        conn = self._get_db()
        try:
            self._ensure_shopping_table(conn)
            cursor = conn.execute("""
                INSERT INTO household_shopping (item_name, category, quantity)
                VALUES (?, ?, ?)
            """, (name, cat, qty))
            conn.commit()
            return True, f"[OK] Einkaufsartikel #{cursor.lastrowid}: {name} ({cat})"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # DONE-SHOPPING
    # ------------------------------------------------------------------
    def _done_shopping(self, args: List[str]) -> Tuple[bool, str]:
        ids, _ = self._parse_ids(args)
        if not ids:
            return False, "Usage: bach haushalt done-shopping <id> [id2...]"

        conn = self._get_db()
        try:
            self._ensure_shopping_table(conn)
            results = []
            for sid in ids:
                row = conn.execute("SELECT * FROM household_shopping WHERE id = ?", (sid,)).fetchone()
                if not row:
                    results.append(f"[WARN] Artikel {sid} nicht gefunden")
                    continue
                conn.execute("UPDATE household_shopping SET is_done = 1 WHERE id = ?", (sid,))
                results.append(f"[OK] {row['item_name']} erledigt")
            conn.commit()
            return True, "\n".join(results)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # HELP
    # ------------------------------------------------------------------
    def _help(self) -> Tuple[bool, str]:
        return True, """HAUSHALT - Haushaltsmanagement
=============================

UEBERSICHT:
  bach haushalt status             Dashboard (Zusammenfassung)
  bach haushalt today              Was steht heute an?
  bach haushalt week               Wochenplan (Routinen + Termine)
  bach haushalt due [tage]         Faellige Aufgaben (Standard: 7 Tage)

FIXKOSTEN:
  bach haushalt costs              Monatliche Fixkosten-Uebersicht
  bach haushalt kosten-monat [m]   Irregulare Kosten pro Monat
  bach haushalt add-kosten "Name" --monat 3 --betrag 100
  bach haushalt kosten-list        Alle irregularen Kosten
  bach haushalt insurance-check    Versicherungs-Portfolio analysieren

EINKAUFSLISTE:
  bach haushalt shopping           Einkaufsliste anzeigen
  bach haushalt add-shopping "Milch" --cat Lebensmittel --qty 2
  bach haushalt done-shopping <id> Einkaufsartikel als erledigt markieren

VORRATSMANAGEMENT (Pull-System):
  bach haushalt inventory          Vorratsbestand mit Ampel anzeigen
  bach haushalt add-item "Milch" --cat Lebensmittel --unit Liter --min 2
  bach haushalt stock-in <id> <menge> [--price 1.29] [--supplier 1]
  bach haushalt stock-out <id> <menge>
  bach haushalt pull-check         Automatische Einkaufs-Pull-Liste
  bach haushalt ampel              Ampel-Uebersicht (ROT/GELB/GRUEN)
  bach haushalt order <id> --type routine --qty 6 --cycle 14
  bach haushalt supplier           Lieferanten anzeigen
  bach haushalt add-supplier "REWE" --type supermarket

AMPEL-FARBEN:
  ROT   = Leer und Bedarf vorhanden (sofort kaufen!)
  GELB  = Weniger als 7 Tage Vorrat
  GRUEN = Genug auf Lager
  GRAU  = Kein Bedarf definiert

EXPORT:
  bach haushalt export-routine [--days N] [--out datei.md]
                                Tagesplan als formatierten Text exportieren"""

    # ------------------------------------------------------------------
    # EXPORT-ROUTINE - Tagesplan-Export (INT04)
    # ------------------------------------------------------------------
    def _export_routine(self, args: List[str]) -> Tuple[bool, str]:
        days_ahead = 1
        out_file = None
        i = 0
        while i < len(args):
            if args[i] == "--days" and i + 1 < len(args):
                days_ahead = int(args[i + 1])
                i += 2
            elif args[i] == "--out" and i + 1 < len(args):
                out_file = args[i + 1]
                i += 2
            else:
                try:
                    days_ahead = int(args[i])
                except ValueError:
                    pass
                i += 1

        conn = self._get_db()
        try:
            now = datetime.now()
            lines = []
            lines.append(f"# Tagesplan")
            lines.append(f"Erstellt: {now.strftime('%d.%m.%Y %H:%M')}")
            lines.append("")

            for d in range(days_ahead):
                day = now + timedelta(days=d)
                day_str = day.strftime("%Y-%m-%d")
                weekday = self.WEEKDAYS_DE[day.weekday()]

                lines.append(f"## {weekday} {day.strftime('%d.%m.%Y')}")
                lines.append("")

                # Routinen
                if d == 0:
                    # Heute: auch ueberfaellige
                    routines = conn.execute("""
                        SELECT id, name, category, next_due FROM household_routines
                        WHERE is_active = 1 AND next_due <= ?
                        ORDER BY category ASC, name ASC
                    """, (day_str + " 23:59:59",)).fetchall()
                else:
                    routines = conn.execute("""
                        SELECT id, name, category, next_due FROM household_routines
                        WHERE is_active = 1 AND date(next_due) = ?
                        ORDER BY category ASC, name ASC
                    """, (day_str,)).fetchall()

                if routines:
                    lines.append("### Routinen")
                    lines.append("")
                    current_cat = None
                    for r in routines:
                        cat = r["category"] or "Sonstige"
                        if cat != current_cat:
                            current_cat = cat
                            lines.append(f"**{cat}:**")
                        overdue = (r["next_due"] or "")[:10] < day_str
                        marker = " (UEBERFAELLIG)" if overdue else ""
                        lines.append(f"- [ ] {r['name']}{marker}")
                    lines.append("")

                # Termine
                try:
                    appointments = conn.execute("""
                        SELECT title, event_time, event_type FROM assistant_calendar
                        WHERE date(event_date) = ? AND status != 'erledigt'
                        ORDER BY event_time ASC
                    """, (day_str,)).fetchall()

                    if appointments:
                        lines.append("### Termine")
                        lines.append("")
                        for a in appointments:
                            time = a["event_time"] or "--:--"
                            lines.append(f"- {time} {a['title']}")
                        lines.append("")
                except Exception:
                    pass

                # Medikamente (nur am ersten Tag)
                if d == 0:
                    try:
                        meds = conn.execute("""
                            SELECT name, dosage, schedule FROM health_medications
                            WHERE status = 'aktiv' ORDER BY name
                        """).fetchall()
                        if meds:
                            lines.append("### Medikamente")
                            lines.append("")
                            for m in meds:
                                schedule = m["schedule"] or ""
                                lines.append(f"- [ ] {m['name']} {m['dosage'] or ''} {schedule}")
                            lines.append("")
                    except Exception:
                        pass

                lines.append("---")
                lines.append("")

            content = "\n".join(lines)

            if out_file:
                from pathlib import Path as P
                out_path = P(out_file)
                out_path.write_text(content, encoding="utf-8")
                return True, f"Tagesplan exportiert: {out_path} ({days_ahead} Tag(e))"

            return True, content
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # INVENTORY - Vorratsbestand mit Ampel
    # ------------------------------------------------------------------
    def _inventory(self, args: List[str]) -> Tuple[bool, str]:
        from hub._services.household.inventory_engine import InventoryEngine
        engine = InventoryEngine(self.user_db_path)
        overview = engine.get_ampel_overview()

        if not overview:
            return True, (
                "[HAUSHALT] Kein Inventar vorhanden.\n"
                "Nutze: bach haushalt add-item \"Milch\" --cat Lebensmittel --unit Liter --min 2"
            )

        # Optional: nach Kategorie filtern
        cat_filter = self._get_arg(args, "--cat") or self._get_arg(args, "-c")

        lines = [f"=== VORRATSBESTAND ({len(overview)} Artikel) ===\n"]
        current_cat = None

        for item in overview:
            if cat_filter and item["category"].lower() != cat_filter.lower():
                continue

            cat = item["category"] or "Sonstige"
            if cat != current_cat:
                current_cat = cat
                lines.append(f"  [{cat}]")

            ampel = item["ampel"]
            days = f"{item['days_left']:.0f}d" if item["days_left"] != float("inf") else "---"
            lines.append(
                f"    {ampel:<5} [{item['id']:>3}] {item['name']:<25} "
                f"{item['stock']:>6.1f} {item['unit']:<5} (Vorrat: {days})"
            )

        lines.append(f"\n  Befehle: bach haushalt pull-check | ampel | add-item | stock-in | stock-out")
        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # ADD-ITEM - Artikel anlegen
    # ------------------------------------------------------------------
    def _add_item(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach haushalt add-item \"Name\" [Optionen]\n\n"
                "Optionen:\n"
                "  --cat, -c       Kategorie (Lebensmittel, Hygiene, Medikamente, ...)\n"
                "  --unit, -u      Einheit (Stueck, Liter, kg, Packung, ...)\n"
                "  --min           Mindestbestand (Standard: 1)\n"
                "  --pack-size     Packungsgroesse (Standard: 1)\n"
                "  --priority      Prioritaet 1-3 (1=optional, 2=wichtig, 3=kritisch)\n"
                "  --location      Lagerort"
            )

        name = None
        for a in args:
            if not a.startswith("-"):
                name = a
                break
        if not name:
            return False, "Kein Name angegeben."

        cat = self._get_arg(args, "--cat") or self._get_arg(args, "-c") or "Sonstige"
        unit = self._get_arg(args, "--unit") or self._get_arg(args, "-u") or "Stueck"
        min_qty = self._get_arg(args, "--min")
        pack_size = self._get_arg(args, "--pack-size")
        priority = self._get_arg(args, "--priority")
        location = self._get_arg(args, "--location")

        try:
            min_qty = int(min_qty) if min_qty else 1
        except ValueError:
            return False, f"Ungueltiger Mindestbestand: {min_qty}"
        try:
            pack_size = float(pack_size) if pack_size else 1.0
        except ValueError:
            return False, f"Ungueltige Packungsgroesse: {pack_size}"
        try:
            priority = int(priority) if priority else 2
            if priority not in (1, 2, 3):
                return False, "Prioritaet muss 1, 2 oder 3 sein."
        except ValueError:
            return False, f"Ungueltige Prioritaet: {priority}"

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO household_inventory
                (name, category, unit, min_quantity, pack_size, priority, location, quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """, (name, cat, unit, min_qty, pack_size, priority, location))
            conn.commit()
            return True, f"[OK] Artikel #{cursor.lastrowid}: {name} ({cat}, {unit}, Prio {priority})"
        except sqlite3.IntegrityError as e:
            return False, f"Fehler: {e}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # STOCK-IN - Wareneingang
    # ------------------------------------------------------------------
    def _stock_in(self, args: List[str]) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, (
                "Usage: bach haushalt stock-in <artikel-id> <menge> [Optionen]\n\n"
                "Optionen:\n"
                "  --price    Preis pro Einheit\n"
                "  --supplier Lieferanten-ID"
            )

        try:
            article_id = int(args[0])
            amount = float(args[1])
        except (ValueError, IndexError):
            return False, "Usage: bach haushalt stock-in <id> <menge>"

        if amount <= 0:
            return False, "Menge muss positiv sein."

        price = self._get_arg(args, "--price")
        supplier_id = self._get_arg(args, "--supplier")
        try:
            price = float(price) if price else None
        except ValueError:
            return False, f"Ungueltiger Preis: {price}"
        try:
            supplier_id = int(supplier_id) if supplier_id else None
        except ValueError:
            return False, f"Ungueltige Lieferanten-ID: {supplier_id}"

        from hub._services.household.inventory_engine import InventoryEngine
        engine = InventoryEngine(self.user_db_path)
        try:
            result = engine.stock_in(article_id, amount, supplier_id=supplier_id, price=price)
            return True, (
                f"[OK] Eingang: {result['name']}\n"
                f"  {result['before']:.1f} + {result['amount']:.1f} = {result['after']:.1f}"
            )
        except ValueError as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # STOCK-OUT - Verbrauch
    # ------------------------------------------------------------------
    def _stock_out(self, args: List[str]) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, "Usage: bach haushalt stock-out <artikel-id> <menge>"

        try:
            article_id = int(args[0])
            amount = float(args[1])
        except (ValueError, IndexError):
            return False, "Usage: bach haushalt stock-out <id> <menge>"

        if amount <= 0:
            return False, "Menge muss positiv sein."

        from hub._services.household.inventory_engine import InventoryEngine
        engine = InventoryEngine(self.user_db_path)
        try:
            result = engine.stock_out(article_id, amount)
            return True, (
                f"[OK] Verbrauch: {result['name']}\n"
                f"  {result['before']:.1f} - {result['amount']:.1f} = {result['after']:.1f}"
            )
        except ValueError as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # PULL-CHECK - Einkaufs-Pull-Liste
    # ------------------------------------------------------------------
    def _pull_check(self, args: List[str]) -> Tuple[bool, str]:
        days = 30
        for a in args:
            try:
                days = int(a)
                break
            except ValueError:
                pass

        from hub._services.household.inventory_engine import InventoryEngine
        engine = InventoryEngine(self.user_db_path)
        pull_list = engine.generate_pull_list(days_ahead=days)

        if not pull_list:
            return True, f"[HAUSHALT] Kein Einkaufsbedarf (naechste {days} Tage). Alles auf Lager!"

        lines = [f"=== EINKAUFS-PULL-LISTE ({days} Tage) ===\n"]
        lines.append(f"  {'Artikel':<25} {'Fehlmenge':>10} {'Packungen':>10} {'Dringlichkeit':>13}")
        lines.append("  " + "-" * 62)

        total_packs = 0
        for item in pull_list:
            total_packs += item["packs_needed"]
            lines.append(
                f"  {item['name']:<25} "
                f"{item['missing']:>8.1f} {item['unit']:<1} "
                f"{item['packs_needed']:>8}x     "
                f"D={item['urgency']:>5.1f}"
            )

        lines.append("")
        lines.append(f"  {len(pull_list)} Artikel, {total_packs} Packungen gesamt")
        lines.append(f"\n  Eingang buchen: bach haushalt stock-in <id> <menge>")
        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # AMPEL - Uebersicht
    # ------------------------------------------------------------------
    def _ampel(self, args: List[str]) -> Tuple[bool, str]:
        from hub._services.household.inventory_engine import InventoryEngine
        engine = InventoryEngine(self.user_db_path)
        overview = engine.get_ampel_overview()

        if not overview:
            return True, "[HAUSHALT] Kein Inventar vorhanden."

        rot = [x for x in overview if x["ampel"] == "ROT"]
        gelb = [x for x in overview if x["ampel"] == "GELB"]
        gruen = [x for x in overview if x["ampel"] == "GRUEN"]
        grau = [x for x in overview if x["ampel"] == "GRAU"]

        lines = [f"=== AMPEL-UEBERSICHT ({len(overview)} Artikel) ===\n"]

        if rot:
            lines.append(f"  ROT — Sofort kaufen! ({len(rot)})")
            for item in rot:
                lines.append(f"    [{item['id']:>3}] {item['name']:<25} Bestand: {item['stock']:.1f} {item['unit']}")
            lines.append("")

        if gelb:
            lines.append(f"  GELB — Bald aufbrauchen ({len(gelb)})")
            for item in gelb:
                days = f"{item['days_left']:.0f} Tage" if item["days_left"] != float("inf") else "---"
                lines.append(f"    [{item['id']:>3}] {item['name']:<25} Vorrat: {days}")
            lines.append("")

        if gruen:
            lines.append(f"  GRUEN — OK ({len(gruen)})")
            for item in gruen:
                days = f"{item['days_left']:.0f} Tage" if item["days_left"] != float("inf") else "---"
                lines.append(f"    [{item['id']:>3}] {item['name']:<25} Vorrat: {days}")
            lines.append("")

        if grau:
            lines.append(f"  GRAU — Kein Bedarf definiert ({len(grau)})")
            for item in grau:
                lines.append(f"    [{item['id']:>3}] {item['name']:<25} Bestand: {item['stock']:.1f} {item['unit']}")

        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # ORDER - Order anlegen
    # ------------------------------------------------------------------
    def _order(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach haushalt order <artikel-id> [Optionen]\n\n"
                "Optionen:\n"
                "  --type      Order-Typ: routine|period|oneshot|project (Standard: routine)\n"
                "  --qty       Menge pro Zyklus/Zeitraum\n"
                "  --cycle     Intervall in Tagen (fuer routine)\n"
                "  --start     Startdatum YYYY-MM-DD (fuer period/project)\n"
                "  --end       Enddatum YYYY-MM-DD (fuer period/project)\n"
                "  --target    Zieldatum YYYY-MM-DD (fuer oneshot)\n"
                "  --reason    Grund/Beschreibung\n"
                "  --priority  1-3 (1=optional, 2=wichtig, 3=kritisch)"
            )

        try:
            article_id = int(args[0])
        except ValueError:
            return False, f"Ungueltige Artikel-ID: {args[0]}"

        order_type = self._get_arg(args, "--type") or "routine"
        if order_type not in ("routine", "period", "oneshot", "project"):
            return False, f"Ungueltiger Order-Typ: {order_type}. Erlaubt: routine|period|oneshot|project"

        qty_str = self._get_arg(args, "--qty")
        if not qty_str:
            return False, "Menge erforderlich: --qty <zahl>"
        try:
            qty = float(qty_str)
        except ValueError:
            return False, f"Ungueltige Menge: {qty_str}"

        cycle_str = self._get_arg(args, "--cycle")
        start = self._get_arg(args, "--start")
        end = self._get_arg(args, "--end")
        target = self._get_arg(args, "--target")
        reason = self._get_arg(args, "--reason")
        prio_str = self._get_arg(args, "--priority")

        try:
            cycle = int(cycle_str) if cycle_str else None
        except ValueError:
            return False, f"Ungueltiges Intervall: {cycle_str}"
        try:
            priority = int(prio_str) if prio_str else 2
        except ValueError:
            return False, f"Ungueltige Prioritaet: {prio_str}"

        if order_type == "routine" and not cycle:
            return False, "Routine braucht --cycle <tage>"

        conn = self._get_db()
        try:
            # Artikel pruefen
            art = conn.execute("SELECT name FROM household_inventory WHERE id = ?", (article_id,)).fetchone()
            if not art:
                return False, f"Artikel {article_id} nicht gefunden."

            cursor = conn.execute("""
                INSERT INTO household_orders
                (article_id, order_type, quantity_value, cycle_interval_days,
                 start_date, end_date, target_date, reason, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (article_id, order_type, qty, cycle, start, end, target, reason, priority))
            conn.commit()

            type_label = {"routine": "Routine", "period": "Zeitraum",
                          "oneshot": "Einmalig", "project": "Projekt"}.get(order_type, order_type)
            extra = f", alle {cycle} Tage" if cycle else ""
            return True, f"[OK] Order #{cursor.lastrowid}: {type_label} fuer {art['name']} ({qty} Einheiten{extra})"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SUPPLIER - Lieferanten anzeigen
    # ------------------------------------------------------------------
    def _supplier(self, args: List[str]) -> Tuple[bool, str]:
        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT id, name, supplier_type, address, phone, website
                FROM household_suppliers WHERE archived = 0
                ORDER BY name
            """).fetchall()

            if not rows:
                return True, (
                    "[HAUSHALT] Keine Lieferanten erfasst.\n"
                    "Nutze: bach haushalt add-supplier \"REWE\" --type supermarket"
                )

            lines = [f"=== LIEFERANTEN ({len(rows)}) ===\n"]
            for r in rows:
                typ = r["supplier_type"] or "other"
                addr = f" | {r['address']}" if r["address"] else ""
                lines.append(f"  [{r['id']:>3}] {r['name']:<25} ({typ}){addr}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ADD-SUPPLIER - Lieferant anlegen
    # ------------------------------------------------------------------
    def _add_supplier(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage: bach haushalt add-supplier \"Name\" [Optionen]\n\n"
                "Optionen:\n"
                "  --type      Typ: supermarket|drugstore|online|other\n"
                "  --address   Adresse\n"
                "  --phone     Telefon\n"
                "  --website   Website"
            )

        name = None
        for a in args:
            if not a.startswith("-"):
                name = a
                break
        if not name:
            return False, "Kein Name angegeben."

        supplier_type = self._get_arg(args, "--type") or "other"
        address = self._get_arg(args, "--address")
        phone = self._get_arg(args, "--phone")
        website = self._get_arg(args, "--website")

        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO household_suppliers (name, supplier_type, address, phone, website)
                VALUES (?, ?, ?, ?, ?)
            """, (name, supplier_type, address, phone, website))
            conn.commit()
            return True, f"[OK] Lieferant #{cursor.lastrowid}: {name} ({supplier_type})"
        except sqlite3.IntegrityError:
            return False, f"Lieferant '{name}' existiert bereits."
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------
    def _ensure_shopping_table(self, conn):
        """Erstellt household_shopping Tabelle falls nicht vorhanden."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS household_shopping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                category TEXT DEFAULT 'Sonstige',
                quantity TEXT,
                is_done INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _parse_ids(self, args: List[str]) -> Tuple[List[int], List[str]]:
        ids = []
        rest = []
        for arg in args:
            try:
                ids.append(int(arg))
            except ValueError:
                rest.append(arg)
        return ids, rest

    def _get_arg(self, args: List[str], flag: str) -> Optional[str]:
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(flag + "="):
                return a[len(flag) + 1:]
        return None
