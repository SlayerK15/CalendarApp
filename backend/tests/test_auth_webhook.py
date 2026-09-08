from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import AuthFlow, Session as LoginSession, Source, User, Watch
from app.security import digest, encrypt
from app.sync import utcnow


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("GOOGLE_WEBHOOK_SECRET", "test-channel-secret")
    settings.cache_clear()
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(User(id="u", name="Student", email="test@example.com", tokens=encrypt({})))
        db.add(Source(id="s", user_id="u", spreadsheet_id="sheet", sheet_gid="0"))
        db.commit()

        def session():
            yield db

        app.dependency_overrides[get_db] = session
        with TestClient(app) as client:
            yield client, db
    app.dependency_overrides.clear()
    settings.cache_clear()
    engine.dispose()


def test_health_auth_and_csrf(client):
    http, _ = client
    assert http.get("/health").json() == {"status": "ok"}
    assert http.get("/health/db").status_code == 200
    assert http.get("/api/me").status_code == 401
    assert http.post("/api/auth/logout").status_code == 403
    assert http.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert http.post("/api/auth/logout", headers={"Origin": "http://localhost:3000"}).status_code == 200


def test_ticket_is_browser_bound_single_use_and_session_http_only(client):
    http, db = client
    db.add(
        AuthFlow(
            state=digest("state"),
            binding=digest("browser"),
            verifier=encrypt("pkce"),
            ticket=digest("ticket"),
            user_id="u",
            consumed=True,
            expires_at=utcnow() + timedelta(minutes=1),
        )
    )
    db.commit()
    headers = {"Origin": "http://localhost:3000"}
    assert http.post("/api/auth/exchange", json={"ticket": "ticket"}, headers=headers).status_code == 400
    http.cookies.set("lt_oauth", "browser")
    result = http.post("/api/auth/exchange", json={"ticket": "ticket"}, headers=headers)
    assert result.status_code == 200
    assert "HttpOnly" in result.headers["set-cookie"]
    assert "SameSite=lax" in result.headers["set-cookie"]
    assert http.get("/api/me").json()["email"] == "test@example.com"
    assert http.post("/api/auth/exchange", json={"ticket": "ticket"}, headers=headers).status_code == 400
    assert db.scalar(select(LoginSession))
    http.post("/api/auth/logout", headers=headers)
    assert http.get("/api/me").status_code == 401


def test_webhook_rejects_forged_channel_and_resource(client, monkeypatch):
    import app.main as main

    http, db = client
    calls = []
    monkeypatch.setattr(main, "sync_source", lambda source: calls.append(source))
    db.add(Watch(channel_id="channel", source_id="s", resource_id="resource", expiration=utcnow() + timedelta(hours=1)))
    db.commit()
    assert http.post("/api/webhooks/google-drive").status_code == 403
    headers = {
        "X-Goog-Channel-Token": "test-channel-secret",
        "X-Goog-Channel-ID": "channel",
        "X-Goog-Resource-ID": "wrong",
        "X-Goog-Resource-State": "update",
    }
    assert http.post("/api/webhooks/google-drive", headers=headers).status_code == 403
    headers["X-Goog-Resource-ID"] = "resource"
    assert http.post("/api/webhooks/google-drive", headers=headers).status_code == 202
    assert calls == ["s"]
    assert db.get(Source, "s").pending
    db.get(Watch, "channel").expiration = utcnow() - timedelta(seconds=1)
    db.commit()
    assert http.post("/api/webhooks/google-drive", headers=headers).status_code == 403
