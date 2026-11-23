"""Inspect shared timetable section assignments without writing calendar events."""

import json
from collections import Counter
import re
from types import SimpleNamespace
from urllib.parse import quote

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.google import Google
from app.master_timetable import reader_account
from app.models import Event, Source, User
from app.timetables import read_timetables
from app.batch_sync import latest_batch


def main():
    config = settings()
    config.validate_runtime()
    source = SimpleNamespace(spreadsheet_id=config.google_spreadsheet_id, sheet_gid=config.google_sheet_gid)
    with SessionLocal() as db, Google(db, reader_account(db)) as google:
        parsed = read_timetables(google, source)
        sources = list(db.scalars(select(Source).where(Source.active.is_(True))))
        users = {user.id: user for user in db.scalars(select(User))}
        batch = latest_batch(db)
        outcomes = batch.outcomes if batch else {}
        calendar_audits = []
        for item in sources:
            user = users.get(item.user_id)
            if (
                not user
                or user.email.strip().lower() != config.master_timetable_email.strip().lower()
                or not item.calendar_id
            ):
                continue
            stored = list(db.scalars(select(Event).where(Event.source_id == item.id)))
            remote_events = {}
            try:
                with Google(db, user) as calendar_google:
                    page_token = None
                    while True:
                        params = {
                            "maxResults": 2500,
                            "fields": "items(id,summary,location,start,end,status),nextPageToken",
                        }
                        if page_token:
                            params["pageToken"] = page_token
                        result = calendar_google.request(
                            "GET",
                            "https://www.googleapis.com/calendar/v3/calendars/"
                            + quote(item.calendar_id, safe="")
                            + "/events",
                            params=params,
                        )
                        remote_events.update({event["id"]: event for event in result.get("items", [])})
                        page_token = result.get("nextPageToken")
                        if not page_token:
                            break
                active_stored = [event for event in stored if not event.cancelled]
                missing = [event for event in active_stored if event.id not in remote_events]
                mismatched = []
                for event in active_stored:
                    remote = remote_events.get(event.id)
                    if not remote:
                        continue
                    payload = event.payload
                    if any(
                        remote.get(field) != payload.get(field)
                        for field in ("summary", "location")
                    ) or remote.get("start", {}).get("dateTime") != payload.get("start", {}).get("dateTime") or remote.get(
                        "end", {}
                    ).get("dateTime") != payload.get("end", {}).get("dateTime"):
                        mismatched.append(remote)
                calendar_audits.append({
                    "programme": item.programme,
                    "section": item.section,
                    "status": "readable",
                    "stored_active_events": len(active_stored),
                    "remote_active_events": sum(event.get("status") != "cancelled" for event in remote_events.values()),
                    "missing_from_google_calendar": len(missing),
                    "payload_mismatches": len(mismatched),
                    "remote_locations": dict(Counter(event.get("location", "") for event in remote_events.values() if event.get("status") != "cancelled")),
                })
            except httpx.HTTPStatusError as exc:
                calendar_audits.append({
                    "programme": item.programme,
                    "section": item.section,
                    "status": f"Google Calendar HTTP {exc.response.status_code}",
                })
            except Exception as exc:
                calendar_audits.append({
                    "programme": item.programme,
                    "section": item.section,
                    "status": type(exc).__name__,
                })
        section_headers = []
        for timetable in config.additional_timetables:
            if not timetable.enabled:
                continue
            rows = google.sheet(timetable)
            for row_index, row in enumerate(rows[:10], 1):
                for column_index, value in enumerate(row, 1):
                    label = str(value).strip()
                    if re.search(r"\bSection\s*-\s*[A-Z]\b", label, re.I):
                        section_headers.append({"row": row_index, "column": column_index, "label": label})

    counts = Counter((event["programme"], event["section"]) for event in parsed)
    locations = Counter(
        (event["programme"], event["section"], event["payload"].get("location", "")) for event in parsed
    )
    matches = [
        {
            "programme": event["programme"],
            "section": event["section"],
            "class": event["payload"]["summary"],
            "date": event["payload"]["start"]["dateTime"][:10],
            "start": event["payload"]["start"]["dateTime"][11:16],
            "end": event["payload"]["end"]["dateTime"][11:16],
        }
        for event in parsed
        if any(code in event["payload"]["description"] for code in ("MM-II-3", "BC-I-13"))
    ]
    print(json.dumps({
        "section_headers": section_headers,
        "main_account_calendar_audit": calendar_audits,
        "active_accounts": [
            {
                "is_main_account": users.get(item.user_id).email.strip().lower() == config.master_timetable_email.strip().lower()
                if users.get(item.user_id)
                else False,
                "programme": item.programme,
                "section": item.section,
                "calendar_created": bool(item.calendar_id),
                "last_batch_status": outcomes.get(item.id),
                "event_count": item.event_count,
            }
            for item in sources
        ],
        "locations_by_section": {
            f"{programme} / {section}": {location: count for (group, lane, location), count in locations.items() if (group, lane) == (programme, section)}
            for programme, section in sorted({(group, lane) for group, lane, _ in locations})
        },
        "events_by_section": {f"{programme} / {section}": count for (programme, section), count in sorted(counts.items())},
        "target_classes_by_section": matches,
        "issues": [
            {key: issue[key] for key in ("programme", "section", "row", "column", "message", "text")}
            for issue in parsed.issues
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
