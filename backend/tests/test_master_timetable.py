from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.master_timetable import MasterTimetableUnavailable, reader_account, shared_timetable
from app.models import MasterTimetableAccount, TimetableSnapshot, User
from app.security import encrypt


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("MASTER_TIMETABLE_EMAIL", "master@example.com")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ADDITIONAL_TIMETABLES", "[]")
    monkeypatch.setenv("PRIMARY_TIMETABLE_ENABLED", "true")
    settings.cache_clear()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            User(
                id="master",
                email="master@example.com",
                name="Master",
                tokens=encrypt(
                    {
                        "scope": "https://www.googleapis.com/auth/drive.readonly",
                        "refresh_token": "reader-refresh",
                    }
                ),
            )
        )
        session.add(
            User(
                id="student",
                email="student@example.com",
                name="Student",
                tokens=encrypt(
                    {
                        "scope": "https://www.googleapis.com/auth/calendar.app.created",
                    }
                ),
            )
        )
        session.commit()
        yield session
    engine.dispose()
    settings.cache_clear()


def test_existing_master_grant_is_isolated_from_later_normal_sign_in(db):
    isolated = reader_account(db)
    assert isolated.subject == "master"
    old_tokens = isolated.tokens
    db.get(User, "master").tokens = encrypt({"scope": "calendar-only"})
    db.commit()
    assert reader_account(db).tokens == old_tokens
    assert db.get(MasterTimetableAccount, "student@example.com") is None


def test_missing_master_never_uses_student_drive_grant(db):
    db.delete(db.get(User, "master"))
    db.get(User, "student").tokens = encrypt(
        {
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "refresh_token": "student-refresh",
        }
    )
    db.commit()
    with pytest.raises(MasterTimetableUnavailable):
        reader_account(db)


def test_shared_snapshot_downloads_once_and_preserves_diagnostics(db, monkeypatch):
    import app.master_timetable as central

    calls = []

    class Reader:
        def __init__(self, _, user):
            assert isinstance(user, MasterTimetableAccount)
            assert user.email == "master@example.com"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def sheet(self, _):
            calls.append(1)
            return [
                ["", "Section - A", "Section - B"],
                ["Date", "9.15 am - 10.30 am", "9.15 am - 10.30 am"],
                ["2026-10-01", "Unknown activity", "CF-1"],
            ]

    monkeypatch.setattr(central, "Google", Reader)
    first = shared_timetable(db)
    for _ in range(100):
        cached = shared_timetable(db)
        assert cached == first
        assert cached.issues == first.issues
        assert cached.sections == first.sections
    assert calls == [1]
    assert cached.issues[0]["section"] == "A"
    # Return independent values: imported ID mutation must not corrupt cache.
    cached[0]["row_id"] = "changed"
    assert shared_timetable(db)[0]["row_id"] != "changed"
    snapshot = db.scalar(select(TimetableSnapshot))
    snapshot.fetched_at -= timedelta(hours=1)
    db.commit()
    shared_timetable(db)
    assert calls == [1, 1]


def test_expired_cache_refresh_failure_never_replaces_snapshot(db, monkeypatch):
    import app.master_timetable as central
    from app.parser import ParsedEvents

    events = ParsedEvents()
    events.sections = {("MBA", "B")}
    events.append({"row_id": "stable-id"})
    monkeypatch.setattr(
        central,
        "Google",
        lambda *_: SimpleNamespace(
            __enter__=lambda self: self,
            __exit__=lambda *_: None,
        ),
    )
    # Provide a real context manager while keeping Google entirely offline.
    from contextlib import nullcontext

    monkeypatch.setattr(central, "Google", lambda *_: nullcontext())
    monkeypatch.setattr(central, "read_timetables", lambda *_: events)
    shared_timetable(db)
    snapshot = db.scalar(select(TimetableSnapshot))
    snapshot.fetched_at -= timedelta(hours=1)
    db.commit()
    old = snapshot.data

    def failed(*_):
        raise ValueError("invalid workbook")

    monkeypatch.setattr(central, "read_timetables", failed)
    with pytest.raises(MasterTimetableUnavailable):
        shared_timetable(db)
    assert db.scalar(select(TimetableSnapshot)).data == old


def test_parser_upgrade_does_not_reuse_a_fresh_quarantined_snapshot(db, monkeypatch):
    from contextlib import nullcontext

    import app.master_timetable as central
    from app.parser import ParsedEvents

    old = ParsedEvents()
    old.issues = [{"row": 40, "column": 31, "section": "F"}]
    updated = ParsedEvents()
    updated.append({"row_id": "guest-session"})
    monkeypatch.setattr(central, "Google", lambda *_: nullcontext())
    monkeypatch.setattr(central, "TIMETABLE_PARSER_VERSION", 1)
    monkeypatch.setattr(central, "read_timetables", lambda *_: old)
    assert shared_timetable(db).issues == old.issues
    monkeypatch.setattr(central, "read_timetables", lambda *_: updated)
    assert shared_timetable(db).issues == old.issues
    monkeypatch.setattr(central, "TIMETABLE_PARSER_VERSION", 2)
    refreshed = shared_timetable(db)
    assert refreshed == updated
    assert not refreshed.issues
