"""Inspect shared timetable section assignments without writing calendar events."""

import json
from collections import Counter
import re
from types import SimpleNamespace

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.google import Google
from app.master_timetable import reader_account
from app.models import Source, User
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
