import copy
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.google import Google, GooglePermissionRequired
from app.locks import source_lock
from app.models import Event, Source, SyncRun, User
from app.parser import fingerprint
from app.timetables import event_scope, guard_timetable_removals, managed_event, read_timetables
from app.security import digest

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SyncResult(str):
    def __new__(cls, status, message):
        result = super().__new__(cls, status)
        result.message = message
        return result


def partial_message(issues, updates):
    locations = "; ".join(
        f"{issue['timetable']}, row {issue['row']}, column {issue['column']}: {issue['message']}"
        for issue in issues[:3]
    )
    remaining = f"; and {len(issues) - 3} more" if len(issues) > 3 else ""
    outcome = f"{updates} calendar update(s) applied to readable timetables." if updates else "No calendar changes were made."
    return (
        f"Some timetable entries need attention ({locations}{remaining}). "
        "Existing calendar events for affected timetables were kept unchanged. "
        + outcome
    )


def apply_sync(db, source, google):
    parsed = read_timetables(google, source)
    issues = [i for i in parsed.issues if i["programme"] == source.programme and i["section"] == source.section]
    preserved_scopes = {issue["scope"] for issue in issues}
    selected = [
        e for e in parsed
        if e["programme"] == source.programme and e["section"] == source.section
        and event_scope(e["row_id"]) not in preserved_scopes
    ]
    existing = {
        e.row_id: e for e in db.scalars(select(Event).where(Event.source_id == source.id)) if managed_event(e.row_id)
    }
    guard_timetable_removals(source, existing, selected, preserved_scopes)
    current_fingerprint = fingerprint(selected)
    if not issues and source.fingerprint == current_fingerprint:
        return "unchanged"
    if issues:
        # A partial read must never look like a fully reconciled snapshot, even
        # if a later repair restores the original spreadsheet fingerprint.
        source.fingerprint = None
        db.commit()
    desired = {e["row_id"]: e for e in selected}
    for row_id, event in existing.items():
        if row_id not in desired:
            desired[row_id] = {
                "row_id": row_id,
                "payload": event.payload,
                "cancelled": event.cancelled if event_scope(row_id) in preserved_scopes else True,
            }
    updates = 0
    for row_id, item in desired.items():
        previous = existing.get(row_id)
        if previous and previous.payload == item["payload"] and previous.cancelled == item["cancelled"]:
            continue
        if not source.calendar_id:
            source.calendar_id = google.calendar(source)
            db.commit()
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
        updates += 1
    source.fingerprint = None if issues else current_fingerprint
    source.event_count = sum(not e["cancelled"] for e in desired.values())
    if issues:
        return SyncResult("partial", partial_message(issues, updates))
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
                # Last sync remains the last complete read of the selection.
                # Partial checks and their retained events are visible in runs.
                if result != "partial":
                    source.last_synced_at = utcnow()
                source.last_error = None
                run.status, run.message = result, getattr(result, "message", "Reconciliation completed")
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
                result = "reconnect_required" if isinstance(exc, GooglePermissionRequired) else "failed"
                run.status, run.message = result, message
                db.commit()
                logger.warning("sync source=%s status=%s type=%s", source_id, result, type(exc).__name__)
                return result
