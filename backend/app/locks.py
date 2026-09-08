from contextlib import contextmanager
import hashlib

from sqlalchemy import text

from app.db import engine


@contextmanager
def source_lock(source_id):
    # Dedicated connection: advisory lock survives ORM commits and releases on process death.
    with engine.connect() as connection:
        key = int.from_bytes(hashlib.sha256(source_id.encode()).digest()[:8], "big", signed=True)
        if engine.dialect.name == "postgresql":
            acquired = connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
            connection.commit()
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    connection.commit()
        else:
            # SQLite is for parser/unit development only; use compose/Postgres for full sync.
            raise RuntimeError("Synchronization requires PostgreSQL for safe distributed locking")
