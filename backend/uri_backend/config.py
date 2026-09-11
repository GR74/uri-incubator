from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ROOT = Path(__file__).resolve().parents[1] / ".local"


class Settings(BaseSettings):
    """Environment-backed settings for the local URI backend."""

    model_config = SettingsConfigDict(env_prefix="URI_", extra="ignore")

    database_url: str | None = None
    artifact_root: Path = LOCAL_ROOT / "artifacts"
    staging_root: Path = LOCAL_ROOT / "staging"
    job_lease_seconds: int = 30
    job_poll_interval_seconds: float = 1.0
    job_max_attempts: int = 3
    pilot_mode: bool = False
