import copy
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.google import Google
from app.locks import source_lock
from app.models import Event, Source, SyncRun, User
from app.parser import fingerprint, guard_removals, parse_sheet
from app.security import digest

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def apply_sync(db, source, google):
    parsed = parse_sheet(google.sheet(source), settings().timetable_timezone)
    selected = [e for e in parsed if e["programme"] == source.programme and e["section"] == source.section]
    existing = {e.row_id: e for e in db.scalars(select(Event).where(Event.source_id == source.id))}
    guard_removals(sum(not e.cancelled for e in existing.values()), len(selected))
    current_fingerprint = fingerprint(selected)
    if source.fingerprint == current_fingerprint:
        return "unchanged"
    if not source.calendar_id:
        source.calendar_id = google.calendar(source)
        db.commit()
    desired = {e["row_id"]: e for e in selected}
    for row_id, event in existing.items():
        if row_id not in desired:
            desired[row_id] = {"row_id": row_id, "payload": event.payload, "cancelled": True}
    for row_id, item in desired.items():
        previous = existing.get(row_id)
        if previous and previous.payload == item["payload"] and previous.cancelled == item["cancelled"]:
            continue
        event_id = digest(source.id + ":" + row_id)
        payload = copy.deepcopy(item["payload"])
        payload["status"] = "confirmed"
        if item["cancelled"]:
            payload["summary"] = "[CANCELLED] " + payload["summary"]
            payload["transparency"] = "transparent"
        else:
            payload["transparency"] = "opaque"
        google.put_event(
            source.calendar_id,
            event_id,
            payload,
            deleted=item["cancelled"] and settings().cancelled_event_behaviour == "delete",
        )
        if previous:
            previous.payload, previous.cancelled = item["payload"], item["cancelled"]
        else:
            db.add(
                Event(
                    id=event_id,
                    source_id=source.id,
                    row_id=row_id,
                    payload=item["payload"],
                    cancelled=item["cancelled"],
                )
            )
        # Persist each successful operation. Deterministic IDs make crash retries safe.
        db.commit()
    source.fingerprint = current_fingerprint
    source.event_count = sum(not e["cancelled"] for e in selected)
    return "success"


def sync_source(source_id):
    with source_lock(source_id) as acquired:
        if not acquired:
            return "busy"
        with SessionLocal() as db:
            source = db.get(Source, source_id)
            if not source or not source.active:
                return "inactive"
            source.pending = False
            db.commit()
            run = SyncRun(id=uuid.uuid4().hex, source_id=source_id, status="running", message="")
            db.add(run)
            db.commit()
            try:
                with Google(db, db.get(User, source.user_id)) as google:
                    result = apply_sync(db, source, google)
                source.last_synced_at, source.last_error = utcnow(), None
                run.status, run.message = result, "Reconciliation completed"
                db.commit()
                logger.info("sync source=%s status=%s", source_id, result)
                return result
            except Exception as exc:
                db.rollback()
                # Do not persist provider responses, which may include sensitive data.
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else f"{type(exc).__name__}: synchronization failed; retry scheduled"
                )
                source.last_error, source.pending = message, True
                run.status, run.message = "failed", message
                db.commit()
                logger.warning("sync source=%s status=failed type=%s", source_id, type(exc).__name__)
                return "failed"
