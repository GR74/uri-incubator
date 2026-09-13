from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ROOT = Path(__file__).resolve().parents[1] / ".local"


class Settings(BaseSettings):
    """Environment-backed settings for the local URI backend."""

    model_config = SettingsConfigDict(env_prefix="URI_", extra="ignore")

    database_url: str | None = None
    artifact_root: Path = LOCAL_ROOT / "artifacts"
    staging_root: Path = LOCAL_ROOT / "staging"
    job_lease_seconds: int = Field(default=30, gt=0)
    job_poll_interval_seconds: float = Field(default=1.0, gt=0)
    job_heartbeat_interval_seconds: float | None = Field(default=None, gt=0)
    job_max_attempts: int = Field(default=3, gt=0)
    pilot_mode: bool = False
    approved_git_repository_roots: dict[str, list[Path]] = Field(default_factory=dict)
    conversation_stage_cleanup_seconds: int = 30
    generic_upload_max_bytes: int = 16 * 1024 * 1024
