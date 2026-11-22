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

__all__ = [
    "AppConfig",
    "CURATED_MODELS",
    "CuratedModel",
    "OUTPUT_FORMATS",
    "OutputFormatSpec",
    "SEPARATION_PRESETS",
    "SeparationPreset",
    "TRACK_DEFINITIONS",
    "TrackDefinition",
    "detect_hardware_info",
    "get_config",
    "get_system_catalog_payload",
    "is_model_installed",
    "resolve_model_and_tracks",
]
