"""Configuration management for Stem Separator via environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
        return max(minimum, value)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return Path(raw.strip()).resolve()


@dataclass(frozen=True)
class AppConfig:
    """Immutable application settings loaded from environment variables."""

    output_dir: Path
    model_dir: Path
    max_upload_mb: int
    max_duration_minutes: int
    min_free_disk_mb: int
    max_concurrent_jobs: int
    max_queue_size: int
    job_retention_hours: int
    host: str
    port: int


def get_config() -> AppConfig:
    """Resolve current configuration from environment variables."""
    default_output = PROJECT_ROOT / "data" / "output"
    default_models = PROJECT_ROOT / "data" / "models"

    output_dir = _env_path("STEM_SEPARATOR_OUTPUT_DIR", default_output)
    model_dir = _env_path(
        "AUDIO_SEPARATOR_MODEL_DIR",
        _env_path("STEM_SEPARATOR_MODEL_DIR", default_models),
    )

    return AppConfig(
        output_dir=output_dir,
        model_dir=model_dir,
        max_upload_mb=_env_int("STEM_SEPARATOR_MAX_UPLOAD_MB", 250, minimum=1),
        max_duration_minutes=_env_int("STEM_SEPARATOR_MAX_DURATION_MINUTES", 30, minimum=1),
        min_free_disk_mb=_env_int("STEM_SEPARATOR_MIN_FREE_DISK_MB", 500, minimum=0),
        max_concurrent_jobs=_env_int("STEM_SEPARATOR_MAX_CONCURRENT_JOBS", 1, minimum=1),
        max_queue_size=_env_int("STEM_SEPARATOR_MAX_QUEUE_SIZE", 5, minimum=1),
        job_retention_hours=_env_int("STEM_SEPARATOR_JOB_RETENTION_HOURS", 24, minimum=1),
        host=os.environ.get("STEM_SEPARATOR_HOST", "0.0.0.0"),
        port=_env_int("STEM_SEPARATOR_PORT", 7860, minimum=1),
    )
