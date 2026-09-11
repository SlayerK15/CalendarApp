# Scaling and operating cadence

## Implemented

- Automatic reconciliation runs at minute 17 every six hours in UTC: `17 */6 * * *`. With Asia/Kolkata display time this is 05:47, 11:47, 17:47 and 23:47. Set `SYNC_INTERVAL_SECONDS=21600` on API and cron to match the displayed interval.
- `SYNC_ON_CHANGE=false` queues validated Drive notifications in PostgreSQL for the scheduled run. Initial connection and manual Sync now remain immediate. Set it to true only when immediate change-triggered sync is desired again.
- The cron reads subscriptions using keyset pagination in batches of 100. `SYNC_MAX_WORKERS=2` permits two independent users to reconcile concurrently, with a configurable maximum of four. Every user has a separate DB session, Google HTTP client and PostgreSQL advisory lock.
- Google HTTP connections are reused during reconciliation. Events retain deterministic IDs and unchanged fingerprints skip calendar writes.
- The dashboard polls every five minutes when idle and every ten seconds while an import is running. Hidden tabs do not poll; returning to the tab refreshes it.
- Drive watches are renewed at least twelve hours before expiry, allowing headroom for six-hour cron runs.
- PostgreSQL holds persistent state and pending work. No worker requires a persistent local filesystem.

These changes bound concurrency and memory; they are not a measured user-capacity guarantee. The current small Render plans and Google API quotas still constrain throughput. A large first import makes more API calls than an unchanged scheduled check.

## Growth checkpoints

Measure first-import duration, batch completion time, Google 429/5xx errors, DB connection use and memory. The six-hour batch must finish before the next scheduled run. Increase worker concurrency only within measured DB/Google limits. Before thousands of subscriptions, use a dedicated worker with durable per-user jobs, retry backoff, indexes based on query measurements and shared source parsing with access checks. Keep webhook HTTP handlers short.

Current independent subscriptions each read the timetable using that user's Google permission. A shared source cache must preserve authorization; do not return one user's private sheet contents to another user merely because file IDs match. The server-identity approach in `GOOGLE_VERIFICATION.md` is a candidate for a college-owned source after its owner approves access.

## Three-hour wake-up workflow

`.github/workflows/wake-services.yml` requests the public frontend and API health endpoint at minute 23 every three hours UTC. It can also run manually in GitHub Actions. It needs no repository or cloud secrets, has bounded timeouts/retries, and does not run a timetable synchronization.

This periodically wakes the free frontend. Render may put it back to sleep after fifteen idle minutes; the workflow does not provide continuous availability or an exact three-hours-after-idle timer. The API is already on a paid plan. GitHub schedules may run late and public-repository schedules may be disabled after sixty days without repository activity. An always-available frontend requires an appropriate always-on hosting plan or architecture.

Sources checked 11 September 2026: [Render free service behavior](https://render.com/docs/free), [GitHub scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
