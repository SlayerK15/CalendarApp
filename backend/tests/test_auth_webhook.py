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
from app.models import AuthFlow, Session as LoginSession, Source, SyncRun, User, Watch
from app.security import digest, encrypt
from app.sync import utcnow


def test_regular_oauth_requests_calendar_without_drive_even_with_master_query(client, monkeypatch):
    from urllib.parse import urlparse, parse_qs
    http, _ = client
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://api.example.com/callback")
    settings.cache_clear()
    response = http.post("/api/auth/google/start?purpose=master", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    scopes = parse_qs(urlparse(response.json()["url"]).query)["scope"][0].split()
    assert "https://www.googleapis.com/auth/calendar.app.created" in scopes
    assert not any("drive" in scope or "spreadsheets" in scope for scope in scopes)


def test_only_pinned_master_can_start_reader_authorization(client, monkeypatch):
    from urllib.parse import urlparse, parse_qs
    http, db = client
    monkeypatch.setenv("MASTER_TIMETABLE_EMAIL", "master@example.com")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://api.example.com/callback")
    settings.cache_clear()
    headers = {"Origin": "http://localhost:3000"}
    assert http.post("/api/admin/timetable/connect", headers=headers).status_code == 401
    db.add(LoginSession(token_hash=digest("signed-in"), user_id="u", expires_at=utcnow() + timedelta(hours=1)))
    db.commit()
    http.cookies.set("lt_session", "signed-in")
    assert http.post("/api/admin/timetable/connect", headers=headers).status_code == 403
    db.get(User, "u").email = "master@example.com"
    db.commit()
    result = http.post("/api/admin/timetable/connect", headers=headers)
    assert result.status_code == 200
    scopes = parse_qs(urlparse(result.json()["url"]).query)["scope"][0].split()
    assert "https://www.googleapis.com/auth/drive.readonly" in scopes
    assert not any("calendar" in scope for scope in scopes)
    assert db.scalar(select(AuthFlow)).purpose == "master"


@pytest.mark.parametrize("profile_email,profile_subject,bound,expected", [
    ("master@example.com", "u", True, True), ("other@example.com", "u", True, False),
    ("master@example.com", "u", False, False), ("master@example.com", "different-user", True, False),
])
def test_master_callback_requires_pinned_account_and_browser_and_isolates_tokens(
    client, monkeypatch, profile_email, profile_subject, bound, expected
):
    import app.main as main
    import httpx
    from app.models import MasterTimetableAccount
    http, db = client
    monkeypatch.setenv("MASTER_TIMETABLE_EMAIL", "master@example.com")
    settings.cache_clear()
    original_tokens = db.get(User, "u").tokens
    db.add(AuthFlow(state=digest("master-state"), binding=digest("browser"), verifier=encrypt("pkce"),
                    purpose="master", user_id="u", expires_at=utcnow() + timedelta(minutes=5)))
    db.commit()
    db.get(User, "u").email = "master@example.com"
    db.commit()

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, url, data):
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "access_token": "master-access", "refresh_token": "master-refresh", "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/drive.readonly",
            })

        def get(self, url, headers):
            return httpx.Response(200, request=httpx.Request("GET", url), json={
                "sub": profile_subject, "email": profile_email, "email_verified": True,
            })

    monkeypatch.setattr(main.httpx, "Client", Client)
    response = http.get("/api/auth/google/callback?state=master-state&code=code", follow_redirects=False)
    # Google calls the backend domain, which cannot receive the frontend cookie.
    # No grant may be installed until the first-party exchange checks it.
    assert db.get(MasterTimetableAccount, "master@example.com") is None
    assert "master-access" not in response.text
    location = response.headers["location"]
    if profile_email != "master@example.com" or profile_subject != "u":
        assert "auth=failed" in location
        return
    assert "/auth/complete#ticket=" in location
    ticket = location.split("#ticket=", 1)[1]
    flow = db.scalar(select(AuthFlow))
    assert "master-access" not in flow.pending_tokens
    if bound:
        http.cookies.set("lt_oauth", "browser")
    result = http.post("/api/auth/exchange", json={"ticket": ticket}, headers={"Origin": "http://localhost:3000"})
    assert result.status_code == (200 if expected else 400)
    assert bool(db.get(MasterTimetableAccount, "master@example.com")) is expected
    assert db.get(User, "u").tokens == original_tokens
    assert http.post("/api/auth/exchange", json={"ticket": ticket}, headers={"Origin": "http://localhost:3000"}).status_code == 400


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


@pytest.mark.parametrize("immediate", [False, True])
def test_webhook_rejects_forged_channel_and_resource(client, monkeypatch, immediate):
    import app.main as main

    http, db = client
    monkeypatch.setenv("SYNC_ON_CHANGE", str(immediate).lower())
    settings.cache_clear()
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
    assert calls == (["s"] if immediate else [])
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
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def __init__(self, *args):
            pass

        def sheet(self, source):
            raise GooglePermissionRequired("Reconnect Google to read this Excel timetable.")

    monkeypatch.setattr(main, "Google", MissingPermission)
    response = http.get("/api/options")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "google_reconnect_required"
    assert "Reconnect Google" in response.json()["detail"]["message"]


def test_dashboard_exposes_background_reconnect_requirement(client):
    http, db = client
    db.add(LoginSession(token_hash=digest("signed-in"), user_id="u", expires_at=utcnow() + timedelta(hours=1)))
    db.add(SyncRun(id="expired-auth", source_id="s", status="reconnect_required", message="Reconnect Google"))
    db.get(Source, "s").last_error = "Reconnect Google"
    db.commit()
    http.cookies.set("lt_session", "signed-in")
    assert http.get("/api/dashboard").json()["google_reconnect_required"] is True
    db.add(SyncRun(id="recovered", source_id="s", status="success", message="Done", started_at=utcnow() + timedelta(seconds=1)))
    db.get(Source, "s").last_error = None
    db.commit()
    assert http.get("/api/dashboard").json()["google_reconnect_required"] is False


def test_timetable_parse_error_is_not_reported_as_google_reconnection(client, monkeypatch):
    import app.main as main

    http, db = client
    db.add(LoginSession(token_hash=digest("signed-in"), user_id="u", expires_at=utcnow() + timedelta(hours=1)))
    db.commit()
    http.cookies.set("lt_session", "signed-in")

    def invalid_timetable(*_):
        raise ValueError("Unrecognized timetable entry at row 9, column 25")

    monkeypatch.setattr(main, "read_timetables", invalid_timetable)
    response = http.get("/api/options")
    assert response.status_code == 422
    assert response.json() == {"detail": "Unrecognized timetable entry at row 9, column 25"}


def test_options_keep_sections_even_when_their_classes_are_quarantined(client, monkeypatch):
    import app.main as main

    http, db = client
    db.add(LoginSession(token_hash=digest("signed-in"), user_id="u", expires_at=utcnow() + timedelta(hours=1)))
    db.commit()
    http.cookies.set("lt_session", "signed-in")

    class Reader:
        def __init__(self, *_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def sheet(self, _):
            return [
                ["", "Section - A", "Section - B"],
                ["Date", "9.15 am - 10.30 am", "9.15 am - 10.30 am"],
                ["2026-10-01", "Unrecognized class notation", "Another unknown entry"],
            ]

    monkeypatch.setattr(main, "Google", Reader)
    response = http.get("/api/options")
    assert response.status_code == 200
    assert response.json() == {"MBA": ["A", "B"]}


def test_dashboard_warning_survives_running_check_and_clears_after_complete_sync(client):
    http, db = client
    checked = utcnow()
    db.add(LoginSession(token_hash=digest("signed-in"), user_id="u", expires_at=checked + timedelta(hours=1)))
    db.add(SyncRun(
        id="partial-check", source_id="s", status="partial", started_at=checked,
        message="Existing calendar events for the unreadable timetable were kept unchanged."
    ))
    db.commit()
    http.cookies.set("lt_session", "signed-in")
    result = http.get("/api/dashboard").json()
    assert "kept unchanged" in result["sync_warning"]
    assert result["last_error"] is None
    assert result["google_reconnect_required"] is False
    db.add(SyncRun(
        id="running-check", source_id="s", status="running", message="", started_at=checked + timedelta(seconds=1)
    ))
    db.commit()
    assert http.get("/api/dashboard").json()["sync_warning"] == result["sync_warning"]
    running = db.get(SyncRun, "running-check")
    running.status, running.message = "success", "Reconciliation completed"
    db.commit()
    assert http.get("/api/dashboard").json()["sync_warning"] is None


def sign_in_for_sync(http, db):
    db.add(LoginSession(token_hash=digest("sync-user"), user_id="u", expires_at=utcnow() + timedelta(hours=1)))
    db.commit()
    http.cookies.set("lt_session", "sync-user")


def test_main_account_sync_queues_every_active_account_without_own_subscription(client, monkeypatch):
    from contextlib import contextmanager

    import app.batch_sync as batches
    import app.main as main
    from app.models import SyncBatch

    http, db = client
    monkeypatch.setenv("MASTER_TIMETABLE_EMAIL", "TEST@example.com")
    settings.cache_clear()
    sign_in_for_sync(http, db)
    db.add(User(id="other", name="Other", email="other@example.com", tokens="unused"))
    db.add(Source(id="other-source", user_id="other", spreadsheet_id="sheet", sheet_gid="0", active=True))
    db.commit()

    @contextmanager
    def unlocked(_):
        yield True

    monkeypatch.setattr(batches, "source_lock", unlocked)
    calls = []
    monkeypatch.setattr(main, "run_shared_sync", lambda batch_id: calls.append(batch_id))
    response = http.post("/api/sync", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 202 and response.json()["scope"] == "all"
    batch_id = response.json()["batch"]["id"]
    assert db.get(SyncBatch, batch_id).source_ids == ["other-source"]
    assert calls == [batch_id]
    assert not db.get(Source, "s").active
    assert db.get(Source, "other-source").pending
    again = http.post("/api/sync", headers={"Origin": "http://localhost:3000"})
    assert again.json()["batch"]["id"] == batch_id
    assert http.get("/api/dashboard").json()["shared_sync"]["total"] == 1


def test_student_cannot_request_all_accounts_or_read_their_batch_status(client, monkeypatch):
    import app.main as main
    from app.models import SyncBatch

    http, db = client
    monkeypatch.setenv("MASTER_TIMETABLE_EMAIL", "main@example.com")
    settings.cache_clear()
    sign_in_for_sync(http, db)
    db.get(Source, "s").active = True
    db.add(SyncBatch(id="other-batch", source_ids=["someone-else"], outcomes={}, status="running", message=""))
    db.commit()
    calls = []
    monkeypatch.setattr(main, "reconcile", lambda source_id: calls.append(source_id))
    monkeypatch.setattr(main, "queue_shared_sync", lambda *_: pytest.fail("student must not queue everyone"))
    response = http.post("/api/sync?admin=true", json={"scope": "all"}, headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 202 and response.json()["scope"] == "self"
    assert calls == ["s"]
    assert http.get("/api/dashboard").json()["shared_sync"] is None


def test_updating_main_accounts_class_selection_also_updates_every_account(client, monkeypatch):
    from contextlib import contextmanager
    import app.batch_sync as batches
    import app.main as main
    from app.models import SyncBatch

    http, db = client
    monkeypatch.setenv("MASTER_TIMETABLE_EMAIL", "test@example.com")
    settings.cache_clear()
    sign_in_for_sync(http, db)
    monkeypatch.setattr(main, "options", lambda *_: {"MBA Analytics": ["F"]})

    @contextmanager
    def unlocked(_):
        yield True

    monkeypatch.setattr(main, "source_lock", unlocked)
    monkeypatch.setattr(batches, "source_lock", unlocked)
    calls = []
    monkeypatch.setattr(main, "run_shared_sync", lambda batch_id: calls.append(batch_id))
    response = http.post("/api/subscription", json={"programme": "MBA Analytics", "section": "F"},
                         headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200 and response.json()["scope"] == "all"
    assert db.get(Source, "s").programme == "MBA Analytics"
    assert db.get(Source, "s").section == "F"
    assert db.get(SyncBatch, calls[0]).source_ids == ["s"]
