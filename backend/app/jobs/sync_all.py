import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.jobs.renew_google_watch import renew_source
from app.models import AuthFlow, Session, Source, SyncRun
from app.sync import sync_source, utcnow

BATCH_SIZE = 100


def reconcile_one(source_id):
    failed = False
    try:
        failed = sync_source(source_id) == "failed"
    except Exception as exc:
        failed = True
        logging.error("sync source=%s error=%s", source_id, type(exc).__name__)
    try:
        renew_source(source_id)
    except Exception as exc:
        failed = True
        logging.error("watch source=%s error=%s", source_id, type(exc).__name__)
    return failed


def main():
    settings().validate_runtime()
    logging.basicConfig(level=logging.INFO)
    failed, processed, cursor = False, 0, ""
    with SessionLocal() as db:
        db.execute(delete(AuthFlow).where(AuthFlow.expires_at < utcnow()))
        db.execute(delete(Session).where(Session.expires_at < utcnow()))
        db.execute(delete(SyncRun).where(SyncRun.started_at < utcnow() - timedelta(days=30)))
        db.commit()
    # Each worker owns its DB session, Google client and per-source advisory lock.
    # Keyset pagination bounds memory as the number of subscriptions grows.
    with ThreadPoolExecutor(max_workers=settings().sync_max_workers) as pool:
        while True:
            with SessionLocal() as db:
                ids = list(
                    db.scalars(
                        select(Source.id)
                        .where(Source.active.is_(True), Source.id > cursor)
                        .order_by(Source.id)
                        .limit(BATCH_SIZE)
                    )
                )
            if not ids:
                break
            for result in pool.map(reconcile_one, ids):
                failed |= result
                processed += 1
            cursor = ids[-1]
    logging.info("scheduled reconciliation processed=%s failed=%s", processed, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
