"""Inspect shared timetable section assignments without writing calendar events."""

import json
from collections import Counter
from types import SimpleNamespace

from app.config import settings
from app.db import SessionLocal
from app.google import Google
from app.master_timetable import reader_account
from app.timetables import read_timetables


def main():
    config = settings()
    config.validate_runtime()
    source = SimpleNamespace(spreadsheet_id=config.google_spreadsheet_id, sheet_gid=config.google_sheet_gid)
    with SessionLocal() as db, Google(db, reader_account(db)) as google:
        parsed = read_timetables(google, source)

    counts = Counter((event["programme"], event["section"]) for event in parsed)
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
        "events_by_section": {f"{programme} / {section}": count for (programme, section), count in sorted(counts.items())},
        "target_classes_by_section": matches,
        "issues": [
            {key: issue[key] for key in ("programme", "section", "row", "column", "message", "text")}
            for issue in parsed.issues
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
