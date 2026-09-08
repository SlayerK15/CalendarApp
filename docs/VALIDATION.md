# Validation record

Validated locally and on Render on 9 September 2026. This record distinguishes tested behavior from production acceptance that still needs real credentials.

## Passed

- Frontend ESLint, TypeScript type checking, and Next.js 16.3.4 production build.
- Desktop (1440px) and mobile (390px) browser render checks: no JavaScript errors or horizontal overflow.
- Both Docker images build successfully; Compose starts frontend, API, and PostgreSQL.
- Backend suite: **12 tests pass**, including inside the Python 3.12 Docker image with PostgreSQL 16 available.
- Stable event IDs across room changes, cancellation/restoration, repeated sync, and simulated crash after Google write.
- Failed sheet parsing and failed calendar writes do not advance successful fingerprints or trigger cancellation from missing input.
- Missing classes are marked cancelled; suspicious event-count drops abort.
- PostgreSQL advisory locks exclude concurrent connections and release for later work.
- OAuth ticket browser binding, single use, HttpOnly sessions, logout, CSRF Origin checks, and unauthenticated API rejection.
- Webhook token/resource/expiry validation and persisted pending state.
- Watch renewal stores provider expiration, stops the old channel, and skips healthy subscriptions.
- Alembic initial migration and schema drift checks on SQLite and PostgreSQL.
- `render.yaml` validates against the current JSON Schema fetched from `https://render.com/schema/render.yaml.json`.

## Still required before production sign-off

- The provided spreadsheet returned 401 to anonymous export. Confirm its real layout from an accessible Excel/CSV sample and adapt the parser if it is not the documented row format.
- Configure Google Cloud OAuth and complete real login, refresh, Sheets read, Drive watch, and Calendar integration tests.
- Render deployment is now live; see `PRODUCTION.md`. Google OAuth callback registration still needs correction before live Google integration checks can finish.
- Run the full public-deployment checklist in `DEPLOYMENT.md`, including real modification/cancellation, repeated synchronization, webhook notification, and fallback cron checks.
- Configure GitHub branch protection and verify Render/Vercel production deployment gates in the platform accounts.

The landing-page calendar is illustrative sample content. Unit tests mock Google APIs; they are not evidence of a successful live Google sync. Two deprecation warnings from the installed Starlette test client do not affect test results.
