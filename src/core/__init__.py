"""Core modules for Stem Separator."""

from .catalog import (
    CURATED_MODELS,
    OUTPUT_FORMATS,
    SEPARATION_PRESETS,
    TRACK_DEFINITIONS,
    CuratedModel,
    OutputFormatSpec,
    SeparationPreset,
    TrackDefinition,
    detect_hardware_info,
    get_system_catalog_payload,
    is_model_installed,
    resolve_model_and_tracks,
)
from .config import AppConfig, get_config
from .engine import SeparatorEngine
from .errors import SeparationError, classify_runtime_exception
from .job_manager import JobManager
from .validation import (
    ALLOWED_EXTENSIONS,
    AudioMetadata,
    check_free_disk_space,
    probe_and_validate_audio,
    resolve_safe_job_track_path,
    sanitize_display_filename,
    stream_upload_to_path,
    validate_extension,
)

__all__ = [
    "ALLOWED_EXTENSIONS",
    "AppConfig",
    "AudioMetadata",
    "CURATED_MODELS",
    "CuratedModel",
    "JobManager",
    "OUTPUT_FORMATS",
    "OutputFormatSpec",
    "SEPARATION_PRESETS",
    "SeparationError",
    "SeparationPreset",
    "SeparatorEngine",
    "TRACK_DEFINITIONS",
    "TrackDefinition",
    "check_free_disk_space",
    "classify_runtime_exception",
    "detect_hardware_info",
    "get_config",
    "get_system_catalog_payload",
    "is_model_installed",
    "probe_and_validate_audio",
    "resolve_model_and_tracks",
    "resolve_safe_job_track_path",
    "sanitize_display_filename",
    "stream_upload_to_path",
    "validate_extension",
]
