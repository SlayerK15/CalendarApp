from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url):
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(
        url, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}
    )


engine = make_engine(settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db
