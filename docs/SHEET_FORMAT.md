# Timetable input contract

## Central timetable reader

Production reads the workbook through `MASTER_TIMETABLE_EMAIL`, not through each student's Google grant. Configure the administrator's exact Google email on the API and in the GitHub Actions secret of the same name. Regular sign-in requests identity and Calendar permissions only.

Migration `0002` adds isolated encrypted reader credentials and shared parsed timetable snapshots; `0003` defers installing new reader grants until the browser-bound ticket exchange. Apply both with `alembic upgrade head`. On first use, an already-connected master's existing read-only Drive grant is copied into the isolated credential store. Otherwise the administrator signs in and uses **Connect timetable reader** on the dashboard. This separate flow verifies the configured email and browser binding, and never changes student Calendar credentials. Normal logins cannot overwrite reader credentials.

PostgreSQL caches parsed classes for five minutes (`TIMETABLE_CACHE_SECONDS=300`) across web processes and scheduled workers. A database advisory lock serializes refreshes. Manual calendar sync may use a snapshot up to five minutes old. Expired-cache failures stop calendar writes and preserve previous events; students are never asked to reconnect Drive. Cell-level quarantine diagnostics remain in cached snapshots. Calendar synchronization still runs every six hours.

Existing user Drive grants are not silently revoked. New authorization requests omit those scopes; users can remove their old Google grant and reconnect if desired. The OAuth project still declares scopes needed by the administrator flow. Direct source links may require college access even though viewing the timetable inside the app does not.

Per-user Drive instructions below describe the legacy development adapter. Production uses this central reader. Initialize and verify the master credential before removing its old grant.

The supplied file is **Term- I Class Schedule MBA & MBAA-2026-28.xlsx**, an Excel workbook stored in Google Drive. The app downloads it through Drive using the signed-in account's read-only content permission. No public sharing or conversion is required.

## College section grid

The adapter recognizes the `Term-I` layout: a row of section headings followed by dated rows and four time columns per section. MBA contains sections A–D; MBA Analytics contains E–F, as indicated by the workbook's headings. Each numbered course session or quiz becomes a dated calendar event. Course codes remain in event titles and the original class text, including faculty details, is kept in the description.

- Cell-specific times override the column's normal time. Multiple numbered entries in one cell are parsed separately.
- Term 2 dissertation labels such as `Dissertation Module-I-1` are numbered classes; they use the column time unless the cell specifies an override. Their faculty text, merged duration, and cancellation formatting are preserved like other classes.
- Course activities such as `OD-Make-up-Quiz`, `CF-Presentation`, and retake quizzes may omit a session number when they provide an explicit time range. Numbered activities keep using the normal slot when no override is supplied. Common dash, spacing, capitalisation and `a.m.`/`p.m.` variants are accepted.
- Whole-cell or course-label strikethrough and explicit cancellation text mark the affected event cancelled.
- Classroom headings supply the default location; `CR-…` and `Online` override it.
- Room reservations (including `B-1 Classroom Booked for TEDx`), holidays, no-class days and exam-week banners are excluded. A separate booking note's time does not override the preceding class's time.
- Unknown entries and ambiguous cell times preserve the last good calendar events for that programme/section in that file. Other sections and readable files continue syncing. The affected user sees a review warning with the file, row and column; programme/section choices stay available. No additions, moves, or inferred cancellations are made for the affected section until it is readable again.
- Section-level preservation is deliberate: skipping one cell could renumber repeated class labels and move the wrong calendar event. Partial runs leave the last complete-sync timestamp unchanged, retry at the normal scheduled/manual sync, and clear their warning after a complete read. Invalid structure, cross-section/date merges and source access failures still pause the entire sync.
- IDs use programme, section and numbered session/quiz labels. Dates, times, faculty and rooms can change without changing a unique session's ID. Repeated labels receive occurrence suffixes in grid order. Retain cancelled duplicates in place: removing or reordering indistinguishable duplicate labels can change their occurrence matching. A sheet with explicit permanent IDs avoids this ambiguity.

The adapter lives in `app/college_grid.py`; the flat-row format below remains supported for other timetables.

## Explicit row format

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

The parser validates the whole sheet before touching any calendar. A malformed explicit-format row, duplicated ID, missing tab, empty sheet, or unrecognized layout stops the sync and records an error. Recognized college grids isolate cell-level issues as described above. Add a dedicated adapter for a different layout; preserve the normalized event contract and stable IDs. This boundary allows a grid/Excel adapter without changing OAuth, deployment, or synchronization.

## Excel input

Excel `.xlsx` files are read in memory with openpyxl (cached formula values, rich-text cancellation markers preserved, external links disabled). No source workbook is modified or converted. The app limits downloads to 25 MB, expanded workbook content to 100 MB, and cell allocation (including merged cells) and the selected worksheet to 250,000 cells.

For a workbook with one worksheet, that worksheet is used. For multiple worksheets, configure the exact `EXCEL_SHEET_NAME` on the API and cron; the app does not guess which tab is the timetable. Google’s Office-editor `gid` is not an Excel worksheet identifier. Native Google Sheets continues to use `GOOGLE_SHEET_GID`. Typed Excel dates and times normalize to the parser’s date/time contract.

Existing users who granted only `drive.metadata.readonly` must use **Reconnect Google** on the dashboard and consent to `drive.readonly`. This allows downloading Drive file content; the app reads the configured timetable.

## Multiple timetable files

The original timetable remains configured with `GOOGLE_SPREADSHEET_ID` and `GOOGLE_SHEET_GID`. `ADDITIONAL_TIMETABLES` is a JSON array of objects with `spreadsheet_id`, `sheet_gid`, `label`, `enabled`, and optional `excel_sheet_name`. Enabled files use the same signed-in Google account and programme/section selection; their classes are combined in the existing College Timetable calendar.

For Excel files, set `excel_sheet_name` to that file's exact worksheet name when it differs from the primary workbook (for example, `"Term-II"`). Omitting it retains the global `EXCEL_SHEET_NAME`; an explicit empty string selects the sole worksheet and rejects ambiguous multi-tab workbooks. Set the same configuration on the API and cron. Worksheet names do not change existing event IDs; use a separate file entry for a new term rather than redirecting an imported term to another tab.

The active file is [Term 2 timetable](https://docs.google.com/spreadsheets/d/14B2j6u27W2OS4e1lXHMcBYZejYLy0nkt/edit?gid=129828207). It is now configured with `enabled: true`, while `PRIMARY_TIMETABLE_ENABLED=false` retires the original file. The account used for syncing only needs access to the active file. Expired Google grants still require reconnection before access and parsing can be validated.

The dashboard lists the primary file only when enabled, plus configured additional files. Additional classes receive file-specific hashed IDs so equal session labels in different workbooks cannot overwrite one another. The original event IDs remain unchanged. Additional files are read during the six-hour reconciliation and manual sync; Drive watch renewal stops when the primary file is retired. Additional files use scheduled and manual reconciliation.

All enabled files must be fetched and their structure validated before calendar writes begin. For a college grid with cell-level warnings, existing events from the affected selection/file are kept unchanged while readable files can reconcile. Removal guards run independently per readable file, so adding many new events in one file cannot hide a suspicious loss in another. Disabling or removing a file whose entries were already imported pauses sync rather than cancelling those entries. Make deliberate source-removal changes separately.

Retiring the primary file with `PRIMARY_TIMETABLE_ENABLED=false` intentionally excludes its rows from removal guards and reconciliation. Historical primary events remain in Google Calendar and the database but are hidden from the active timetable dashboard. Its spreadsheet ID remains unchanged as a legacy identity anchor. At least one additional file must be enabled. Removal guards still protect each active additional file, and removing an already imported additional file still pauses sync.
