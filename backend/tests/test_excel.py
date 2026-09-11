from datetime import date, time
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from openpyxl import Workbook

from app.config import settings
from app.excel import read_excel
from app.google import Google, GooglePermissionRequired, SHEETS_MIME, XLSX_MIME
from app.parser import parse_sheet
from app.security import encrypt


def workbook_bytes(multiple=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Timetable"
    sheet.append(["id", "programme", "section", "title", "date", "start_time", "end_time", "location"])
    sheet.append(["math-1", "MBA", "A", "Maths", date(2026, 9, 10), time(9), time(10), "101"])
    if multiple:
        workbook.create_sheet("Notes")
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def test_excel_preserves_typed_dates_times_and_stable_ids():
    rows = read_excel(workbook_bytes())
    event = parse_sheet(rows)[0]
    assert event["row_id"] == "math-1"
    assert event["payload"]["start"]["dateTime"] == "2026-09-10T09:00:00+05:30"
    assert event["payload"]["end"]["dateTime"] == "2026-09-10T10:00:00+05:30"


def test_excel_does_not_guess_among_multiple_tabs():
    content = workbook_bytes(multiple=True)
    with pytest.raises(ValueError, match="EXCEL_SHEET_NAME"):
        read_excel(content)
    assert len(read_excel(content, "Timetable")) == 2
    with pytest.raises(ValueError, match="not found"):
        read_excel(content, "Missing")


def test_invalid_workbook_and_oversized_input_rejected(monkeypatch):
    import app.excel as excel

    with pytest.raises(ValueError, match="xlsx"):
        read_excel(b"not a workbook")
    monkeypatch.setattr(excel, "MAX_DOWNLOAD_BYTES", 10)
    with pytest.raises(ValueError, match="too large"):
        read_excel(b"x" * 11)


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EXCEL_SHEET_NAME", "")
    settings.cache_clear()
    user = SimpleNamespace(tokens=encrypt({"scope": "https://www.googleapis.com/auth/drive.metadata.readonly"}))
    yield Google(None, user)
    settings.cache_clear()


def test_metadata_only_grant_requires_reconnect_for_excel(google, monkeypatch):
    monkeypatch.setattr(google, "request", lambda *a, **kw: {"mimeType": XLSX_MIME})
    monkeypatch.setattr(google, "download_excel", lambda *a: pytest.fail("Download requires content permission"))
    with pytest.raises(GooglePermissionRequired, match="Reconnect Google"):
        google.sheet(SimpleNamespace(spreadsheet_id="file", sheet_gid="129828207"))


def test_excel_uses_drive_download_instead_of_sheets_api(google, monkeypatch):
    google.user.tokens = encrypt({"scope": "https://www.googleapis.com/auth/drive.readonly"})
    calls = []

    def metadata(method, url, **kwargs):
        calls.append(url)
        return {"mimeType": XLSX_MIME}

    monkeypatch.setattr(google, "request", metadata)
    monkeypatch.setattr(google, "download_excel", lambda url: workbook_bytes())
    rows = google.sheet(SimpleNamespace(spreadsheet_id="file", sheet_gid="129828207"))
    assert parse_sheet(rows)[0]["programme"] == "MBA"
    assert all("sheets.googleapis.com" not in url for url in calls)


def test_native_google_sheet_still_uses_gid(google, monkeypatch):
    calls = []

    def provider(method, url, **kwargs):
        calls.append(url)
        if "drive/v3" in url:
            return {"mimeType": SHEETS_MIME}
        if "/values/" in url:
            return {"values": [["id"], ["sample"]]}
        return {"sheets": [{"properties": {"sheetId": 42, "title": "My Timetable"}}]}

    monkeypatch.setattr(google, "request", provider)
    assert google.sheet(SimpleNamespace(spreadsheet_id="file", sheet_gid="42")) == [["id"], ["sample"]]
    assert "My%20Timetable" in calls[-1]


def test_disabled_api_is_reported_actionably(google, monkeypatch):
    def provider(*args, **kwargs):
        request = httpx.Request("GET", "https://www.googleapis.com/drive/v3/files/file")
        response = httpx.Response(403, request=request, json={"error": {"details": [{"reason": "SERVICE_DISABLED"}]}})
        response.raise_for_status()

    monkeypatch.setattr(google, "request", provider)
    with pytest.raises(ValueError, match="Enable the Google Drive API"):
        google.sheet(SimpleNamespace(spreadsheet_id="file", sheet_gid="42"))


def test_google_reuses_connections_without_sharing_authorization(google, monkeypatch):
    import time

    original_client = httpx.Client
    clients, authorization = [], []

    def handle(request):
        authorization.append(request.headers["authorization"])
        return httpx.Response(200, json={"ok": True})

    def client_factory(**kwargs):
        client = original_client(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", client_factory)
    google.user.tokens = encrypt({"access_token": "test-first", "expires_at": time.time() + 3600})
    with google:
        google.request("GET", "https://www.googleapis.com/example")
        google.request("GET", "https://www.googleapis.com/example")
    other = SimpleNamespace(tokens=encrypt({"access_token": "test-second", "expires_at": time.time() + 3600}))
    with Google(None, other) as second:
        second.request("GET", "https://www.googleapis.com/example")
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)
    assert authorization == ["Bearer test-first", "Bearer test-first", "Bearer test-second"]
