import time
from contextlib import contextmanager
from urllib.parse import quote

import httpx

from app.config import settings
from app.excel import MAX_DOWNLOAD_BYTES, read_excel
from app.security import decrypt, encrypt

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEETS_MIME = "application/vnd.google-apps.spreadsheet"


class GooglePermissionRequired(ValueError):
    pass


class Google:
    def __init__(self, db, user):
        self.db, self.user = db, user
        self._client = None

    def __enter__(self):
        self._client = httpx.Client(timeout=30)
        return self

    def __exit__(self, *_):
        self._client.close()
        self._client = None

    @contextmanager
    def http(self):
        # Reuse TCP/TLS connections throughout each user's reconciliation.
        # Authorization remains a per-request header, never shared between users.
        if self._client is not None:
            yield self._client
        else:
            with httpx.Client(timeout=30) as client:
                yield client

    def access_token(self):
        token = decrypt(self.user.tokens)
        if token.get("expires_at", 0) < time.time() + 90:
            with self.http() as client:
                response = client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": settings().google_client_id,
                        "client_secret": settings().google_client_secret,
                        "refresh_token": token["refresh_token"],
                        "grant_type": "refresh_token",
                    },
                )
                response.raise_for_status()
                update = response.json()
            token.update(update)
            token["expires_at"] = time.time() + update["expires_in"]
            self.user.tokens = encrypt(token)
            self.db.commit()
        return token["access_token"]

    def request(self, method, url, **kwargs):
        with self.http() as client:
            response = client.request(method, url, headers={"Authorization": f"Bearer {self.access_token()}"}, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def sheet(self, source):
        try:
            return self._sheet(source)
        except httpx.HTTPStatusError as exc:
            try:
                error = exc.response.json().get("error", {})
                reasons = {item.get("reason") for item in error.get("details", [])}
            except (ValueError, AttributeError, TypeError):
                reasons = set()
            if "SERVICE_DISABLED" in reasons:
                service = "Google Sheets" if exc.request.url.host == "sheets.googleapis.com" else "Google Drive"
                raise ValueError(
                    f"Enable the {service} API in the Google Cloud project, then reload this page."
                ) from None
            if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in reasons:
                raise GooglePermissionRequired(
                    "Reconnect Google and allow read-only access to the timetable file."
                ) from None
            if exc.response.status_code in {401, 403}:
                raise ValueError(
                    "Google denied access to the timetable. Check that the signed-in account can view and download it."
                ) from None
            if exc.response.status_code == 404:
                raise ValueError(
                    "The timetable file was not found or is not shared with the signed-in Google account."
                ) from None
            raise

    def _sheet(self, source):
        file_url = f"https://www.googleapis.com/drive/v3/files/{quote(source.spreadsheet_id, safe='')}"
        file = self.request("GET", file_url, params={"fields": "mimeType", "supportsAllDrives": "true"})
        if file["mimeType"] == XLSX_MIME:
            scopes = set(decrypt(self.user.tokens).get("scope", "").split())
            if not scopes.intersection(
                {"https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive"}
            ):
                raise GooglePermissionRequired(
                    "Your timetable is an Excel workbook. Reconnect Google to grant read-only Drive access so its contents can be read."
                )
            content = self.download_excel(file_url)
            return read_excel(content, settings().excel_sheet_name)
        if file["mimeType"] != SHEETS_MIME:
            raise ValueError("Use a Google Sheets spreadsheet or an Excel .xlsx timetable.")
        base = f"https://sheets.googleapis.com/v4/spreadsheets/{quote(source.spreadsheet_id, safe='')}"
        metadata = self.request("GET", base, params={"fields": "sheets.properties"})
        title = next(
            (
                s["properties"]["title"]
                for s in metadata["sheets"]
                if str(s["properties"]["sheetId"]) == source.sheet_gid
            ),
            None,
        )
        if title is None:
            raise ValueError("Configured sheet tab was not found")
        range_name = "'" + title.replace("'", "''") + "'"
        return self.request(
            "GET", base + "/values/" + quote(range_name, safe=""), params={"valueRenderOption": "FORMATTED_VALUE"}
        ).get("values", [])

    def download_excel(self, file_url):
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        with self.http() as client:
            with client.stream(
                "GET", file_url, headers=headers, params={"alt": "media", "supportsAllDrives": "true"}, timeout=60
            ) as response:
                if response.is_error:
                    response.read()
                    response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > MAX_DOWNLOAD_BYTES:
                        raise ValueError("The Excel timetable is too large to read safely (25 MB limit).")
                    content.extend(chunk)
                return bytes(content)

    def calendar(self, source):
        # A source-specific marker recovers a calendar created before a process crash.
        marker = f"LiveTimetable source:{source.id}"
        page = None
        while True:
            result = self.request(
                "GET",
                "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                params={"pageToken": page} if page else {},
            )
            for item in result.get("items", []):
                if item.get("description") == marker:
                    return item["id"]
            page = result.get("nextPageToken")
            if not page:
                break
        result = self.request(
            "POST",
            "https://www.googleapis.com/calendar/v3/calendars",
            json={"summary": "College Timetable", "description": marker, "timeZone": settings().timetable_timezone},
        )
        return result["id"]

    def put_event(self, calendar_id, event_id, payload, deleted=False):
        url = f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events"
        if deleted:
            try:
                self.request("DELETE", f"{url}/{event_id}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {404, 410}:
                    raise
            return
        try:
            self.request("PUT", f"{url}/{event_id}", json=payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {404, 410}:
                raise
            try:
                self.request("POST", url, json={"id": event_id, **payload})
            except httpx.HTTPStatusError as conflict:
                if conflict.response.status_code != 409:
                    raise
                self.request("PUT", f"{url}/{event_id}", json=payload)
