# Render production deployment

Deployed 9 September 2026 from `SlayerK15/CalendarApp`, branch `main`.

| Resource | URL or ID | Configuration |
| --- | --- | --- |
| Frontend: CalendarApp | https://calendarapp-2r1h.onrender.com | Existing free Docker web service, `frontend` root |
| API: livetimetable-api | https://livetimetable-api.onrender.com | Python web service, 0.5 CPU / 512 MB |
| Database: livetimetable-db | dpg-dag8cd67bikc73945h80-a | PostgreSQL 16, 0.1 CPU / 256 MB, 5 GB |
| Sync: livetimetable-sync-cron | crn-dag8huht0dsc73ecar8g | Python cron, 0.5 CPU / 512 MB, every five minutes |

All resources are in Singapore. The existing frontend, API, and database were reused. A missing cron was added. All three services have `autoDeployTrigger=checksPass`. `render-only.yaml` matches the existing frontend name and free plan to avoid creating a duplicate frontend or upgrading its plan on a future Blueprint sync.

Application secrets were sent directly from the ignored local `.env` to Render environment variables. The Render API key is not an application environment variable and was not copied into any service. No secrets are included in this record or Git-tracked environment files.

## Verified publicly

- Frontend returns HTTP 200, loads its assets, and renders without browser JavaScript errors.
- Mobile viewport has no horizontal overflow.
- Signed-out dashboard redirects to sign-in.
- API `/health` returns HTTP 200 with `{"status":"ok"}`.
- API `/health/db` returns HTTP 200 with `{"status":"ok"}`.
- Production PostgreSQL migration version is `0001`.
- Google login-start returns 200 and uses PKCE S256.
- Login binding cookie is Secure, HttpOnly, and SameSite=Lax.
- Frontend, API, and cron deployments report `live`.
- Cron smoke test completed successfully; Render reports last success at `2026-09-08T22:17:38Z` (9 September in Asia/Kolkata).

## Google OAuth status

The production callback is now accepted: a fresh login request reaches Google’s sign-in page. The configured **Authorized redirect URI** is:

```text
https://livetimetable-api.onrender.com/api/auth/google/callback
```

Start login from the frontend’s **Connect with Google** button. Opening the callback URL directly or reusing an expired/consumed OAuth state cannot authenticate a user. The app redirects these requests to the sign-in page with a retry message; it continues to reject invalid state without exchanging Google codes. Google tokens stay backend-side.

Google sign-in and read-only Drive content consent have succeeded. Authenticated diagnostics identified the source as `Term- I Class Schedule MBA & MBAA-2026-28.xlsx`; the app downloads this original Office file through Drive because Sheets API cannot read it.

The real `Term-I` grid was validated inside Render on 9 September 2026: **878 unique event IDs, 823 scheduled entries, 55 cancellations**, with scheduled dates from 6 July to 18 September 2026. The worksheet also contains untimed holidays and exam-week banners through 27 September; those do not become invented timed events. Available sections are MBA A–D and MBA Analytics E–F. Strikethroughs, replacement classes, additional quizzes, explicit times and room overrides are handled; see `SHEET_FORMAT.md`.

The source was still inactive during this validation. User programme/section selection, real calendar creation, repeat sync without duplicates, modification/cancellation propagation, and real Drive webhook delivery remain to be verified. The earlier cron smoke test checked execution and database access, not a real Google synchronization.
