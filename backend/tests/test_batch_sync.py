from collections import Counter
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base
from app.models import Source, SyncBatch, User
from app.parser import ParsedEvents


@contextmanager
def unlocked(_):
    yield True


@pytest.fixture
def batch_db(monkeypatch):
    import app.batch_sync as batch

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        for index in range(5):
            db.add(User(id=f"u{index}", email=f"u{index}@example.com", name="Student", tokens="unused"))
            db.add(Source(id=f"s{index}", user_id=f"u{index}", spreadsheet_id="sheet", sheet_gid="0", active=index < 4))
        db.commit()
    monkeypatch.setattr(batch, "SessionLocal", sessions)
    monkeypatch.setattr(batch, "source_lock", unlocked)
    monkeypatch.setattr(batch.time, "sleep", lambda _: None)
    monkeypatch.setenv("SYNC_MAX_WORKERS", "2")
    settings.cache_clear()
    yield sessions
    settings.cache_clear()
    engine.dispose()


def timetable():
    result = ParsedEvents()
    result.sections = {("MBA", "A")}
    result.append({"row_id": "fresh-event"})
    return result


def test_duplicate_requests_share_one_durable_batch_and_only_queue_active_accounts(batch_db):
    from app.batch_sync import batch_summary, queue_shared_sync

    with batch_db() as db:
        first = queue_shared_sync(db)
        again = queue_shared_sync(db)
        assert again.id == first.id
        assert first.source_ids == ["s0", "s1", "s2", "s3"]
        assert len(list(db.scalars(select(SyncBatch)))) == 1
        assert all(db.get(Source, f"s{i}").pending for i in range(4))
        assert not db.get(Source, "s4").pending
        summary = batch_summary(first)
        assert summary["total"] == 4 and summary["processed"] == 0
        assert "source_ids" not in summary and "snapshot" not in summary


def test_one_fresh_snapshot_updates_all_accounts_and_isolates_reconnect_and_errors(batch_db, monkeypatch):
    import app.batch_sync as batch

    parsed = timetable()
    reads, calls = [], Counter()

    def read(db, *, force_refresh):
        reads.append(force_refresh)
        return parsed

    def sync(source_id, snapshot):
        assert snapshot is parsed
        calls[source_id] += 1
        if source_id == "s3":
            raise RuntimeError("one user's provider failed")
        return {"s0": "success", "s1": "unchanged", "s2": "reconnect_required"}[source_id]

    monkeypatch.setattr(batch, "shared_timetable", read)
    monkeypatch.setattr(batch, "sync_source", sync)
    with batch_db() as db:
        batch_id = batch.queue_shared_sync(db).id
    summary = batch.run_shared_sync(batch_id)
    assert reads == [True]
    assert calls == Counter({f"s{i}": 1 for i in range(4)})
    assert summary["status"] == "completed"
    assert summary["processed"] == 4 and summary["up_to_date"] == 2
    assert summary["reconnect_required"] == 1 and summary["failed"] == 1
    assert batch.run_shared_sync(batch_id) == "inactive"
    with batch_db() as db:
        assert db.get(SyncBatch, batch_id).snapshot is None


def test_interrupted_batch_resumes_unfinished_accounts_with_original_snapshot(batch_db, monkeypatch):
    import app.batch_sync as batch

    with batch_db() as db:
        job = batch.queue_shared_sync(db)
        job.status = "running"
        job.outcomes = {"s0": "success", "s1": "reconnect_required"}
        job.snapshot = {"events": list(timetable()), "issues": [], "sections": [["MBA", "A"]]}
        db.commit()
        batch_id = job.id
    calls = []

    def sync(source_id, parsed):
        calls.append(source_id)
        assert parsed == timetable()
        assert parsed.sections == {("MBA", "A")}
        return "success"

    monkeypatch.setattr(batch, "shared_timetable", lambda *_args, **_kwargs: pytest.fail("must reuse saved snapshot"))
    monkeypatch.setattr(batch, "sync_source", sync)
    result = batch.run_shared_sync(batch_id)
    assert set(calls) == {"s2", "s3"}
    assert result["up_to_date"] == 3 and result["reconnect_required"] == 1


def test_invalid_main_timetable_stops_before_any_calendar_updates(batch_db, monkeypatch):
    import app.batch_sync as batch

    def unreadable(*_args, **_kwargs):
        raise ValueError("broken workbook")

    monkeypatch.setattr(batch, "shared_timetable", unreadable)
    monkeypatch.setattr(batch, "sync_source", lambda *_: pytest.fail("must not touch calendars"))
    with batch_db() as db:
        batch_id = batch.queue_shared_sync(db).id
    assert batch.run_shared_sync(batch_id) == "failed"
    with batch_db() as db:
        job = db.get(SyncBatch, batch_id)
        assert job.status == "failed" and job.outcomes == {}
        assert "preserved" in job.message
        assert batch.queue_shared_sync(db).id != batch_id


def test_busy_accounts_stay_queued_and_resume_without_redownloading(batch_db, monkeypatch):
    import app.batch_sync as batch

    reads, calls = [], Counter()
    monkeypatch.setattr(batch, "shared_timetable", lambda *_args, **_kwargs: reads.append(1) or timetable())

    def sync(source_id, _):
        calls[source_id] += 1
        return "busy" if source_id == "s0" else "success"

    monkeypatch.setattr(batch, "sync_source", sync)
    with batch_db() as db:
        batch_id = batch.queue_shared_sync(db).id
    result = batch.run_shared_sync(batch_id)
    assert result["status"] == "queued" and result["processed"] == 3
    assert calls["s0"] == 4
    monkeypatch.setattr(batch, "sync_source", lambda source_id, _: calls.update([source_id]) or "success")
    result = batch.run_shared_sync(batch_id)
    assert result["status"] == "completed" and result["up_to_date"] == 4
    assert reads == [1]
    assert calls == Counter({"s0": 5, "s1": 1, "s2": 1, "s3": 1})


def test_overlapping_workers_leave_the_batch_for_the_active_worker(batch_db, monkeypatch):
    import app.batch_sync as batch

    with batch_db() as db:
        batch_id = batch.queue_shared_sync(db).id

    @contextmanager
    def busy(_):
        yield False

    monkeypatch.setattr(batch, "source_lock", busy)
    monkeypatch.setattr(batch, "shared_timetable", lambda *_args, **_kwargs: pytest.fail("another worker owns it"))
    assert batch.run_shared_sync(batch_id) == "busy"
    with batch_db() as db:
        assert db.get(SyncBatch, batch_id).status == "queued"
