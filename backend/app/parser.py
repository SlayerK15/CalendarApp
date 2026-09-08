import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

REQUIRED = {"id", "programme", "section", "title", "date", "start_time", "end_time"}


def parse_sheet(values, timezone="Asia/Kolkata"):
    if not values:
        raise ValueError("Spreadsheet is empty; refusing to remove existing events")
    headers = [str(v).strip().lower() for v in values[0]]
    if len(set(headers)) != len(headers) or not REQUIRED.issubset(headers):
        raise ValueError("Expected unique headers: " + ", ".join(sorted(REQUIRED)))
    events, seen = [], set()
    for number, cells in enumerate(values[1:], 2):
        if not any(str(v).strip() for v in cells):
            continue
        row = dict(zip(headers, [str(v).strip() for v in cells]))
        if any(not row.get(k) for k in REQUIRED):
            raise ValueError(f"Row {number}: missing required field")
        if row["id"] in seen:
            raise ValueError(f"Row {number}: duplicate stable id")
        seen.add(row["id"])
        try:
            start = datetime.strptime(f"{row['date']} {row['start_time']}", "%Y-%m-%d %H:%M").replace(
                tzinfo=ZoneInfo(timezone)
            )
            end = datetime.strptime(f"{row['date']} {row['end_time']}", "%Y-%m-%d %H:%M").replace(
                tzinfo=ZoneInfo(timezone)
            )
        except ValueError as exc:
            raise ValueError(f"Row {number}: use YYYY-MM-DD and HH:MM") from exc
        if end <= start:
            raise ValueError(f"Row {number}: end must be after start")
        status = row.get("status", "").lower()
        if status not in {"", "scheduled", "cancelled", "canceled"}:
            raise ValueError(f"Row {number}: invalid status")
        events.append(
            {
                "row_id": row["id"],
                "programme": row["programme"],
                "section": row["section"],
                "cancelled": status in {"cancelled", "canceled"},
                "payload": {
                    "summary": row["title"],
                    "location": row.get("location", ""),
                    "description": row.get("description", ""),
                    "start": {"dateTime": start.isoformat(), "timeZone": timezone},
                    "end": {"dateTime": end.isoformat(), "timeZone": timezone},
                },
            }
        )
    return events


def fingerprint(events):
    return hashlib.sha256(json.dumps(sorted(events, key=lambda e: e["row_id"]), sort_keys=True).encode()).hexdigest()


def guard_removals(previous, current):
    if previous and not current:
        raise ValueError("No matching classes found; refusing to cancel all events. Use explicit cancelled rows.")
    if previous > 10 and current < previous * 0.5:
        raise ValueError("Suspicious drop in class count; synchronization paused")
