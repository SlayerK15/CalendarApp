"""Combine configured timetables without changing existing calendar event IDs."""

import hashlib

from app.config import settings
from app.parser import guard_removals, parse_sheet


def timetable_prefix(timetable):
    identity = timetable.spreadsheet_id + ":" + timetable.sheet_gid
    return "external:" + hashlib.sha256(identity.encode()).hexdigest()[:20] + ":"


def additional_for(source, include_disabled=False):
    seen = {(source.spreadsheet_id, source.sheet_gid)}
    result = []
    for item in settings().additional_timetables:
        key = (item.spreadsheet_id, item.sheet_gid)
        if key not in seen and (item.enabled or include_disabled):
            seen.add(key)
            result.append(item)
    return result


def source_listing(source):
    files = ([(source, "Original timetable", True)] if settings().primary_timetable_enabled else []) + [
        (item, item.label, item.enabled) for item in additional_for(source, include_disabled=True)
    ]
    return [
        {
            "label": label,
            "url": f"https://docs.google.com/spreadsheets/d/{item.spreadsheet_id}/edit?gid={item.sheet_gid}",
            "enabled": enabled,
        }
        for item, label, enabled in files
    ]


def read_timetables(google, source):
    # Validate every enabled file before making any Google Calendar writes.
    events = parse_sheet(google.sheet(source), settings().timetable_timezone) if settings().primary_timetable_enabled else []
    for item in additional_for(source):
        incoming = parse_sheet(google.sheet(item), settings().timetable_timezone)
        prefix = timetable_prefix(item)
        for event in incoming:
            event["row_id"] = prefix + hashlib.sha256(event["row_id"].encode()).hexdigest()
            link = f"https://docs.google.com/spreadsheets/d/{item.spreadsheet_id}/edit?gid={item.sheet_gid}"
            event["payload"]["description"] += f"\n\n{item.label}: {link}"
        events.extend(incoming)
    if not events:
        raise ValueError("No enabled timetable contains classes; synchronization paused")
    return events


def managed_event(row_id):
    # Retired primary events remain as calendar history, outside reconciliation.
    return settings().primary_timetable_enabled or row_id.startswith("external:")


def guard_timetable_removals(source, existing, selected):
    prefixes = [timetable_prefix(item) for item in additional_for(source)]

    def group(row_id):
        if not row_id.startswith("external:"):
            return "primary"
        return next((prefix for prefix in prefixes if row_id.startswith(prefix)), "unconfigured")

    if any(group(row_id) == "unconfigured" for row_id in existing):
        raise ValueError("An imported timetable is disabled or removed. Sync is paused to protect its events.")
    groups = (["primary"] if settings().primary_timetable_enabled else []) + prefixes
    for name in groups:
        previous = sum(not event.cancelled and group(row_id) == name for row_id, event in existing.items())
        current = sum(group(event["row_id"]) == name for event in selected)
        guard_removals(previous, current)
