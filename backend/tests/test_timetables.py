import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.timetables import additional_for, guard_timetable_removals, read_timetables, source_listing, timetable_prefix

HEADER = ["id", "programme", "section", "title", "date", "start_time", "end_time"]
ROW = ["ME-1", "MBA Analytics", "F", "Economics", "2026-10-01", "09:15", "10:30"]


@pytest.fixture
def multiple(monkeypatch):
    monkeypatch.setenv(
        "ADDITIONAL_TIMETABLES",
        json.dumps(
            [
                {"spreadsheet_id": "second", "sheet_gid": "42", "label": "Second timetable"},
            ]
        ),
    )
    settings.cache_clear()
    yield SimpleNamespace(spreadsheet_id="first", sheet_gid="0")
    settings.cache_clear()


class Reader:
    def __init__(self):
        self.calls = []
        self.fail_second = False

    def sheet(self, source):
        self.calls.append(source.spreadsheet_id)
        if source.spreadsheet_id == "second" and self.fail_second:
            raise ValueError("Second timetable is unavailable")
        return [HEADER, ROW.copy()]


def test_both_files_are_read_and_colliding_labels_keep_distinct_stable_ids(multiple):
    reader = Reader()
    events = read_timetables(reader, multiple)
    assert reader.calls == ["first", "second"]
    assert len(events) == 2
    assert events[0]["row_id"] == "ME-1"
    assert events[1]["row_id"] != events[0]["row_id"]
    assert "second/edit?gid=42" in events[1]["payload"]["description"]
    assert read_timetables(reader, multiple)[1]["row_id"] == events[1]["row_id"]


def test_pending_file_is_listed_but_does_not_interrupt_existing_reads(multiple, monkeypatch):
    monkeypatch.setenv(
        "ADDITIONAL_TIMETABLES",
        json.dumps(
            [
                {"spreadsheet_id": "second", "sheet_gid": "42", "enabled": False},
            ]
        ),
    )
    settings.cache_clear()
    reader = Reader()
    assert len(read_timetables(reader, multiple)) == 1
    assert reader.calls == ["first"]
    assert [item["enabled"] for item in source_listing(multiple)] == [True, False]


def test_duplicate_file_configuration_does_not_duplicate_events(multiple, monkeypatch):
    monkeypatch.setenv(
        "ADDITIONAL_TIMETABLES",
        json.dumps(
            [
                {"spreadsheet_id": "first", "sheet_gid": "0"},
                {"spreadsheet_id": "second", "sheet_gid": "42"},
                {"spreadsheet_id": "second", "sheet_gid": "42"},
            ]
        ),
    )
    settings.cache_clear()
    assert len(read_timetables(Reader(), multiple)) == 2


def test_one_unreadable_file_aborts_combined_read(multiple):
    reader = Reader()
    reader.fail_second = True
    with pytest.raises(ValueError, match="unavailable"):
        read_timetables(reader, multiple)


def test_new_file_cannot_mask_suspicious_loss_in_original(multiple):
    prefix = timetable_prefix(additional_for(multiple)[0])
    existing = {f"old-{i}": SimpleNamespace(cancelled=False) for i in range(20)}
    selected = [{"row_id": f"old-{i}"} for i in range(4)] + [{"row_id": prefix + str(i)} for i in range(100)]
    with pytest.raises(ValueError, match="Suspicious drop"):
        guard_timetable_removals(multiple, existing, selected)


def test_disabling_imported_file_does_not_cancel_its_existing_events(multiple):
    existing = {"external:unconfigured:file-event": SimpleNamespace(cancelled=False)}
    with pytest.raises(ValueError, match="protect its events"):
        guard_timetable_removals(multiple, existing, [{"row_id": "primary-event"}])


def test_retiring_primary_reads_only_second_and_preserves_its_ids(multiple, monkeypatch):
    original_id = read_timetables(Reader(), multiple)[1]["row_id"]
    monkeypatch.setenv("PRIMARY_TIMETABLE_ENABLED", "false")
    settings.cache_clear()
    reader = Reader()
    events = read_timetables(reader, multiple)
    assert reader.calls == ["second"]
    assert [event["row_id"] for event in events] == [original_id]
    assert len(source_listing(multiple)) == 1
    assert "second/edit" in source_listing(multiple)[0]["url"]
    existing = {f"primary-{i}": SimpleNamespace(cancelled=False) for i in range(100)}
    guard_timetable_removals(multiple, existing, events)


def test_retiring_primary_keeps_second_file_removal_guard(multiple, monkeypatch):
    monkeypatch.setenv("PRIMARY_TIMETABLE_ENABLED", "false")
    settings.cache_clear()
    prefix = timetable_prefix(additional_for(multiple)[0])
    existing = {prefix + str(i): SimpleNamespace(cancelled=False) for i in range(20)}
    with pytest.raises(ValueError, match="Suspicious drop"):
        guard_timetable_removals(multiple, existing, [{"row_id": prefix + "0"}])


def test_retiring_every_file_is_rejected(multiple, monkeypatch):
    monkeypatch.setenv("PRIMARY_TIMETABLE_ENABLED", "false")
    monkeypatch.setenv("ADDITIONAL_TIMETABLES", "[]")
    settings.cache_clear()
    with pytest.raises(ValueError, match="Enable at least one"):
        settings().validate_runtime()
    with pytest.raises(ValueError, match="No enabled timetable"):
        read_timetables(Reader(), multiple)
