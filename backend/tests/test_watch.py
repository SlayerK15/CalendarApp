from contextlib import contextmanager
from datetime import timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import Source, User, Watch
from app.sync import utcnow


def test_renewal_respects_returned_expiry_and_skips_fresh_watch(monkeypatch):
    import app.jobs.renew_google_watch as job

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com")
    monkeypatch.setenv("GOOGLE_WEBHOOK_SECRET", "test-only-secret")
    settings.cache_clear()
    calls = []
    expiry = utcnow().replace(microsecond=0) + timedelta(hours=20)

    @contextmanager
    def lock(_):
        yield True

    with Session(engine, expire_on_commit=False) as db:
        db.add(User(id="u", email="test@example.com", name="Test", tokens="encrypted"))
        db.add(Source(id="s", user_id="u", spreadsheet_id="sheet", sheet_gid="0", active=True))
        db.add(
            Watch(channel_id="old", source_id="s", resource_id="old-resource", expiration=utcnow() + timedelta(hours=1))
        )
        db.commit()

        class Google:
            def __init__(self, *_):
                pass

            def request(self, method, url, **kwargs):
                calls.append((url, kwargs["json"]))
                if url.endswith("/watch"):
                    # Registration row must exist before Google can send the initial notification.
                    assert db.get(Watch, kwargs["json"]["id"])
                    return {
                        "resourceId": "new-resource",
                        "expiration": str(int(expiry.replace(tzinfo=timezone.utc).timestamp() * 1000)),
                    }
                return {}

        @contextmanager
        def session():
            yield db

        monkeypatch.setattr(job, "SessionLocal", session)
        monkeypatch.setattr(job, "source_lock", lock)
        monkeypatch.setattr(job, "Google", Google)
        job.renew_source("s")
        watches = list(db.scalars(select(Watch)))
        assert len(watches) == 1
        assert watches[0].resource_id == "new-resource"
        assert watches[0].expiration == expiry
        assert calls[0][1]["address"] == "https://api.example.com/api/webhooks/google-drive"
        assert calls[1][0].endswith("/channels/stop")
        job.renew_source("s")
        assert len(calls) == 2
    settings.cache_clear()
    engine.dispose()
