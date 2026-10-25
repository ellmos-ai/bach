"""Shim-Package: macht ellmos-worker/verification_chain.py als `ellmos_worker` importierbar.

Der Ordner heisst 'ellmos-worker' (Bindestrich) und ist damit kein gültiger
Python-Paketname. Dieses Shim leitet __path__ auf den echten Ordner um,
bis dieser per `git mv ellmos-worker ellmos_worker` umbenannt wird
(danach kann dieses Shim gelöscht werden).
"""

from pathlib import Path as _Path

_TARGET = _Path(__file__).resolve().parent.parent / "ellmos-worker"
if not (_TARGET / "verification_chain.py").exists():
    raise ImportError(
        "ellmos-worker/verification_chain.py nicht gefunden; "
        "Shim-Package 'ellmos_worker' nicht nutzbar"
    )

__path__ = [str(_TARGET)]

from .verification_chain import StageResult, VerificationChain, Verdict  # noqa: E402

__all__ = ["VerificationChain", "Verdict", "StageResult"]