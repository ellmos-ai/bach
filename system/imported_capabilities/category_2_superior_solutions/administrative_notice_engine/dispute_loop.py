"""Autonomous Self-Healing Vendor Dispute & Correction Loop with GDPR Privacy Gates."""

from typing import Optional
from sentinel_fleet.domains.omniledger.models import InvoiceDocument
from sentinel_fleet.memory.bank import DEFAULT_ORGANIZATION_ID
from sentinel_fleet.memory.hooker import memory_hooker
from sentinel_fleet.core.privacy_contacts import privacy_contact_hub


class DisputeCommunicator:
    @staticmethod
    def generate_dispute_resolution(
        doc: InvoiceDocument,
        requested_by: str = "operator",
        requested_department: Optional[str] = None,
        requested_organization: str = DEFAULT_ORGANIZATION_ID,
    ) -> str:
        """Generates a legally sound, courteous correction request to the vendor under strict GDPR controls."""
        # 1. Check Privacy Contact Hub & Opt-Out Blacklist
        perm = privacy_contact_hub.validate_send_permission(
            doc.vendor_email,
            requested_by=requested_by,
            requested_department=requested_department,
            requested_organization=requested_organization,
        )
        if not perm["allowed"]:
            doc.dispute_email_draft = f"BLOCKED BY PRIVACY GATE: {perm['reason']}"
            return doc.dispute_email_draft

        violations_formatted = "\n".join(f"- {v}" for v in doc.compliance_violations)

        # 2. Inject corporate memory / policy context and quote it in the draft, so the
        #    operator can see which retrieved knowledge the argument rests on.
        # The query keeps the statute tokens (14, UStG) on purpose: the legal corpus is
        # indexed in German, and dropping them would silently empty the retrieval.
        memory_clues = memory_hooker.inject_context(
            "invoice audit § 14 UStG correction request",
            requested_by=requested_by,
            requested_department=requested_department,
            requested_organization=requested_organization,
        )
        clue_lines = [line for line in memory_clues.splitlines() if line.startswith("- ")]
        reference_block = ""
        if clue_lines:
            reference_block = (
                "Reference context (retrieved from memory bank and legal corpus):\n"
                + "\n".join(clue_lines)
                + "\n\n"
            )

        body = (
            f"Dear Sir or Madam,\n\n"
            f"thank you for sending your invoice no. {doc.invoice_number} dated {doc.invoice_date} "
            f"for a gross amount of {doc.gross_amount:.2f} {doc.currency}.\n\n"
            f"Our automated tax intake audit under § 14 UStG found the following formal defects:\n"
            f"{violations_formatted}\n\n"
            f"Under German tax law we may only deduct input VAT once all mandatory fields are present. "
            f"We therefore kindly ask you to send us a corrected invoice or a formal invoice correction.\n\n"
            f"Until the corrected document arrives, the automatic payment instruction for this invoice "
            f"has been placed on hold.\n\n"
            f"{reference_block}"
            f"Data protection notice: your contact details are processed under GDPR protection level S3 "
            f"for the purpose of meeting our tax obligations.\n\n"
            f"Kind regards\n"
            f"SentinelFleet Autonomous Accounting Governance"
        )

        doc.dispute_email_draft = body
        return body


dispute_communicator = DisputeCommunicator()
