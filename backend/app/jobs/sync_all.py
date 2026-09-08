import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.jobs.renew_google_watch import renew_source
from app.models import AuthFlow, Session, Source, SyncRun
from app.sync import sync_source, utcnow


def main():
    settings().validate_runtime()
    logging.basicConfig(level=logging.INFO)
    failed = False
    with SessionLocal() as db:
        ids = list(db.scalars(select(Source.id).where(Source.active.is_(True))))
        db.execute(delete(AuthFlow).where(AuthFlow.expires_at < utcnow()))
        db.execute(delete(Session).where(Session.expires_at < utcnow()))
        db.execute(delete(SyncRun).where(SyncRun.started_at < utcnow() - timedelta(days=30)))
        db.commit()
    for source_id in ids:
        try:
            failed |= sync_source(source_id) == "failed"
        except Exception as exc:
            failed = True
            logging.error("sync source=%s error=%s", source_id, type(exc).__name__)
        try:
            renew_source(source_id)
        except Exception as exc:
            failed = True
            logging.error("watch source=%s error=%s", source_id, type(exc).__name__)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
