"""Solana anchoring: the ProofSettle program as a tamper-evident mirror of the audit trail.

get_chain() is None unless app.config's solana_* settings are complete and load, and then
nothing in the workflow touches the chain (every event stays chain_status "skipped").
"""

import logging
import threading

from app.chain.program import Chain
from app.config import settings

log = logging.getLogger(__name__)

_chain: Chain | None = None
_built = False
_guard = threading.Lock()


def get_chain() -> Chain | None:
    """The configured chain, built once. Bad settings disable anchoring rather than raise,
    so a missing keypair file can't break the workflow (PRD §9)."""
    global _chain, _built
    with _guard:
        if not _built:
            try:
                _chain = Chain.from_settings(settings)
            except Exception:
                log.exception("Solana anchoring disabled: the solana_* settings could not be loaded")
                _chain = None
            _built = True
        return _chain


def set_chain(chain: Chain | None) -> None:
    """Replace the configured chain (tests, or after changing settings at runtime)."""
    global _chain, _built
    with _guard:
        _chain, _built = chain, True
