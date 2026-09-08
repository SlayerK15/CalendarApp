# Timetable input contract

The supplied Google spreadsheet returned **401 Unauthorized** to the unauthenticated CSV export during implementation. Its actual cell layout has not been inspected. The parser currently supports the explicit row format below; do not claim compatibility with a weekly grid or merged-cell college timetable until a representative export has been supplied and an adapter tested.

The app reads the configured tab through the signed-in user's Google OAuth account. That account must have permission to view the spreadsheet. The sheet does not need to be public for the deployed app.

First row: unique headers (case-insensitive, surrounding spaces ignored).

| Column | Required | Format |
| --- | --- | --- |
| id | Yes | Unique, permanent class occurrence ID; must survive a move or cancellation |
| programme | Yes | Programme label shown in the selector |
| section | Yes | Section label shown in the selector |
| title | Yes | Class name |
| date | Yes | YYYY-MM-DD |
| start_time | Yes | 24-hour HH:MM |
| end_time | Yes | 24-hour HH:MM, later than start |
| location | No | Room or meeting location |
| description | No | Additional class details |
| status | No | scheduled or cancelled; blank means scheduled |

See `docs/sample-timetable.csv` for synthetic sample data. Each row is one dated occurrence, not a recurrence rule. Set Sheets date/time cell formatting to the formats above or store these as plain text. Timezone comes from `TIMETABLE_TIMEZONE` (Asia/Kolkata by default). The browser displays event times in its local timezone.

Do not derive IDs from row positions, room, or start time. Sorting or moving a class must not change its ID. Explicit cancelled rows are safest. Missing rows are marked cancelled only after a successful, valid read. An empty selection or a drop below half of more than ten previous active classes aborts changes. Small accidental deletions cannot be distinguished from intentional cancellations; prefer explicit statuses.

The parser validates the whole sheet before touching any calendar. A malformed row, duplicated ID, missing tab, empty sheet, or unrecognized format stops the sync and records an error. Adapt only `app/parser.py` for a different layout; preserve the normalized event contract and stable IDs. This boundary allows a grid/Excel adapter without changing OAuth, deployment, or synchronization.
