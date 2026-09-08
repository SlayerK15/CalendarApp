# LiveTimetable

Next.js frontend, FastAPI backend, and PostgreSQL: connect a college timetable in Google Sheets to a dedicated **College Timetable** Google Calendar. Default deployment is **Vercel + Render Web Service + Render PostgreSQL + Render Cron**.

## Status

The application is deployed on Render: [open LiveTimetable](https://calendarapp-2r1h.onrender.com). The API, PostgreSQL database, and five-minute sync cron are configured. Google currently rejects the production callback with `redirect_uri_mismatch`; register the URI in [the production record](docs/PRODUCTION.md) before signing in. Real Google API acceptance checks still require a successful user login. The supplied spreadsheet returned HTTP 401 to an anonymous export, so its actual format is not yet verified. The current parser supports the documented [row contract](docs/SHEET_FORMAT.md); an Excel/CSV export is needed if the real timetable uses a different layout. Landing-page sample classes are explicitly illustrative, never shown as a user's real timetable.

## Run locally

1. Copy `.env.example` to `.env` (ignored by Git).
2. Follow [Google Cloud setup](docs/DEPLOYMENT.md#1-google-cloud) and fill the Google OAuth values.
3. Generate and save `TOKEN_ENCRYPTION_KEY` and `GOOGLE_WEBHOOK_SECRET` as described below.
4. Start Docker Desktop, then run:

```bash
docker compose up --build
```

Frontend: http://localhost:3000 · API: http://localhost:8000 · OpenAPI: http://localhost:8000/docs

Migrations run before the Docker API starts. PostgreSQL uses a named Docker volume; all persistent application state is in that database. Production containers have no persistent filesystem requirement. You can load the UI and health endpoints without Google credentials in development; sign-in requires credentials.

Generate an encryption key using the backend image (copy the output into `.env`; never commit it):

```bash
docker compose run --rm --no-deps backend python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
docker compose run --rm --no-deps backend python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Run fallback reconciliation locally:

```bash
docker compose --profile jobs run --rm sync
```

Localhost cannot receive Google push notifications. Use manual sync or run the job; production registers an HTTPS webhook automatically. `SYNC_INTERVAL_SECONDS=300` documents the desired interval; the actual production schedule is `*/5 * * * *` in `render.yaml`. Update both if changing cadence. No polling loop runs inside FastAPI.

## Develop without containers

Use Python 3.12+ and Node 22. Start PostgreSQL (for example `docker compose up -d db`), then:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cp .env backend/.env
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

SQLite is available for isolated parser/migration development using `DATABASE_URL=sqlite:///./livetimetable.db`. Full sync requires PostgreSQL because the distributed lock uses session advisory locks. Use a direct database connection, not a transaction-pooling proxy.

## Validation

```bash
cd backend
../.venv/bin/ruff check .
../.venv/bin/pytest -q
../.venv/bin/alembic check
```

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database to include the cross-connection advisory-lock test. GitHub CI provides PostgreSQL and runs migration upgrade, schema drift detection, lint, and tests.

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

## Deploy

Follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The repository includes `render.yaml`, Alembic migrations, both Dockerfiles, Docker Compose, environment templates, and GitHub Actions. Render plan IDs follow the [current Blueprint specification](https://render.com/docs/blueprint-spec). Review the paid service estimates in Render before creating resources.

## Architecture

- The browser calls same-origin Next.js `/api/*`. Its narrowly allowlisted server proxy uses `NEXT_PUBLIC_API_URL` to reach FastAPI. This preserves first-party HttpOnly cookies on unrelated Vercel/Render domains.
- OAuth callback remains on FastAPI at `GOOGLE_REDIRECT_URI`. A single-use, two-minute application ticket in the URL fragment is redeemed with the initiating browser's HttpOnly binding cookie. No Google tokens reach frontend JavaScript.
- PostgreSQL stores encrypted Google credentials, OAuth state, hashed app sessions, source configuration, watch subscriptions, event mappings, and sync logs.
- Google Drive notifications persist pending work and return 202 before background processing. PostgreSQL advisory locks serialize operations per source. A five-minute cron reconciles all active sources, recovering interrupted or lost background tasks.
- A source is currently one user's selected programme/section. Multiple users viewing the same spreadsheet have independent calendars and locks. This MVP fetches the sheet per user; parser and sync services can later be reused behind a shared-source queue/worker.
- Canonical fingerprints skip unchanged schedules. Stable Google event IDs make retries safe even after a remote write succeeds and the process crashes. Removed rows default to a `[CANCELLED]` title and transparent busy status. Explicit `delete` mode deletes instead.
- Parsing/fetch failures do not cancel events. Calendar failures do not advance the fingerprint or success timestamp. Successful individual event writes are committed so retries resume safely; multi-event updates are eventually consistent, not an atomic Google transaction.
- Watch renewal happens before expiry, independent of unchanged fingerprints. Temporary overlapping channels are validated. A crashed watch registration is recovered by cron.
- Logs older than 30 days, expired sessions, and OAuth flows are pruned by cron. App tokens remain backend-side, Fernet encrypted. Keep the encryption key stable and backed up securely.

No Redis, Celery, Kubernetes, persistent app disk, or additional worker is required.
