from collections import Counter
from threading import Lock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.models import Source, User


def test_batches_process_all_active_sources_and_preserve_failure(monkeypatch):
    import app.jobs.sync_all as job

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        for index in range(7):
            db.add(User(id=f"u{index}", email=f"u{index}@example.com", name="Test", tokens="unused"))
            db.add(Source(id=f"s{index}", user_id=f"u{index}", spreadsheet_id="sheet", sheet_gid="0", active=index < 6))
        db.commit()
    calls, guard = Counter(), Lock()

    def reconcile(source_id):
        with guard:
            calls[source_id] += 1
        return source_id == "s2"

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SYNC_MAX_WORKERS", "2")
    settings.cache_clear()
    monkeypatch.setattr(job, "SessionLocal", sessions)
    monkeypatch.setattr(job, "BATCH_SIZE", 2)
    monkeypatch.setattr(job, "reconcile_one", reconcile)
    assert job.main() == 1
    assert calls == Counter({f"s{i}": 1 for i in range(6)})
    settings.cache_clear()
    engine.dispose()


def test_one_failed_user_does_not_skip_watch_renewal(monkeypatch):
    import app.jobs.sync_all as job

    calls = []

    def fail(_):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(job, "sync_source", fail)
    monkeypatch.setattr(job, "renew_source", lambda source_id: calls.append(source_id))
    assert job.reconcile_one("source")
    assert calls == ["source"]
