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
