"""Application settings, read from environment variables prefixed ``DOMUS_``."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "domus"


class Settings(BaseSettings):
    """Runtime configuration.

    ``data_dir`` holds the SQLite database, blobs, and local backups, so copying
    that one folder with the app stopped is also a valid manual backup.
    """

    model_config = SettingsConfigDict(env_prefix="DOMUS_", env_file=None)

    data_dir: Path = Field(default_factory=_default_data_dir)
    database_url: str | None = None
    # Session cookies are marked Secure unless explicitly disabled for plain
    # http on localhost during development.
    cookie_secure: bool = True
    session_days: int = 14
    login_max_failures: int = 5
    login_window_seconds: int = 300
    # Largest total uncompressed size a backup archive may expand to (zip-bomb guard).
    backup_max_bytes: int = 2 * 1024**3
    # The sample home dataset that Admins can load from the web interface. Unset
    # means examples/sample-home in a source checkout; the Docker image sets it.
    sample_data_dir: Path | None = None

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "domus.sqlite"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def blobs_dir(self) -> Path:
        return self.data_dir / "blobs"

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.sqlite_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
