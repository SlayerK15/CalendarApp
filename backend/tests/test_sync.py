import copy
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Event, Source, SyncRun, User
from app.parser import fingerprint, guard_removals, parse_sheet
from app.sync import apply_sync

HEADER = ["id", "programme", "section", "title", "date", "start_time", "end_time", "location", "status"]
ROW = ["math-001", "BTech", "A", "Mathematics", "2026-09-10", "09:00", "10:00", "101", "scheduled"]


class FakeGoogle:
    def __init__(self):
        self.rows = [HEADER, ROW.copy()]
        self.calls = []
        self.remote = {}
        self.fail = False

    def sheet(self, source):
        return self.rows

    def calendar(self, source):
        return "calendar-1"

    def put_event(self, calendar_id, event_id, payload, deleted=False):
        if self.fail:
            raise RuntimeError("provider unavailable")
        self.calls.append((event_id, copy.deepcopy(payload), deleted))
        self.remote[event_id] = copy.deepcopy(payload)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="user", name="Student", email="student@example.com", tokens="encrypted"))
        session.add(
            Source(
                id="source",
                user_id="user",
                spreadsheet_id="sheet",
                sheet_gid="0",
                programme="BTech",
                section="A",
                active=True,
            )
        )
        session.commit()
        yield session
    engine.dispose()


def test_retry_update_cancel_same_event(db):
    source, google = db.get(Source, "source"), FakeGoogle()
    assert apply_sync(db, source, google) == "success"
    db.commit()
    first_id = google.calls[0][0]
    assert apply_sync(db, source, google) == "unchanged"
    assert len(google.calls) == 1
    google.rows[1][7] = "204"
    apply_sync(db, source, google)
    db.commit()
    assert google.calls[-1][0] == first_id
    assert google.calls[-1][1]["location"] == "204"
    google.rows[1][8] = "cancelled"
    apply_sync(db, source, google)
    db.commit()
    assert google.calls[-1][0] == first_id
    assert google.calls[-1][1]["summary"] == "[CANCELLED] Mathematics"
    google.rows[1][8] = "scheduled"
    apply_sync(db, source, google)
    assert google.calls[-1][1]["summary"] == "Mathematics"
    assert len(list(db.scalars(select(Event)))) == 1


def test_failed_sheet_does_not_cancel(db):
    source, google = db.get(Source, "source"), FakeGoogle()
    apply_sync(db, source, google)
    db.commit()
    old = source.fingerprint
    google.rows = []
    with pytest.raises(ValueError):
        apply_sync(db, source, google)
    assert source.fingerprint == old
    assert len(google.calls) == 1


def test_provider_failure_does_not_advance_fingerprint(db):
    source, google = db.get(Source, "source"), FakeGoogle()
    apply_sync(db, source, google)
    db.commit()
    old = source.fingerprint
    google.rows[1][7] = "204"
    google.fail = True
    with pytest.raises(RuntimeError):
        apply_sync(db, source, google)
    assert source.fingerprint == old
    google.fail = False
    apply_sync(db, source, google)
    assert len(google.remote) == 1
    assert source.fingerprint != old


def test_crash_after_google_write_uses_same_id(db):
    source, google = db.get(Source, "source"), FakeGoogle()
    original = google.put_event

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("crash after remote write")

    google.put_event = interrupted
    with pytest.raises(RuntimeError):
        apply_sync(db, source, google)
    google.put_event = original
    apply_sync(db, source, google)
    assert len(google.remote) == 1


def test_removed_class_is_marked(db):
    source, google = db.get(Source, "source"), FakeGoogle()
    row2 = ROW.copy()
    row2[0] = "math-002"
    google.rows.append(row2)
    apply_sync(db, source, google)
    db.commit()
    google.rows.pop()
    apply_sync(db, source, google)
    assert google.calls[-1][1]["summary"].startswith("[CANCELLED]")


def test_parser_and_destructive_guard():
    events = parse_sheet([HEADER, ROW])
    assert events[0]["payload"]["start"]["dateTime"].endswith("+05:30")
    assert fingerprint(events) == fingerprint(list(reversed(events)))
    with pytest.raises(ValueError, match="duplicate"):
        parse_sheet([HEADER, ROW, ROW])
    with pytest.raises(ValueError):
        parse_sheet([["unexpected"], ["layout"]])
    with pytest.raises(ValueError):
        guard_removals(12, 5)
    with pytest.raises(ValueError):
        guard_removals(1, 0)


def test_failed_run_is_persisted_and_retried(db, monkeypatch):
    import app.sync as sync

    @contextmanager
    def locked(_):
        yield True

    @contextmanager
    def session():
        yield db

    google = FakeGoogle()
    google.fail = True
    monkeypatch.setattr(sync, "source_lock", locked)
    monkeypatch.setattr(sync, "SessionLocal", session)
    monkeypatch.setattr(sync, "Google", lambda *_: google)
    assert sync.sync_source("source") == "failed"
    assert db.get(Source, "source").last_synced_at is None
    assert db.get(Source, "source").pending
    assert db.scalar(select(SyncRun)).status == "failed"
    google.fail = False
    assert sync.sync_source("source") == "success"
    assert db.get(Source, "source").last_synced_at


def test_postgres_lock_excludes_second_connection(monkeypatch):
    import os
    import app.locks as locks
    from app.db import make_engine

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL locking integration test")
    engine = make_engine(url)
    monkeypatch.setattr(locks, "engine", engine)
    key = uuid.uuid4().hex
    with locks.source_lock(key) as first:
        assert first
        with locks.source_lock(key) as second:
            assert not second
    with locks.source_lock(key) as third:
        assert third
    engine.dispose()
