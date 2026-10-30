"""Refresh the main timetable once and reconcile every active account with it."""

import logging
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select, update

from app.config import settings
from app.db import SessionLocal
from app.locks import source_lock
from app.master_timetable import shared_timetable
from app.models import Source, SyncBatch
from app.parser import ParsedEvents
from app.sync import sync_source, utcnow
from app.account_notices import calendar_ready, refresh_notice_safely

logger = logging.getLogger(__name__)
ACTIVE = ("queued", "running")


def batch_summary(batch, db=None):
    outcomes = dict(batch.outcomes)
    if db is not None:
        # A user's successful reconnection may occur after this batch finished.
        for source in db.scalars(select(Source).where(Source.id.in_(batch.source_ids))):
            if outcomes.get(source.id) == "reconnect_required" and calendar_ready(source, batch.requested_at):
                outcomes[source.id] = "success"
    counts = Counter(outcomes.values())
    return {
        "id": batch.id,
        "status": batch.status,
        "total": len(batch.source_ids),
        "processed": sum(status != "busy" for status in batch.outcomes.values()),
        "up_to_date": counts["success"] + counts["unchanged"],
        "reconnect_required": counts["reconnect_required"],
        "failed": counts["failed"],
        "needs_review": counts["partial"],
        "skipped": counts["inactive"],
        "message": batch.message,
        "requested_at": batch.requested_at.isoformat() + "Z",
    }


def latest_batch(db):
    return db.scalar(select(SyncBatch).order_by(SyncBatch.requested_at.desc(), SyncBatch.id.desc()).limit(1))


def queue_shared_sync(db):
    # Requests and scheduled jobs reuse an unfinished batch. This short lock
    # prevents two app processes from creating competing batches at once.
    with source_lock("shared-sync-queue") as acquired:
        if not acquired:
            raise ValueError("An all-account sync is being queued. Please try again shortly.")
        batch = db.scalar(select(SyncBatch).where(SyncBatch.status.in_(ACTIVE)).limit(1))
        if batch:
            return batch
        ids = list(db.scalars(select(Source.id).where(Source.active.is_(True)).order_by(Source.id)))
        batch = SyncBatch(
            id=uuid.uuid4().hex, requested_at=utcnow(), source_ids=ids, outcomes={}, status="queued", message=""
        )
        db.add(batch)
        db.execute(update(Source).where(Source.active.is_(True)).values(pending=True))
        db.commit()
        return batch


def reconcile_account(source_id, parsed):
    for attempt in range(4):
        try:
            result = str(sync_source(source_id, parsed))
        except Exception as exc:
            logger.warning("batch sync source=%s error=%s", source_id, type(exc).__name__)
            return "failed"
        if result != "busy" or attempt == 3:
            return result
        time.sleep(2 * (attempt + 1))


def run_shared_sync(batch_id):
    # A process crash releases this lock. The next cron/request resumes the
    # persisted snapshot and unfinished accounts instead of losing the batch.
    with source_lock("shared-sync-worker") as acquired:
        if not acquired:
            return "busy"
        with SessionLocal() as db:
            batch = db.get(SyncBatch, batch_id)
            if not batch or batch.status not in ACTIVE:
                return "inactive"
            batch.status = "running"
            batch.started_at = batch.started_at or utcnow()
            db.commit()
            refresh_notice_safely(db, start=True)
            if batch.snapshot is None:
                try:
                    parsed = shared_timetable(db, force_refresh=True)
                except Exception as exc:
                    batch.status, batch.finished_at = "failed", utcnow()
                    batch.message = (
                        "The main timetable could not be refreshed. Check the administrator connection and workbook. "
                        "Existing calendar events were preserved."
                    )
                    db.commit()
                    logger.warning("batch timetable refresh failed type=%s", type(exc).__name__)
                    return "failed"
                batch.snapshot = {"events": list(parsed), "issues": parsed.issues, "sections": sorted(parsed.sections)}
                db.commit()
            else:
                parsed = ParsedEvents()
                parsed.extend(batch.snapshot["events"])
                parsed.issues = batch.snapshot["issues"]
                parsed.sections = {tuple(section) for section in batch.snapshot["sections"]}
            remaining = [sid for sid in batch.source_ids if batch.outcomes.get(sid) in (None, "busy")]
            with ThreadPoolExecutor(max_workers=settings().sync_max_workers) as pool:
                tasks = {pool.submit(reconcile_account, sid, parsed): sid for sid in remaining}
                for task in as_completed(tasks):
                    sid, outcome = tasks[task], task.result()
                    batch.outcomes = {**batch.outcomes, sid: outcome}
                    db.commit()
                    refresh_notice_safely(db, start=True)
            if "busy" in batch.outcomes.values():
                batch.status = "queued"
                batch.message = "Some accounts are still syncing. Retry Sync all accounts or wait for the scheduled retry."
            else:
                batch.status, batch.finished_at = "completed", utcnow()
                batch.message = "All connected accounts have been checked."
                # The snapshot is needed only for crash recovery while active.
                batch.snapshot = None
            db.commit()
            summary = batch_summary(batch)
            logger.info("shared sync completed %s", summary)
            return summary
