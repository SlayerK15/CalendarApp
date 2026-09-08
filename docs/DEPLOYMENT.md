# Deploy LiveTimetable

Current deployment: [frontend](https://calendarapp-2r1h.onrender.com) and [API health](https://livetimetable-api.onrender.com/health) are live on Render. See [the production record](PRODUCTION.md) for verified checks and the remaining Google OAuth setup.

Primary: **Vercel frontend + Render FastAPI + Render PostgreSQL + Render Cron**. This guide accompanies executable configuration in the repository; it is not a claim that these services have already been provisioned.

## Prerequisites

A GitHub repository containing this project, access to a Vercel account and Render workspace, and a Google Cloud project with OAuth credentials. The supplied sheet must be readable by the signed-in Google account and conform to [SHEET_FORMAT.md](SHEET_FORMAT.md). The supplied Excel section grid is supported; the signed-in Google account must grant Drive read-only content access.

No SSH setup is required. Run commands locally, through Render's dashboard shell, or using the supplied deployment commands. Store secrets only in platform environment settings or ignored `.env` files.

## 1. Google Cloud

1. Open [Google Cloud Console](https://console.cloud.google.com/), create a project, and select it.
2. In **APIs & Services → Library**, enable Google Sheets API, Google Drive API, and Google Calendar API.
3. Open **Google Auth Platform** (OAuth consent screen). Configure branding, support email, audience, and developer contact. For a student test deployment, use External with your Google accounts added as test users. Workspace Internal is available only within a compatible organization.
4. Add the requested data-access scopes:
   - `openid`, `email`, `profile`
   - `https://www.googleapis.com/auth/spreadsheets.readonly`
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/calendar.app.created`
   - `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
5. Create an OAuth client of type **Web application**. Store its client ID and secret in the backend environment only.
6. Add development redirect URI exactly: `http://localhost:8000/api/auth/google/callback`.
7. Add production redirect URI exactly: `https://<render-backend-domain>/api/auth/google/callback`. Scheme, host, path, and trailing slash must match `GOOGLE_REDIRECT_URI`.
8. Set application homepage/privacy details and authorized domains as required by the consent configuration. Before public use beyond test users, complete Google's publishing/verification requirements for the chosen scopes. Testing-mode refresh tokens may expire; reauthorization is then necessary. See [Google OAuth production readiness](https://developers.google.com/identity/protocols/oauth2/production-readiness/policy-compliance).

The app asks for offline access and keeps refreshed credentials encrypted on the backend. Calendar-list read access lets it recover its own created calendar after an interrupted creation; calendar writes are scoped to app-created calendars. See [CalendarList authorization](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list).

Google Drive watch configuration is an API call performed by the app, not a Google OAuth redirect setting. Its receiver will be `https://<render-backend-domain>/api/webhooks/google-drive`.

## 2. Render

### Blueprint deployment

1. Push the project to GitHub. Confirm both CI jobs pass.
2. In Render choose **New → Blueprint**, connect the repository, and use root `render.yaml`.
3. Review the resources before creation:
   - `livetimetable-api`: Python Web Service, 0.5 CPU/512 MB.
   - `livetimetable-db`: PostgreSQL 16, 0.1 CPU/256 MB, 5 GB disk.
   - `livetimetable-sync-cron`: Python Cron, 0.5 CPU/512 MB, every five minutes.
4. Enter the prompted backend variables. The cron references the same values from the API service; do not generate different token-encryption keys for the two processes.
5. Render supplies `DATABASE_URL` from PostgreSQL and `PORT` to the web process. Build installs `requirements.txt`; pre-deploy runs `alembic upgrade head`; start uses `uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log`.
6. Find the assigned public API URL at the top of the Web Service dashboard. If its name differs from your intended URL, update `BACKEND_URL` and `GOOGLE_REDIRECT_URI`, and the Google OAuth redirect registration. The API will reject incomplete production configuration until valid values are set.
7. Use your intended Vercel production domain for `FRONTEND_URL` and `ALLOWED_ORIGINS`; update them after Vercel assigns its actual domain. Redeploy after changes and sync the Blueprint so cron references receive updated values.
8. Health Check Path is already `/health`. Verify `/health` and `/health/db` both return 200 with `{"status":"ok"}`.
9. Wait for the API's migration step to finish before triggering the cron manually. Cron does not run migrations concurrently with the API.

The Blueprint uses current plan IDs and service-level secret prompts; Render does not support `sync: false` inside environment groups. See [Render Blueprint reference](https://render.com/docs/blueprint-spec). Render service names are not guarantees of public hostname availability.

### Environment values

| Variable | Production value |
| --- | --- |
| ENVIRONMENT | production |
| DATABASE_URL | Render internal **direct** PostgreSQL connection, injected by Blueprint |
| FRONTEND_URL | `https://<your-project>.vercel.app` |
| BACKEND_URL | `https://<your-api>.onrender.com` |
| ALLOWED_ORIGINS | Same exact frontend origin, comma-separated if more than one |
| GOOGLE_CLIENT_ID | OAuth web client ID |
| GOOGLE_CLIENT_SECRET | OAuth web client secret |
| GOOGLE_REDIRECT_URI | `https://<your-api>.onrender.com/api/auth/google/callback` |
| GOOGLE_SPREADSHEET_ID | `1V5A1Z-PzrLs-92YCYmFA0L9fpwWbhVuN` |
| GOOGLE_SHEET_GID | `129828207` (native Google Sheets only) |
| EXCEL_SHEET_NAME | Exact Excel worksheet name when the workbook has multiple tabs |
| GOOGLE_WEBHOOK_SECRET | Random high-entropy string, shared by API and cron |
| TOKEN_ENCRYPTION_KEY | Fernet key, shared by API and cron |
| SYNC_INTERVAL_SECONDS | 300 (keep Blueprint cron cadence aligned) |
| CANCELLED_EVENT_BEHAVIOUR | mark_cancelled (default) or delete |
| TIMETABLE_TIMEZONE | Asia/Kolkata |

Generate secrets locally after installing backend dependencies:

```bash
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Save the outputs directly in Render settings. Do not paste them into GitHub, logs, issue comments, or frontend environment variables. Losing the Fernet key requires users to reconnect Google. Rotation requires decrypting/re-encrypting stored credentials with controlled old/new keys.

### Manual Render equivalent

Create PostgreSQL and a Python Web Service in the same region; set root directory `backend`, build `pip install -r requirements.txt`, pre-deploy `alembic upgrade head`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log`, and health `/health`. Copy the database internal URL into `DATABASE_URL` and set the table above. Create a Cron Job with the same root/build/environment and start `python -m app.jobs.sync_all`, schedule `*/5 * * * *`.

To apply migrations explicitly from the backend directory with `DATABASE_URL` configured:

```bash
alembic upgrade head
alembic current
alembic check
```

Use deployment pre-deploy commands for future migrations. Back up PostgreSQL before schema changes. Do not attach a persistent disk to the API or cron.

## 3. Vercel

1. Choose **Add New → Project**, import the GitHub repository.
2. Set **Root Directory** to `frontend` and framework to Next.js.
3. Use Node.js 22, install `npm ci`, build `npm run build`, and default Next.js output settings.
4. Add `NEXT_PUBLIC_API_URL=https://<render-backend-domain>` to the production environment (no trailing slash needed). It is the upstream for the server proxy. Never store a Google secret here.
5. Deploy. Set your production domain under **Settings → Domains**. Add its exact origin to backend `ALLOWED_ORIGINS`, set `FRONTEND_URL`, redeploy the API, and sync cron configuration.
6. Frontend routes and assets can load before Google configuration; actual login and schedule sync require the configured backend.

The frontend is a Next.js server application, not a static export: its `/api/*` route is a cookie-preserving, allowlisted proxy. All outbound API requests use `NEXT_PUBLIC_API_URL`. This extra HTTPS hop is intentional to avoid third-party cookie dependence across `vercel.app` and `onrender.com`. Production cookies are Secure, HttpOnly, SameSite=Lax, host-only. POSTs require an allowed Origin. Google callback is still on the backend, and finishes at `/dashboard` after the browser-bound ticket exchange.

Use a stable preview domain explicitly listed in `ALLOWED_ORIGINS` if testing OAuth previews. Avoid enabling credentials for `*` origins. Do not allow arbitrary preview hosts.

## 4. OAuth production check

Set `GOOGLE_REDIRECT_URI=https://<render-domain>/api/auth/google/callback` in Render and register the **identical URI** on the Google web OAuth client. The login-start request sets a first-party browser binding cookie through Next.js. FastAPI verifies state and PKCE, then redirects with a short-lived app ticket to `${FRONTEND_URL}/auth/complete`; the browser redeems it and navigates to `${FRONTEND_URL}/dashboard`.

If login fails, check redirect mismatch, test-user membership, enabled APIs, spreadsheet sharing permissions, and the encryption key. Google refresh tokens never enter localStorage, sessionStorage, or frontend JavaScript.

## 5. Webhook and fallback

After programme selection and initial sync, the app calls Drive `files.watch` with:

```text
https://<render-domain>/api/webhooks/google-drive
```

No manual webhook creation is needed. Google must reach this HTTPS URL without a login page or proxy authentication. The app validates the random channel token, stored channel ID, resource ID, expiry, and resource state. Notifications contain no class data: the backend rereads the sheet. Pending state commits before returning 202; a background task starts reconciliation. Concurrent tasks are serialized by a database advisory lock, and cron recovers work interrupted by restarts.

Channel ID, resource ID, and expiration live in PostgreSQL. Reconciliation renews watches within six hours of expiry, honors Google's returned expiration, and stops replaced channels. The initial `sync` notification can precede the registration response. See [Google Drive push notifications](https://developers.google.com/workspace/drive/api/guides/push).

Run independently if diagnosing registration:

```bash
python -m app.jobs.renew_google_watch
python -m app.jobs.sync_all
```

The fallback fetches every active source, validates/parses it, computes a canonical fingerprint, skips unchanged event writes, and checks watch renewal even when nothing changed. A source failure is logged and does not stop other sources. The job exits nonzero if any sync/renewal fails, allowing Render to report failure.

A message arriving during a sync can remain pending until the next cron; delivery is eventually consistent, not a guarantee of instant updates. Each user is currently an independent source. Scale later by moving `sync_source` into a queue worker; parser and diff logic do not require changes.

## 6. Testing deployment

Use a **copy** of the sheet accessible to your test Google account. Set the spreadsheet ID/GID before first sign-in; existing sources retain their configured ID. Changing the environment does not silently retarget existing users.

- [ ] Frontend loads on its public Vercel URL.
- [ ] API `/health` returns 200.
- [ ] `/health/db` returns 200; migrations are at head.
- [ ] Google login works from the production domain.
- [ ] Spreadsheet can be read; errors are visible rather than showing demo data.
- [ ] Programme is selectable.
- [ ] Section is selectable.
- [ ] College Timetable calendar is created.
- [ ] First sync succeeds and real events appear.
- [ ] Second sync makes no duplicate events.
- [ ] Changing a test row's room/time while keeping its ID triggers a sync.
- [ ] The existing calendar event changes; its Google event ID remains the same.
- [ ] Setting status to cancelled updates that event with `[CANCELLED]` and transparent availability.
- [ ] Restoring scheduled status restores that same event.
- [ ] Dashboard reports a registered active watch.
- [ ] A real Drive notification triggers reconciliation.
- [ ] Triggering Render cron reconciles a missed modification.
- [ ] An unchanged cron run does not write duplicate events.
- [ ] Google API failures leave existing calendar events intact and record a failed run.
- [ ] No secrets appear in tracked files.

Completion requires checking these against the public deployments; passing mocked tests alone is not sufficient.

## 7. CI and deployment gates

`.github/workflows/ci.yml` runs backend install/lint/migrations/tests with PostgreSQL and frontend install/lint/typecheck/build. In GitHub branch protection or repository rulesets, require the `backend` and `frontend` checks before merging to `main` and disallow bypasses as appropriate. Render uses `autoDeployTrigger: checksPass` ([Render deployment behavior](https://render.com/docs/deploys)).

Set Vercel's production branch to protected `main`. Feature branch previews may deploy independently of backend tests; only merge passing changes for production. Restrict manual production deployments to maintainers. YAML alone cannot enforce GitHub account-level branch protection.

## 8. Costs and operational boundaries

The Blueprint selects small paid Render resources to support durable PostgreSQL, cron, and migration pre-deploy steps. Review current [Render pricing](https://render.com/pricing) at creation; this architecture is cost-conscious, not guaranteed free. Vercel plan eligibility depends on intended use. No Redis, extra worker, Kubernetes, or persistent application disk is required.

Calendar updates are per-event and can partially succeed before a provider failure; the failed sync retries idempotently. Fingerprints skip unchanged sources, so manual edits/deletions inside Google Calendar are not automatically healed until the source changes. A deleted app calendar produces an error; automatic calendar recreation is intentionally not attempted during normal sync.

## 9. Render-only alternative and custom domains

Keep backend, PostgreSQL, and cron as above. Add a Node Web Service with root `frontend`, build `npm ci && npm run build`, start `npm start -- --port $PORT`, Node 22, and `NEXT_PUBLIC_API_URL` set to the backend public HTTPS URL. Set `FRONTEND_URL`/`ALLOWED_ORIGINS` to the new frontend URL. The frontend Dockerfile is also deployable as a Render Docker service.

For future custom domains, configure DNS and platform domains for `app.livetimetable.in` and `api.livetimetable.in`. Change `NEXT_PUBLIC_API_URL`, `FRONTEND_URL`, `BACKEND_URL`, `ALLOWED_ORIGINS`, and `GOOGLE_REDIRECT_URI`; update the authorized Google redirect URI and redeploy. Existing watch URLs are replaced at renewal; run the renewal job after expiring existing channels if immediate cutover is required. No source changes are necessary.

## Ready-to-use Render-only Blueprint

Use **`render-only.yaml`** as the Blueprint Path when deploying the entire app on Render. It provisions or adopts `CalendarApp`, `livetimetable-api`, `livetimetable-db`, and `livetimetable-sync-cron`. The frontend uses the tested standalone Docker image and receives its API URL from the API service's assigned Render URL.

The API still prompts for its frontend origin, backend URL, OAuth callback, and secrets. Set frontend origin/CORS to the assigned `CalendarApp` HTTPS URL. Register the assigned API callback URL on the Google OAuth client. The exact public hostnames must be checked after service creation; service names do not reserve domains.

For agent-assisted provisioning, place a Render API key in the ignored root `.env` as `RENDER_API_KEY=...`; do not send it in chat or commit it. Create the key in Render Account Settings. `RENDER_OWNER_ID` can optionally select a specific workspace when the account has more than one. These are deployment credentials, not application environment values, and must not be copied to the frontend or application services.

Excel files need Drive content access. Existing metadata-only Google connections show a **Reconnect Google** action to request the read-only content scope. Drive `files.watch` continues to detect changes to the original Excel file; no converted copy is created. Public OAuth verification must cover the requested Drive scope.
