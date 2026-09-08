from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "development"
    database_url: str = "sqlite:///./livetimetable.db"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    allowed_origins: str = "http://localhost:3000"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    google_spreadsheet_id: str = "1V5A1Z-PzrLs-92YCYmFA0L9fpwWbhVuN"
    google_sheet_gid: str = "129828207"
    google_webhook_secret: str = ""
    token_encryption_key: str = ""
    sync_interval_seconds: int = 300
    cancelled_event_behaviour: str = "mark_cancelled"
    timetable_timezone: str = "Asia/Kolkata"

    @property
    def production(self):
        return self.environment == "production"

    @property
    def origins(self):
        return [s.strip() for s in self.allowed_origins.split(",") if s.strip()]

    def validate_runtime(self):
        if self.cancelled_event_behaviour not in {"mark_cancelled", "delete"}:
            raise ValueError("CANCELLED_EVENT_BEHAVIOUR must be mark_cancelled or delete")
        if self.production:
            if not self.database_url.startswith(("postgresql", "postgres://")):
                raise ValueError("Production requires PostgreSQL")
            for value in (self.frontend_url, self.backend_url, self.google_redirect_uri):
                if not value.startswith("https://"):
                    raise ValueError("Production URLs must use HTTPS")
            if not self.origins or "*" in self.origins or any(not s.startswith("https://") for s in self.origins):
                raise ValueError("Production requires explicit HTTPS CORS origins")
            if not all((self.google_client_id, self.google_client_secret, self.google_webhook_secret)):
                raise ValueError("Missing Google configuration")
            Fernet(self.token_encryption_key.encode())


@lru_cache
def settings():
    return Settings()
