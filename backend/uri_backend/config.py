from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ROOT = Path(__file__).resolve().parents[1] / ".local"
MODEL_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


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
    local_ai_enabled: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434"
    generation_model: str | None = None
    generation_model_digest: str | None = None
    embedding_model: str | None = None
    expected_embedding_dimension: int | None = Field(default=None, gt=0)
    ollama_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    @model_validator(mode="after")
    def require_local_ai_configuration(self) -> Settings:
        if self.local_ai_enabled:
            required = {
                "generation_model": self.generation_model,
                "generation_model_digest": self.generation_model_digest,
                "embedding_model": self.embedding_model,
                "expected_embedding_dimension": self.expected_embedding_dimension,
            }
            missing = [
                name
                for name, value in required.items()
                if value is None or (isinstance(value, str) and not value.strip())
            ]
            if missing:
                raise ValueError(
                    "local AI requires explicit " + ", ".join(missing)
                )
            assert self.generation_model_digest is not None
            if MODEL_DIGEST_PATTERN.fullmatch(self.generation_model_digest) is None:
                raise ValueError(
                    "generation_model_digest must be canonical sha256:<64 lowercase hex>"
                )
        return self
