"""Read the shared workbook using an isolated administrator credential."""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select, text

from app.config import settings
from app.google import Google, GooglePermissionRequired
from app.models import MasterTimetableAccount, TimetableSnapshot, User
from app.parser import ParsedEvents
from app.security import decrypt
from app.timetables import read_timetables


class MasterTimetableUnavailable(ValueError):
    pass


def reader_account(db):
    email = settings().master_timetable_email.strip().lower()
    if not email:
        raise MasterTimetableUnavailable("The administrator must configure the central timetable reader.")
    account = db.get(MasterTimetableAccount, email)
    if account:
        return account
    # Reuse an existing, already-authorized grant once. Keep it separate so a
    # later Calendar-only login cannot overwrite the reader's refresh token.
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user:
        scopes = set(decrypt(user.tokens).get("scope", "").split())
        if "https://www.googleapis.com/auth/drive.readonly" in scopes and decrypt(user.tokens).get("refresh_token"):
            account = MasterTimetableAccount(email=email, subject=user.id, tokens=user.tokens)
            db.add(account)
            db.commit()
            return account
    raise MasterTimetableUnavailable(
        "The administrator must connect the master timetable account. Your Drive permission is not needed."
    )


@contextmanager
def cache_lock(db, key):
    # Dedicated session-level lock survives token-refresh commits. Separate web
    # processes and scheduled workers share it; only one downloads on a miss.
    if db.bind.dialect.name != "postgresql":
        yield
        return
    with db.bind.connect() as connection:
        lock_id = int.from_bytes(hashlib.sha256(("timetable:" + key).encode()).digest()[:8], "big", signed=True)
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_id})
        connection.commit()
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
            connection.commit()


def shared_timetable(db):
    config = settings()
    identity = {
        "reader": config.master_timetable_email.strip().lower(),
        "primary": config.primary_timetable_enabled,
        "file": config.google_spreadsheet_id,
        "gid": config.google_sheet_gid,
        "worksheet": config.excel_sheet_name,
        "additional": [item.model_dump() for item in config.additional_timetables],
        "timezone": config.timetable_timezone,
        "parser": 1,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def cached():
        snapshot = db.get(TimetableSnapshot, key, populate_existing=True)
        if snapshot and snapshot.fetched_at > datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=config.timetable_cache_seconds
        ):
            result = ParsedEvents()
            result.extend(snapshot.data["events"])
            result.issues = snapshot.data["issues"]
            result.sections = {tuple(section) for section in snapshot.data["sections"]}
            return result
        return None

    result = cached()
    if result is not None:
        return result
    with cache_lock(db, key):
        # End an old read transaction before observing another process's fill.
        db.commit()
        result = cached()
        if result is not None:
            return result
        try:
            with Google(db, reader_account(db)) as reader:
                result = read_timetables(
                    reader,
                    SimpleNamespace(
                        spreadsheet_id=config.google_spreadsheet_id,
                        sheet_gid=config.google_sheet_gid,
                    ),
                )
        except (GooglePermissionRequired, ValueError) as exc:
            raise MasterTimetableUnavailable(
                "The shared timetable could not be refreshed. The administrator must check the master account and workbook. Existing calendar events are preserved."
            ) from exc
        # Failed downloads/parses never overwrite the previous snapshot or get
        # presented as a fresh schedule. Partial-section diagnostics are kept.
        db.merge(
            TimetableSnapshot(
                id=key,
                fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
                data={"events": list(result), "issues": result.issues, "sections": sorted(result.sections)},
            )
        )
        db.commit()
        return result
