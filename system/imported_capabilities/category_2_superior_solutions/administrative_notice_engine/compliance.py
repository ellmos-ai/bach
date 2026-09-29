"""Tax Compliance & § 14 UStG Validator based on law-checker."""

from sentinel_fleet.domains.omniledger.models import InvoiceDocument, InvoiceStatus
from sentinel_fleet.core.policies import PolicyEngine, PolicyDecisionType


class ComplianceAuditor:
    @staticmethod
    def audit_invoice(doc: InvoiceDocument) -> InvoiceDocument:
        """Audits an invoice against statutory tax requirements."""
        payload = {
            "vendor_name": doc.vendor_name,
            "vendor_vat_id": doc.vendor_vat_id,
            "invoice_number": doc.invoice_number,
            "invoice_date": doc.invoice_date,
            "delivery_date": doc.delivery_date,
            "net_amount": doc.net_amount,
            "tax_rate": doc.tax_rate,
            "gross_amount": doc.gross_amount,
        }

        result = PolicyEngine.evaluate_tax_compliance(payload)

        if result.decision == PolicyDecisionType.PASS:
            doc.compliance_passed = True
            doc.compliance_violations = []
            doc.status = InvoiceStatus.COMPLIANCE_VERIFIED
        else:
            doc.compliance_passed = False
            doc.compliance_violations = result.violations
            doc.status = InvoiceStatus.DISPUTED

        return doc


compliance_auditor = ComplianceAuditor()
