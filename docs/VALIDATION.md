# Validation record

Validated locally and on Render on 9 September 2026. This record distinguishes tested behavior from production acceptance that still needs a selected programme and section.

## Passed

- Frontend ESLint, TypeScript type checking, and Next.js 16.3.4 production build.
- Desktop (1440px) and mobile (390px) browser render checks: no JavaScript errors or horizontal overflow.
- Both Docker images build successfully; Compose starts frontend, API, and PostgreSQL.
- Backend suite: **44 tests pass locally**, with the PostgreSQL locking integration test skipped locally and configured to run in CI. The earlier 12-test baseline also passed inside the Python 3.12 Docker image with PostgreSQL 16.
- Stable event IDs across room changes, cancellation/restoration, repeated sync, and simulated crash after Google write.
- Failed sheet parsing and failed calendar writes do not advance successful fingerprints or trigger cancellation from missing input.
- Missing classes are marked cancelled; suspicious event-count drops abort.
- PostgreSQL advisory locks exclude concurrent connections and release for later work.
- OAuth ticket browser binding, single use, HttpOnly sessions, logout, CSRF Origin checks, and unauthenticated API rejection.
- Webhook token/resource/expiry validation and persisted pending state.
- Watch renewal stores provider expiration, stops the old channel, and skips healthy subscriptions.
- Alembic initial migration and schema drift checks on SQLite and PostgreSQL.
- `render.yaml` validates against the current JSON Schema fetched from `https://render.com/schema/render.yaml.json`.

## College Excel grid validation

The real workbook was read and parsed inside the Render backend without exporting its full contents or writing calendar events. All dated class cells passed validation: **878 unique event IDs**, **823 scheduled entries**, **55 cancellations**. Scheduled counts: MBA A 139, B 136, C 135, D 139; MBA Analytics E 137, F 137. The grid adapter uses the original worksheet's section labels, dates, time slots, rich-text strikethroughs and overrides.

Synthetic regression fixtures cover whole-cell and partial strikethrough cancellation, replacement classes sharing a slot, quizzes split across lines, observed time notations, room overrides, online classes, merged durations, duplicate labels, stable IDs after rescheduling, invalid dates and ambiguous entries. Test fixtures contain no workbook export or credentials.

## Still required before production sign-off

- Complete real Drive watch and Calendar integration tests after selecting a programme and section.
- Render deployment is now live; see `PRODUCTION.md`. Google OAuth sign-in and authenticated Excel reads have succeeded.
- Run the full public-deployment checklist in `DEPLOYMENT.md`, including real modification/cancellation, repeated synchronization, webhook notification, and fallback cron checks.
- Configure GitHub branch protection and verify Render/Vercel production deployment gates in the platform accounts.

The landing-page calendar is illustrative sample content. Unit tests mock Google APIs; they are not evidence of a successful live Google sync. Two deprecation warnings from the installed Starlette test client do not affect test results.

## OAuth recovery regression checks

Missing, unknown, expired, and reused callback state redirect to the frontend without contacting Google or creating a session. A mocked successful Google callback still redeems its browser-bound ticket correctly; replay is rejected. Fresh production authorization requests reach Google’s sign-in page.

## 11 September 2026 operating changes

Local checks pass for the six-hour scheduler, queued versus immediate webhook modes, paginated worker batches, failure isolation, per-user HTTP connection reuse, and frontend build. The GitHub wake workflow has no secrets or write permissions and requests only the frontend and API health endpoint. Public Google verification remains an external approval step; deployment of privacy/terms pages does not constitute Google approval.

Release `17a414b` passed GitHub CI and is live on all three Render services. The wake workflow successfully checked both URLs. Backend-only runtime diagnostics returned `21600` seconds, queued change notifications, two workers, and a healthy MBA Analytics F source with 139 scheduled events. The production cron smoke run completed at `2026-09-11T14:04:50Z`. No target-user load test has been performed; capacity planning awaits the intended student count.
