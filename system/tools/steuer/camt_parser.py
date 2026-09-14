# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Sicherer ISO-20022-CAMT.053-Parser für BACH.

Abgeleitet aus dem MIT-lizenzierten RechnungsSteller-CAMT-Parser des
BACH-Autors; der Parser liegt bewusst im öffentlichen Steuer-Werkzeugbaum und
nicht im gitignorierten privaten Expertenbaum.
"""

from pathlib import Path
from typing import Dict, List

from defusedxml import ElementTree as DET


class CamtParser:
    """Parst CAMT.053-Kontoauszüge ohne DTD-/Entity-Auflösung."""

    def __init__(self, filepath: Path):
        self.filepath = Path(filepath)
        self.ns = {"n": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"}

    def parse(self) -> List[Dict]:
        tree = DET.parse(str(self.filepath))
        root = tree.getroot()
        if "}" in root.tag:
            self.ns["n"] = root.tag.split("}", 1)[0].strip("{")

        statements = root.findall("./n:BkToCstmrStmt/n:Stmt", self.ns)
        if not statements:
            statements = root.findall(".//n:Stmt", self.ns)

        transactions: List[Dict] = []
        for statement in statements:
            iban_node = statement.find("./n:Acct/n:Id/n:IBAN", self.ns)
            iban = iban_node.text or "" if iban_node is not None else ""
            for entry in statement.findall("./n:Ntry", self.ns):
                transaction = self._parse_entry(entry, iban)
                if transaction:
                    transactions.append(transaction)
        return transactions

    def parse_balances(self) -> List[Dict]:
        """Abschluss-Salden (CLBD) pro Statement, in der Form, die
        ``accounts_core.AccountStore.persist_camt_balances`` erwartet:
        ``[{"iban": ..., "balance": <float>, "currency": ..., "date": "YYYY-MM-DD"}, ...]``.

        Welle 3 (Task 1220): Der D-013-Saldenfix (9ff3df2) existierte nur in der
        gitignorierten Betriebsinstallation; der oeffentliche Baum hatte die
        Methode nie, und ``hub/steuer.py`` degradierte lautlos zu "keine Salden".
        Nur CLBD (Closing Booked) zaehlt -- OPBD (Oeffnungssaldo) oder
        Zwischensalden absichtlich nicht, damit kein falscher Kontostand beim
        Konsumenten landet. Ohne IBAN: ``"UNKNOWN"`` (der Konsument
        ueberspringt mit Warnung). DBIT-Salden (Disposition) werden negiert.
        """
        tree = DET.parse(str(self.filepath))
        root = tree.getroot()
        if "}" in root.tag:
            self.ns["n"] = root.tag.split("}", 1)[0].strip("{")

        statements = root.findall("./n:BkToCstmrStmt/n:Stmt", self.ns)
        if not statements:
            statements = root.findall(".//n:Stmt", self.ns)

        balances: List[Dict] = []
        for statement in statements:
            balance_node = self._closing_balance_node(statement)
            if balance_node is None:
                continue
            amount_node = balance_node.find("./n:Amt", self.ns)
            if amount_node is None or amount_node.text is None:
                continue
            try:
                amount = float(amount_node.text)
            except ValueError:
                continue

            indicator_node = balance_node.find("./n:CdtDbtInd", self.ns)
            indicator = indicator_node.text or "" if indicator_node is not None else ""
            if indicator == "DBIT":
                amount = -amount

            iban_node = statement.find("./n:Acct/n:Id/n:IBAN", self.ns)
            iban = "UNKNOWN"
            if iban_node is not None and iban_node.text:
                iban = iban_node.text.strip()

            balances.append({
                "iban": iban,
                "balance": amount,
                "currency": amount_node.get("Ccy") or "EUR",
                "date": self._balance_date(balance_node),
            })
        return balances

    def _closing_balance_node(self, statement):
        """Letztes CLBD-Bal-Element des Statements oder None."""
        closing_nodes = [
            node for node in statement.findall("./n:Bal", self.ns)
            if (code := node.find("./n:Tp/n:CdOrPrtry/n:Cd", self.ns)) is not None
            and code.text == "CLBD"
        ]
        return closing_nodes[-1] if closing_nodes else None

    def _balance_date(self, balance_node) -> str:
        """ISO-Datum des Saldens: Bal/Dt/Dt oder Bal/Dt/DtTm (Datumsteil)."""
        date_node = balance_node.find("./n:Dt/n:Dt", self.ns)
        if date_node is not None and date_node.text:
            return date_node.text
        datetime_node = balance_node.find("./n:Dt/n:DtTm", self.ns)
        if datetime_node is not None and datetime_node.text:
            return datetime_node.text[:10]
        return ""

    def _parse_entry(self, entry, iban: str) -> Dict:
        amount_node = entry.find("./n:Amt", self.ns)
        if amount_node is None or amount_node.text is None:
            return {}

        indicator_node = entry.find("./n:CdtDbtInd", self.ns)
        indicator = indicator_node.text or "" if indicator_node is not None else ""
        date_node = entry.find("./n:BookgDt/n:Dt", self.ns)
        if date_node is None:
            date_node = entry.find("./n:ValDt/n:Dt", self.ns)

        partner = ""
        purpose_parts: List[str] = []
        partner_iban = ""
        for details in entry.findall("./n:NtryDtls/n:TxDtls", self.ns):
            if indicator == "CRDT":
                partner_node = details.find("./n:RltdPties/n:Dbtr/n:Nm", self.ns)
                if partner_node is None:
                    partner_node = details.find(
                        "./n:RltdPties/n:UltmtDbtr/n:Nm", self.ns
                    )
                iban_node = details.find(
                    "./n:RltdPties/n:DbtrAcct/n:Id/n:IBAN", self.ns
                )
            else:
                partner_node = details.find("./n:RltdPties/n:Cdtr/n:Nm", self.ns)
                if partner_node is None:
                    partner_node = details.find(
                        "./n:RltdPties/n:UltmtCdtr/n:Nm", self.ns
                    )
                iban_node = details.find(
                    "./n:RltdPties/n:CdtrAcct/n:Id/n:IBAN", self.ns
                )

            if partner_node is not None and not partner:
                partner = partner_node.text or ""
            if iban_node is not None and not partner_iban:
                partner_iban = iban_node.text or ""
            purpose_parts.extend(
                node.text
                for node in details.findall("./n:RmtInf/n:Ustrd", self.ns)
                if node.text
            )
            purpose_parts.extend(
                f"REF: {node.text}"
                for node in details.findall(
                    "./n:RmtInf/n:Strd/n:CdtrRefInf/n:Ref", self.ns
                )
                if node.text
            )

        return {
            "datum": date_node.text or "" if date_node is not None else "",
            "betrag": float(amount_node.text),
            "typ": indicator,
            "partner": partner,
            "zweck": " | ".join(purpose_parts),
            "waehrung": amount_node.get("Ccy", "EUR"),
            "iban": iban,
            "partner_iban": partner_iban,
        }
