"""AI inspection as a background job, so no HTTP request has to wait for it.

A Gemini inspection takes a minute or more (87 s for two photos), and hosts cap a web
request well below that (Modal: 150 s). So POST /shipments/{id}/inspect only checks that
an inspection may start, marks the shipment `inspection_state = "running"` and returns
202; this job then runs in the same process, after the response. The shipment detail's
`inspectionRun` shows "running" until the job finishes, and "failed" with the reason if it
couldn't, in which case it can be started again.

The job takes the shipment's row lock and app.operations.run_inspection re-checks the
status, so two runs can never both store findings.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.chain import get_chain
from app.chain.anchoring import anchor_in_background
from app.config import settings
from app.inspection import InspectionFailed, InspectionProvider
from app.models import Shipment
from app.operations import run_inspection
from app.storage import EvidenceStore, StorageError
from app.workflow import Actor, TransitionError

log = logging.getLogger(__name__)

RUNNING, FAILED = "running", "failed"


def is_running(s: Shipment, now: datetime) -> bool:
    """A run is in progress, and recent enough to still be alive.

    A job that died without recording an outcome (the process stopped) would otherwise
    block the shipment forever; after `inspection_stale_s` it may be started again.
    """
    if s.inspection_state != RUNNING or s.inspection_started_at is None:
        return False
    return now - s.inspection_started_at < timedelta(seconds=settings.inspection_stale_s)


def mark_running(s: Shipment, now: datetime) -> None:
    s.inspection_state, s.inspection_error, s.inspection_started_at = RUNNING, None, now


def _locked(db: Session, shipment_id: str) -> Shipment | None:
    return db.scalars(
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(
            selectinload(Shipment.agreement),
            selectinload(Shipment.evidence),
            selectinload(Shipment.findings),
            selectinload(Shipment.events),
            selectinload(Shipment.adjustment),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()


def _record_failure(sessions: Callable[[], Session], shipment_id: str, reason: str) -> None:
    try:
        with sessions() as db:
            s = _locked(db, shipment_id)
            if s is not None and s.inspection_state == RUNNING:
                s.inspection_state, s.inspection_error = FAILED, reason[:2000]
                db.commit()
    except Exception:
        log.exception("Could not record the failed inspection of %s", shipment_id)


def run_inspection_job(
    sessions: Callable[[], Session],
    shipment_id: str,
    actor: Actor,
    provider: InspectionProvider,
    store: EvidenceStore,
) -> None:
    """Run the inspection and store its outcome; never raises (it runs after the response)."""
    try:
        with sessions() as db:
            s = _locked(db, shipment_id)
            if s is None:
                return
            run_inspection(s, actor, provider, store, datetime.now(UTC))
            s.inspection_state = s.inspection_error = s.inspection_started_at = None
            db.commit()
    except (InspectionFailed, TransitionError, StorageError) as e:
        log.warning("Inspection of %s failed: %s", shipment_id, e)
        _record_failure(sessions, shipment_id, str(e))
        return
    except Exception:
        log.exception("Inspection of %s crashed", shipment_id)
        _record_failure(sessions, shipment_id, "The inspection failed unexpectedly; run it again")
        return
    if get_chain() is not None:
        anchor_in_background(sessions, shipment_id)
