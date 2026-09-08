import base64
import hashlib
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import get_db
from app.google import Google
from app.jobs.renew_google_watch import renew_source
from app.locks import source_lock
from app.models import AuthFlow, Event, Session, Source, SyncRun, User, Watch
from app.parser import parse_sheet
from app.security import decrypt, digest, encrypt
from app.sync import sync_source, utcnow


@asynccontextmanager
async def lifespan(app):
    settings().validate_runtime()
    yield


app = FastAPI(title="LiveTimetable API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    if request.method == "POST" and request.url.path != "/api/webhooks/google-drive":
        if request.headers.get("origin") not in settings().origins:
            return Response("Origin not allowed", status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def cookie(response, name, value, age):
    response.set_cookie(name, value, httponly=True, secure=settings().production, samesite="lax", max_age=age, path="/")


def current_user(request: Request, db: DBSession = Depends(get_db)):
    session = db.get(Session, digest(request.cookies.get("lt_session", "")))
    if not session or session.expires_at < utcnow():
        raise HTTPException(401, "Please sign in with Google")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Please sign in again")
    return user


def user_source(db, user):
    source = db.scalar(select(Source).where(Source.user_id == user.id))
    if not source:
        source = Source(
            id=uuid.uuid4().hex,
            user_id=user.id,
            spreadsheet_id=settings().google_spreadsheet_id,
            sheet_gid=settings().google_sheet_gid,
        )
        db.add(source)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            source = db.scalar(select(Source).where(Source.user_id == user.id))
            if source is None:
                raise
    return source


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db(db: DBSession = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ok"}


@app.post("/api/auth/google/start")
def auth_start(response: Response, db: DBSession = Depends(get_db)):
    config = settings()
    if not all(
        (config.google_client_id, config.google_client_secret, config.google_redirect_uri, config.token_encryption_key)
    ):
        raise HTTPException(503, "Google login is not configured. Set backend environment variables first.")
    state, binding, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    db.add(
        AuthFlow(
            state=digest(state),
            binding=digest(binding),
            verifier=encrypt(verifier),
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    db.commit()
    cookie(response, "lt_oauth", binding, 600)
    query = urlencode(
        {
            "client_id": config.google_client_id,
            "redirect_uri": config.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile https://www.googleapis.com/auth/spreadsheets.readonly https://www.googleapis.com/auth/drive.metadata.readonly https://www.googleapis.com/auth/calendar.app.created https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode(),
            "code_challenge_method": "S256",
        }
    )
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + query}


@app.get("/api/auth/google/callback")
def auth_callback(state: str = "", code: str = "", error: str = "", db: DBSession = Depends(get_db)):
    flow = db.scalar(select(AuthFlow).where(AuthFlow.state == digest(state)).with_for_update())
    if not flow or flow.consumed or flow.expires_at < utcnow():
        raise HTTPException(400, "Invalid or expired OAuth request")
    flow.consumed = True
    db.commit()
    if error or not code:
        return RedirectResponse(settings().frontend_url + "/?auth=denied", status_code=303)
    try:
        with httpx.Client(timeout=30) as client:
            result = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings().google_client_id,
                    "client_secret": settings().google_client_secret,
                    "redirect_uri": settings().google_redirect_uri,
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": decrypt(flow.verifier),
                },
            )
            result.raise_for_status()
            token = result.json()
            profile_response = client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": "Bearer " + token["access_token"]},
            )
            profile_response.raise_for_status()
            profile = profile_response.json()
        user = db.get(User, profile["sub"])
        if user and not token.get("refresh_token"):
            token["refresh_token"] = decrypt(user.tokens).get("refresh_token")
        if not token.get("refresh_token"):
            raise ValueError("Offline access required")
        token["expires_at"] = time.time() + token["expires_in"]
        if user:
            user.tokens, user.email, user.name = encrypt(token), profile["email"], profile.get("name", "")
        else:
            user = User(id=profile["sub"], email=profile["email"], name=profile.get("name", ""), tokens=encrypt(token))
            db.add(user)
        db.flush()
        ticket = secrets.token_urlsafe(32)
        flow.user_id, flow.ticket, flow.expires_at = user.id, digest(ticket), utcnow() + timedelta(minutes=2)
        db.commit()
    except Exception:
        db.rollback()
        return RedirectResponse(settings().frontend_url + "/?auth=failed", status_code=303)
    # Fragment is not sent in server logs/referrers. This is a short-lived app ticket, never a Google token.
    return RedirectResponse(settings().frontend_url + "/auth/complete#ticket=" + ticket, status_code=303)


class Exchange(BaseModel):
    ticket: str = Field(max_length=100)


@app.post("/api/auth/exchange")
def exchange(body: Exchange, request: Request, response: Response, db: DBSession = Depends(get_db)):
    flow = db.scalar(select(AuthFlow).where(AuthFlow.ticket == digest(body.ticket)).with_for_update())
    if (
        not flow
        or not flow.user_id
        or flow.expires_at < utcnow()
        or not secrets.compare_digest(flow.binding, digest(request.cookies.get("lt_oauth", "")))
    ):
        raise HTTPException(400, "Login expired or browser mismatch. Please sign in again.")
    token = secrets.token_urlsafe(32)
    db.add(Session(token_hash=digest(token), user_id=flow.user_id, expires_at=utcnow() + timedelta(days=30)))
    db.delete(flow)
    db.commit()
    cookie(response, "lt_session", token, 30 * 86400)
    response.delete_cookie("lt_oauth", path="/")
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: DBSession = Depends(get_db)):
    session = db.get(Session, digest(request.cookies.get("lt_session", "")))
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie("lt_session", path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"name": user.name, "email": user.email}


@app.get("/api/options")
def options(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    try:
        events = parse_sheet(Google(db, user).sheet(user_source(db, user)), settings().timetable_timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(502, "Could not read the spreadsheet. Check access and Google API configuration.") from None
    programmes = {}
    for event in events:
        programmes.setdefault(event["programme"], set()).add(event["section"])
    return {key: sorted(value) for key, value in sorted(programmes.items())}


class Selection(BaseModel):
    programme: str = Field(min_length=1, max_length=200)
    section: str = Field(min_length=1, max_length=100)


def reconcile(source_id):
    sync_source(source_id)
    try:
        renew_source(source_id)
    except Exception:
        pass  # Cron retries registration independently of calendar sync.


@app.post("/api/subscription")
def subscribe(
    body: Selection, tasks: BackgroundTasks, user: User = Depends(current_user), db: DBSession = Depends(get_db)
):
    available = options(user, db)
    if body.section not in available.get(body.programme, []):
        raise HTTPException(422, "Programme and section are not present in the sheet")
    source = user_source(db, user)
    with source_lock(source.id) as acquired:
        if not acquired:
            raise HTTPException(409, "A sync is running. Try again shortly.")
        source.programme, source.section, source.active, source.pending = body.programme, body.section, True, True
        source.fingerprint = None
        db.commit()
    tasks.add_task(reconcile, source.id)
    return {"status": "queued"}


@app.post("/api/sync", status_code=202)
def manual_sync(tasks: BackgroundTasks, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    source = user_source(db, user)
    if not source.active:
        raise HTTPException(400, "Select your programme and section first")
    source.pending = True
    db.commit()
    tasks.add_task(reconcile, source.id)
    return {"status": "queued"}


@app.get("/api/dashboard")
def dashboard(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    source = user_source(db, user)
    events = list(db.scalars(select(Event).where(Event.source_id == source.id)))
    runs = list(
        db.scalars(select(SyncRun).where(SyncRun.source_id == source.id).order_by(SyncRun.started_at.desc()).limit(10))
    )
    watches = list(
        db.scalars(
            select(Watch).where(
                Watch.source_id == source.id, Watch.resource_id.is_not(None), Watch.expiration > utcnow()
            )
        )
    )
    return {
        "programme": source.programme,
        "section": source.section,
        "active": source.active,
        "pending": source.pending,
        "calendar_id": source.calendar_id,
        "last_synced_at": source.last_synced_at.isoformat() + "Z" if source.last_synced_at else None,
        "last_error": source.last_error,
        "event_count": source.event_count,
        "watch_active": bool(watches),
        "events": [
            {"id": e.row_id, **e.payload, "cancelled": e.cancelled}
            for e in sorted(events, key=lambda e: e.payload["start"]["dateTime"])
        ],
        "runs": [{"status": r.status, "message": r.message, "at": r.started_at.isoformat() + "Z"} for r in runs],
    }


@app.post("/api/webhooks/google-drive", status_code=202)
def webhook(request: Request, tasks: BackgroundTasks, db: DBSession = Depends(get_db)):
    secret = settings().google_webhook_secret
    if not secret or not secrets.compare_digest(request.headers.get("x-goog-channel-token", ""), secret):
        raise HTTPException(403, "Invalid notification")
    watch = db.get(Watch, request.headers.get("x-goog-channel-id", ""))
    resource = request.headers.get("x-goog-resource-id", "")
    state = request.headers.get("x-goog-resource-state", "")
    if (
        not watch
        or watch.expiration < utcnow()
        or not resource
        or state not in {"sync", "add", "remove", "update", "trash", "untrash", "change"}
    ):
        raise HTTPException(403, "Unknown notification")
    if watch.resource_id and not secrets.compare_digest(watch.resource_id, resource):
        raise HTTPException(403, "Resource mismatch")
    if not watch.resource_id and state != "sync":
        raise HTTPException(409, "Watch registration in progress")
    source = db.get(Source, watch.source_id)
    source.pending = True
    db.commit()
    tasks.add_task(sync_source, source.id)
    return {"status": "accepted"}
