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


@pytest.mark.parametrize("kind", ["missing", "unknown", "expired", "reused"])
def test_invalid_callback_returns_to_sign_in_without_authenticating(client, monkeypatch, kind):
    import app.main as main

    http, db = client
    if kind in {"expired", "reused"}:
        db.add(
            AuthFlow(
                state=digest("test-state"),
                binding=digest("browser"),
                verifier=encrypt("pkce"),
                expires_at=utcnow() + timedelta(minutes=-1 if kind == "expired" else 1),
                consumed=kind == "reused",
            )
        )
        db.commit()

    def unexpected_provider_call(*args, **kwargs):
        pytest.fail("Invalid state must never contact Google or exchange a code")

    monkeypatch.setattr(main.httpx, "Client", unexpected_provider_call)
    query = {} if kind == "missing" else {"state": "test-state", "code": "untrusted-code"}
    response = http.get("/api/auth/google/callback", params=query, follow_redirects=False)
    assert response.status_code == 303
    expected = "restart" if kind == "missing" else "expired"
    assert response.headers["location"] == f"http://localhost:3000/?auth={expected}"
    assert response.headers["cache-control"] == "no-store"
    assert "lt_session" not in response.headers.get("set-cookie", "")
    assert db.scalar(select(LoginSession)) is None


def test_valid_callback_exchanges_code_and_ticket_then_rejects_replay(client, monkeypatch):
    import httpx
    import app.main as main
    from urllib.parse import parse_qs, urlparse

    http, db = client
    db.add(
        AuthFlow(
            state=digest("valid-state"),
            binding=digest("browser"),
            verifier=encrypt("pkce-verifier"),
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    db.commit()
    calls = []

    class GoogleClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, data):
            calls.append(url)
            assert data["code"] == "valid-code"
            assert data["code_verifier"] == "pkce-verifier"
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "access_token": "google-access-token",
                    "refresh_token": "google-refresh-token",
                    "expires_in": 3600,
                },
            )

        def get(self, url, headers):
            assert headers["Authorization"] == "Bearer google-access-token"
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={
                    "sub": "u",
                    "email": "test@example.com",
                    "name": "Student",
                },
            )

    monkeypatch.setattr(main.httpx, "Client", GoogleClient)
    response = http.get(
        "/api/auth/google/callback", params={"state": "valid-state", "code": "valid-code"}, follow_redirects=False
    )
    assert response.status_code == 303
    target = response.headers["location"]
    assert target.startswith("http://localhost:3000/auth/complete#ticket=")
    assert "google-access-token" not in target and "google-refresh-token" not in target
    ticket = parse_qs(urlparse(target).fragment)["ticket"][0]
    replay = http.get(
        "/api/auth/google/callback", params={"state": "valid-state", "code": "valid-code"}, follow_redirects=False
    )
    assert replay.headers["location"].endswith("/?auth=expired")
    assert len(calls) == 1
    http.cookies.set("lt_oauth", "browser")
    exchange = http.post("/api/auth/exchange", json={"ticket": ticket}, headers={"Origin": "http://localhost:3000"})
    assert exchange.status_code == 200
    assert http.get("/api/me").status_code == 200


def test_excel_permission_error_exposes_reconnect_action(client, monkeypatch):
    import app.main as main
    from app.google import GooglePermissionRequired

    http, db = client
    db.add(LoginSession(token_hash=digest("signed-in"), user_id="u", expires_at=utcnow() + timedelta(hours=1)))
    db.commit()
    http.cookies.set("lt_session", "signed-in")

    class MissingPermission:
        def __init__(self, *args):
            pass

        def sheet(self, source):
            raise GooglePermissionRequired("Reconnect Google to read this Excel timetable.")

    monkeypatch.setattr(main, "Google", MissingPermission)
    response = http.get("/api/options")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "google_reconnect_required"
    assert "Reconnect Google" in response.json()["detail"]["message"]
