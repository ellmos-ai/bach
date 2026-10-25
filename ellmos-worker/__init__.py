"""ellmos-worker – Verifizierungs-Kette (fail-closed) für BACH-Tool-Ausführung.

Öffentliche API:
    from ellmos_worker.verification_chain import VerificationChain, Verdict, StageResult
"""

try:
    from .verification_chain import StageResult, VerificationChain, Verdict
    __all__ = ["VerificationChain", "Verdict", "StageResult"]
except ImportError:
    # Kein Paketkontext (Ordnername mit Bindestrich, pytest prepend-Import
    # als Modul "__init__"); Submodule über ellmos_worker-Shim laden.
    pass