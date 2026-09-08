# Timetable input contract

The supplied file is **Term- I Class Schedule MBA & MBAA-2026-28.xlsx**, an Excel workbook stored in Google Drive. The app downloads it through Drive using the signed-in account's read-only content permission. No public sharing or conversion is required.

## College section grid

The adapter recognizes the `Term-I` layout: a row of section headings followed by dated rows and four time columns per section. MBA contains sections A–D; MBA Analytics contains E–F, as indicated by the workbook's headings. Each numbered course session or quiz becomes a dated calendar event. Course codes remain in event titles and the original class text, including faculty details, is kept in the description.

- Cell-specific times override the column's normal time. Multiple numbered entries in one cell are parsed separately.
- Whole-cell or course-label strikethrough and explicit cancellation text mark the affected event cancelled.
- Classroom headings supply the default location; `CR-…` and `Online` override it.
- Room reservations, holidays, no-class days and exam-week banners are excluded because they do not specify individual timed classes.
- Unknown entries and ambiguous times pause synchronization rather than inventing class times.
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

The parser validates the whole sheet before touching any calendar. A malformed row, duplicated ID, missing tab, empty sheet, or unrecognized format stops the sync and records an error. Add a dedicated adapter for a different layout; preserve the normalized event contract and stable IDs. This boundary allows a grid/Excel adapter without changing OAuth, deployment, or synchronization.

## Excel input

Excel `.xlsx` files are read in memory with openpyxl (cached formula values, rich-text cancellation markers preserved, external links disabled). No source workbook is modified or converted. The app limits downloads to 25 MB, expanded workbook content to 100 MB, and cell allocation (including merged cells) and the selected worksheet to 250,000 cells.

For a workbook with one worksheet, that worksheet is used. For multiple worksheets, configure the exact `EXCEL_SHEET_NAME` on the API and cron; the app does not guess which tab is the timetable. Google’s Office-editor `gid` is not an Excel worksheet identifier. Native Google Sheets continues to use `GOOGLE_SHEET_GID`. Typed Excel dates and times normalize to the parser’s date/time contract.

Existing users who granted only `drive.metadata.readonly` must use **Reconnect Google** on the dashboard and consent to `drive.readonly`. This allows downloading Drive file content; the app reads the configured timetable.
