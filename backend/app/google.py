import time
from urllib.parse import quote

import httpx

from app.config import settings
from app.security import decrypt, encrypt


class Google:
    def __init__(self, db, user):
        self.db, self.user = db, user

    def access_token(self):
        token = decrypt(self.user.tokens)
        if token.get("expires_at", 0) < time.time() + 90:
            with httpx.Client(timeout=30) as client:
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
        with httpx.Client(timeout=30) as client:
            response = client.request(method, url, headers={"Authorization": f"Bearer {self.access_token()}"}, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def sheet(self, source):
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
