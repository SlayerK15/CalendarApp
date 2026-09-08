"""Adapter for the MBA/MBA Analytics dated section grid used by the college."""

import re
from collections import Counter
from datetime import date

HEADERS = ["id", "programme", "section", "title", "date", "start_time", "end_time", "location", "description", "status"]
SECTION = re.compile(r"Section\s*-\s*([A-Z])\b", re.I)
TIME_RANGE = re.compile(
    r"(?P<start>\d{1,2}[.:]\d{2}|\d{4})\s*(?P<start_ampm>[ap]m{1,2})?\s*"
    r"(?:to|[-–])\s*(?P<end>\d{1,2}[.:]\d{2}|\d{4})\s*(?P<end_ampm>[ap]m{1,2})?",
    re.I,
)
CLASS = re.compile(
    r"^[ \t]*(?:\[?cancelled\]?[ :\-]*)?"
    r"(?P<course>[A-Z]{2,}(?:[ \t]*-[ \t]*[IVX]+)?)"
    r"(?:[ \t]*[-–]?[ \t]*(?:\n[ \t]*)?(?P<kind>Quiz|Extra[ \t]+Session)[ \t]*[-–]?[ \t]*|[ \t]*[-–][ \t]*)"
    r"(?P<number>\d+(?:[ \t]*&[ \t]*\d+)?)\b",
    re.I | re.M,
)


def clock_time(value, ampm):
    digits = value.replace(".", ":")
    hours, minutes = map(int, digits.split(":")) if ":" in digits else (int(digits[:-2]), int(digits[-2:]))
    if not 0 <= minutes < 60 or not ampm or not 1 <= hours <= 12:
        raise ValueError("Unrecognized time in the college timetable")
    return f"{hours % 12 + (12 if ampm.lower().startswith('p') else 0):02d}:{minutes:02d}"


def time_range(value):
    matches = list(TIME_RANGE.finditer(value))
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("A timetable entry contains multiple time ranges; check its class labels")
    match = matches[0]
    start_ampm = match["start_ampm"] or match["end_ampm"]
    end_ampm = match["end_ampm"] or match["start_ampm"]
    start = clock_time(match["start"], start_ampm)
    end = clock_time(match["end"], end_ampm)
    if end <= start:
        raise ValueError("A college timetable entry ends before it starts")
    return start, end


def is_non_class(text):
    normalized = " ".join(text.split()).lower().strip("- .")
    return (
        not normalized
        or normalized.startswith("booked")
        or bool(re.search(r"\bno\b.*\bclasses\b", normalized))
        or bool(re.fullmatch(r"(?:mid|end)[- ]term exam week", normalized))
    )


def adapt_college_grid(values):
    """Return flat rows when the recognizable section/date layout is present."""
    section_row = next(
        (i for i, row in enumerate(values[:10]) if sum(bool(SECTION.search(str(v))) for v in row) >= 2),
        None,
    )
    if section_row is None or section_row + 1 >= len(values):
        return None
    labels, slots = values[section_row], values[section_row + 1]
    date_column = next((i for i, value in enumerate(slots) if str(value).strip().lower() == "date"), None)
    if date_column is None:
        return None
    columns = {}
    group = None
    for column in range(max(len(labels), len(slots))):
        label = str(labels[column]) if column < len(labels) else ""
        match = SECTION.search(label)
        if match:
            room = re.search(r"\((Classroom[^)]+)\)", label, re.I)
            group = (
                "MBA Analytics" if "analytics" in label.lower() else "MBA",
                match[1].upper(),
                " ".join(room[1].split()) if room else "",
            )
        slot = time_range(str(slots[column])) if column < len(slots) else None
        if group and slot:
            columns[column] = (*group, slot)
    if not columns:
        raise ValueError("The college timetable has no readable time slots")
    result, occurrences = [HEADERS], Counter()
    strike_spans = getattr(values, "strike_spans", {})
    merges = getattr(values, "merges", {})
    date_rows = 0
    for row_index, row in enumerate(values[section_row + 2 :], section_row + 2):
        raw_date = str(row[date_column]) if len(row) > date_column else ""
        try:
            day = date.fromisoformat(raw_date[:10]).isoformat()
        except ValueError:
            # Course/faculty legend and blank spacer rows follow the dated grid.
            if any(CLASS.search(str(row[c])) for c in columns if c < len(row)):
                raise ValueError(f"A class has an unreadable date at row {row_index + 1}")
            continue
        date_rows += 1
        for column, (programme, section, room, default_slot) in columns.items():
            text = str(row[column]) if column < len(row) else ""
            if not text.strip():
                continue
            matches = list(CLASS.finditer(text))
            if not matches:
                if is_non_class(text):
                    continue
                raise ValueError(f"Unrecognized timetable entry at row {row_index + 1}, column {column + 1}")
            if not is_non_class(text[: matches[0].start()]):
                raise ValueError(f"Unrecognized text before a class at row {row_index + 1}, column {column + 1}")
            default_active_used = False
            for index, match in enumerate(matches):
                stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                entry = text[match.start() : stop].strip(" \n\r\t-")
                course = re.sub(r"\s+", "", match["course"]).upper()
                kind = "-" + " ".join(match["kind"].title().split()) if match["kind"] else ""
                number = re.sub(r"\s+", "", match["number"])
                title = f"{course}{kind}-{number}"
                cancelled = bool(re.search(r"\bcancell?ed\b", entry, re.I)) or any(
                    start <= match.start("course") < end for start, end in strike_spans.get((row_index, column), [])
                )
                slot = time_range(entry)
                if slot is None:
                    if not cancelled and default_active_used:
                        raise ValueError(
                            f"An extra class needs its own time at row {row_index + 1}, column {column + 1}"
                        )
                    if not cancelled:
                        default_active_used = True
                    slot = default_slot
                    last_row, last_column = merges.get((row_index, column), (row_index, column))
                    if last_row != row_index:
                        raise ValueError("A merged class spans several dates; check the timetable")
                    if last_column != column:
                        if last_column not in columns or columns[last_column][:2] != (programme, section):
                            raise ValueError("A merged class spans multiple sections; check the timetable")
                        slot = (slot[0], columns[last_column][3][1])
                override = re.search(r"\bCR\s*-\s*([A-Z]\s*-?\s*\d+)\b", entry, re.I)
                location = "Online" if re.search(r"\bonline\b", entry, re.I) else room
                if override:
                    location = "Classroom " + re.sub(r"\s+", "", override[1]).upper()
                # Session numbers survive changes to date, time, faculty and room.
                # Repeated session labels remain separate occurrences, including cancellations.
                identity = f"grid:{programme}:{section}:{title}"
                occurrences[identity] += 1
                result.append(
                    [
                        f"{identity}:{occurrences[identity]}",
                        programme,
                        section,
                        title,
                        day,
                        *slot,
                        location,
                        entry,
                        "cancelled" if cancelled else "scheduled",
                    ]
                )
    if not date_rows or len(result) == 1:
        raise ValueError("No dated classes found in the college timetable; synchronization paused")
    return result
