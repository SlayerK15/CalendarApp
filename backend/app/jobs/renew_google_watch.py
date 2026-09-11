import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.google import Google
from app.locks import source_lock
from app.models import Source, User, Watch
from app.sync import utcnow


def renew_source(source_id):
    if not settings().backend_url.startswith("https://") or not settings().google_webhook_secret:
        return
    with source_lock(source_id) as acquired:
        if not acquired:
            return
        with SessionLocal() as db:
            source = db.get(Source, source_id)
            if not source or not source.active:
                return
            watches = list(db.scalars(select(Watch).where(Watch.source_id == source_id)))
            renewal_margin = timedelta(seconds=max(43200, settings().sync_interval_seconds * 2))
            if any(w.resource_id and w.expiration > utcnow() + renewal_margin for w in watches):
                return
            with Google(db, db.get(User, source.user_id)) as google:
                watch = Watch(channel_id=uuid.uuid4().hex, source_id=source_id, expiration=utcnow() + timedelta(days=1))
                db.add(watch)
                db.commit()
                # Google can send its initial notification before watch() returns.
                result = google.request(
                    "POST",
                    f"https://www.googleapis.com/drive/v3/files/{quote(source.spreadsheet_id, safe='')}/watch",
                    json={
                        "id": watch.channel_id,
                        "type": "web_hook",
                        "address": settings().backend_url.rstrip("/") + "/api/webhooks/google-drive",
                        "token": settings().google_webhook_secret,
                        "expiration": str(int(watch.expiration.replace(tzinfo=timezone.utc).timestamp() * 1000)),
                    },
                )
                watch.resource_id = result["resourceId"]
                watch.expiration = datetime.fromtimestamp(int(result["expiration"]) / 1000, timezone.utc).replace(
                    tzinfo=None
                )
                db.commit()
                for old in watches:
                    if old.expiration > utcnow() and old.resource_id:
                        google.request(
                            "POST",
                            "https://www.googleapis.com/drive/v3/channels/stop",
                            json={"id": old.channel_id, "resourceId": old.resource_id},
                        )
                    db.delete(old)
                    db.commit()


if __name__ == "__main__":
    with SessionLocal() as db:
        ids = list(db.scalars(select(Source.id).where(Source.active.is_(True))))
    for source_id in ids:
        renew_source(source_id)
