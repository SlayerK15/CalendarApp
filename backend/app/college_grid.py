"""Adapter for the MBA/MBA Analytics dated section grid used by the college."""

import re
from collections import Counter
from datetime import date

HEADERS = ["id", "programme", "section", "title", "date", "start_time", "end_time", "location", "description", "status"]
COURSE = r"Dissertation[ \t]+Module[ \t]*-[ \t]*[IVX]+|[A-Z]{2,}(?:[ \t]*-[ \t]*[IVX]+)?"
ACTIVITY = (
    r"(?:(?:Make[ \t-]*up|Re[ \t-]*take|Supplementary)[ \t-]+)?"
    r"(?:Quiz|Exam|Test|Presentation|Workshop|Tutorial|Viva|Lab|Lecture|Extra[ \t]+Session|Session)"
)
SECTION = re.compile(r"Section\s*-\s*([A-Z])\b", re.I)
TIME_RANGE = re.compile(
    r"(?P<start>\d{1,2}[.:]\d{2}|\d{4})\s*(?P<start_ampm>[ap]\.?m\.?m?)?\s*"
    r"(?:to|[-–—])\s*(?P<end>\d{1,2}[.:]\d{2}|\d{4})\s*(?P<end_ampm>[ap]\.?m\.?m?)?",
    re.I,
)
CLASS = re.compile(
    r"^[ \t]*(?:\[?cancell?ed\]?[ :\-]*)?"
    rf"(?P<course>{COURSE})"
    rf"(?:[ \t]*[-–]?[ \t]*(?:\n[ \t]*)?(?P<kind>{ACTIVITY})[ \t]*[-–]?[ \t]*|[ \t]*[-–][ \t]*)"
    r"(?P<number>\d+(?:[ \t]*&[ \t]*\d+)?)\b",
    re.I | re.M,
)
UNNUMBERED_CLASS = re.compile(
    r"^[ \t]*(?:\[?cancell?ed\]?[ :\-]*)?"
    rf"(?P<course>{COURSE})[ \t]*-[ \t]*(?P<kind>{ACTIVITY})[ \t]*$",
    re.I | re.M,
)
GUEST_CLASS = re.compile(
    r"^[ \t]*(?:\[?cancell?ed\]?[ :\-]*)?"
    rf"(?P<course>{COURSE})[ \t]*(?:-[ \t]*|\n[ \t]*)"
    r"(?P<kind>Guest[ \t]+Session)[ \t]*$",
    re.I | re.M,
)


class GridRows(list):
    def __init__(self):
        super().__init__([HEADERS])
        self.issues = []
        self.sections = set()


class GridStructureError(ValueError):
    """The affected dates or sections cannot be isolated safely."""


def class_matches(text):
    return sorted(
        [*CLASS.finditer(text), *UNNUMBERED_CLASS.finditer(text), *GUEST_CLASS.finditer(text)],
        key=lambda match: match.start(),
    )


def normalized_text(text):
    # One-character replacements retain the rich-text strikethrough offsets.
    return text.translate(str.maketrans({"–": "-", "—": "-", "‑": "-", "−": "-", "\xa0": " ", "\r": "\n"}))


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
    reservation = TIME_RANGE.sub("", normalized).strip(" ()-.")
    return (
        not normalized
        or reservation.startswith("booked")
        or bool(re.match(r"^(?:[a-z]\s*-?\s*\d+\s+)?(?:classroom|room)\s+(?:is\s+)?(?:booked|reserved)\b", reservation))
        or bool(re.search(r"\bno\b.*\bclasses\b", normalized))
        or bool(re.fullmatch(r"(?:mid|end)[- ]term exam week", normalized))
    )


def adapt_college_grid(values, *, tolerant=False):
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
    result, occurrences = GridRows(), Counter()
    result.sections = {item[:2] for item in columns.values()}
    strike_spans = getattr(values, "strike_spans", {})
    merges = getattr(values, "merges", {})
    dated_rows = {}
    for row_index in range(section_row + 2, len(values)):
        row = values[row_index]
        raw_date = str(row[date_column]) if len(row) > date_column else ""
        try:
            dated_rows[row_index] = date.fromisoformat(raw_date[:10]).isoformat()
        except ValueError:
            pass
    last_dated_row = max(dated_rows, default=-1)
    date_rows = 0
    for row_index, row in enumerate(values[section_row + 2 :], section_row + 2):
        day = dated_rows.get(row_index)
        if day is None:
            # Course/faculty legend and blank spacer rows follow the dated grid.
            texts = [normalized_text(str(row[c])) for c in columns if c < len(row)]
            if any(class_matches(text) for text in texts) or (
                row_index <= last_dated_row and any(not is_non_class(text) for text in texts)
            ):
                raise ValueError(f"A class has an unreadable date at row {row_index + 1}")
            continue
        date_rows += 1
        for column, (programme, section, room, default_slot) in columns.items():
            text = normalized_text(str(row[column])) if column < len(row) else ""
            if not text.strip():
                continue
            try:
                result.extend(
                    parse_cell(
                        text,
                        row_index,
                        column,
                        programme,
                        section,
                        room,
                        default_slot,
                        columns,
                        strike_spans,
                        merges,
                        occurrences,
                        day,
                    )
                )
            except ValueError as exc:
                if not tolerant or isinstance(exc, GridStructureError):
                    raise
                result.issues.append(
                    {
                        "programme": programme,
                        "section": section,
                        "row": row_index + 1,
                        "column": column + 1,
                        "message": str(exc),
                    }
                )
    if not date_rows or (len(result) == 1 and not result.issues):
        raise ValueError("No dated classes found in the college timetable; synchronization paused")
    # A skipped cell can alter ordinal IDs for repeated class labels anywhere in
    # this section. Preserve that section as a whole rather than guess identities.
    affected = {(issue["programme"], issue["section"]) for issue in result.issues}
    result[1:] = [row for row in result[1:] if (row[1], row[2]) not in affected]
    return result


def parse_cell(
    text, row_index, column, programme, section, room, default_slot, columns, strike_spans, merges, occurrences, day
):
    matches = class_matches(text)
    if not matches and is_non_class(text):
        return []
    last_row, last_column = merges.get((row_index, column), (row_index, column))
    if last_row != row_index:
        raise GridStructureError("A merged class spans several dates; check the timetable")
    if last_column != column and (last_column not in columns or columns[last_column][:2] != (programme, section)):
        raise GridStructureError("A merged class spans multiple sections; check the timetable")
    if not matches:
        raise ValueError(f"Unrecognized timetable entry at row {row_index + 1}, column {column + 1}")
    if not is_non_class(text[: matches[0].start()]):
        raise ValueError(f"Unrecognized text before a class at row {row_index + 1}, column {column + 1}")
    default_active_used = False
    entries = []
    for index, match in enumerate(matches):
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        entry = text[match.start() : stop].strip(" \n\r\t-")
        # A separated but unreadable follow-on entry must not disappear
        # into the preceding class's faculty/description text.
        parts = re.split(r"(?m)^[ \t]*[-._=•…]{3,}[ \t]*$", entry)
        if any(not is_non_class(part) for part in parts[1:]):
            raise ValueError(f"Unrecognized timetable entry at row {row_index + 1}, column {column + 1}")
        class_text = parts[0]
        course = re.sub(r"\s+", "", match["course"]).upper()
        if course.startswith("DISSERTATIONMODULE-"):
            course = "Dissertation Module-" + course.rsplit("-", 1)[1]
        kind_text = " ".join(match["kind"].title().split()) if match["kind"] else ""
        kind_text = re.sub(r"Make[ -]*Up[ -]+", "Make-up-", kind_text, flags=re.I)
        kind_text = re.sub(r"Re[ -]*Take[ -]+", "Retake-", kind_text, flags=re.I)
        kind = "-" + kind_text if kind_text else ""
        number = re.sub(r"\s+", "", match.groupdict().get("number") or "")
        title = f"{course}{kind}" + (f"-{number}" if number else "")
        cancelled = bool(re.search(r"\bcancell?ed\b", class_text, re.I)) or any(
            start <= match.start("course") < end for start, end in strike_spans.get((row_index, column), [])
        )
        slot = time_range(class_text)
        # The workbook places unnumbered guest sessions in ordinary class
        # columns. Quizzes and other unnumbered activities still need a time.
        if not number and slot is None and kind_text != "Guest Session":
            raise ValueError(f"An unnumbered activity needs its own time at row {row_index + 1}, column {column + 1}")
        if slot is None:
            if not cancelled and default_active_used:
                raise ValueError(f"An extra class needs its own time at row {row_index + 1}, column {column + 1}")
            if not cancelled:
                default_active_used = True
            slot = default_slot
            if last_column != column:
                slot = (slot[0], columns[last_column][3][1])
        override = re.search(r"\bCR\s*-\s*([A-Z]\s*-?\s*\d+)\b", class_text, re.I)
        location = "Online" if re.search(r"\bonline\b", class_text, re.I) else room
        if override:
            location = "Classroom " + re.sub(r"\s+", "", override[1]).upper()
        # Session numbers survive changes to date, time, faculty and room.
        # Repeated session labels remain separate occurrences, including cancellations.
        identity = f"grid:{programme}:{section}:{title}"
        occurrences[identity] += 1
        entries.append(
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
    return entries
