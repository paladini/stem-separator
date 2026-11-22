"""Curated model catalog, output track definitions, and hardware capabilities."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TrackDefinition:
    """Plain-English track metadata for the user interface."""

    id: str
    label: str
    description: str
    icon: str


TRACK_DEFINITIONS: Dict[str, TrackDefinition] = {
    "vocals": TrackDefinition(
        id="vocals",
        label="Vocals",
        description="Main singing and voice",
        icon="🎤",
    ),
    "music": TrackDefinition(
        id="music",
        label="Music (Instrumental)",
        description="Accompaniment without vocals",
        icon="🎹",
    ),
    "drums": TrackDefinition(
        id="drums",
        label="Drums",
        description="Drums and percussion",
        icon="🥁",
    ),
    "bass": TrackDefinition(
        id="bass",
        label="Bass",
        description="Bass guitar and sub-bass",
        icon="🎸",
    ),
    "guitar": TrackDefinition(
        id="guitar",
        label="Guitar",
        description="Electric and acoustic guitars",
        icon="🪕",
    ),
    "piano": TrackDefinition(
        id="piano",
        label="Piano",
        description="Piano and keyboard parts",
        icon="🎼",
    ),
    "other": TrackDefinition(
        id="other",
        label="Other Instruments",
        description="Remaining instruments and synths",
        icon="🎵",
    ),
}


@dataclass(frozen=True)
class OutputFormatSpec:
    """Supported audio export format metadata."""

    id: str
    label: str
    extension: str
    mime_type: str
    lossless: bool
    description: str


OUTPUT_FORMATS: Dict[str, OutputFormatSpec] = {
    "WAV": OutputFormatSpec(
        id="WAV",
        label="WAV (Lossless)",
        extension="wav",
        mime_type="audio/wav",
        lossless=True,
        description="Uncompressed studio quality (largest file size)",
    ),
    "FLAC": OutputFormatSpec(
        id="FLAC",
        label="FLAC (Lossless Compressed)",
        extension="flac",
        mime_type="audio/flac",
        lossless=True,
        description="Lossless audio at roughly half the size of WAV",
    ),
    "MP3": OutputFormatSpec(
        id="MP3",
        label="MP3 (320 kbps)",
        extension="mp3",
        mime_type="audio/mpeg",
        lossless=False,
        description="Compact and compatible with every player",
    ),
}


@dataclass(frozen=True)
class CuratedModel:
    """Tested and verified separation model metadata."""

    id: str
    filename: str
    required_files: Tuple[str, ...]
    friendly_name: str
    architecture: str
    mode: str  # "vocals_music", "all_instruments", "extended_instruments"
    outputs: Tuple[str, ...]
    native_stems: Tuple[str, ...]
    synthesizes_music: bool
    download_size_mb: float
    cpu_recommended: bool
    gpu_recommended: bool
    speed_tier: str
    quality_tier: str
    summary: str
    license_info: str


CURATED_MODELS: Dict[str, CuratedModel] = {
    "vocals_music_fast": CuratedModel(
        id="vocals_music_fast",
        filename="UVR-MDX-NET-Inst_HQ_3.onnx",
        required_files=("UVR-MDX-NET-Inst_HQ_3.onnx",),
        friendly_name="MDX-Net Inst HQ 3 (Fast & Balanced)",
        architecture="MDX",
        mode="vocals_music",
        outputs=("vocals", "music"),
        native_stems=("Vocals", "Instrumental"),
        synthesizes_music=False,
        download_size_mb=63.7,
        cpu_recommended=True,
        gpu_recommended=True,
        speed_tier="Fast",
        quality_tier="High",
        summary="Recommended default for separating vocals and background music on both CPU and GPU.",
        license_info="MIT License (Ultimate Vocal Remover / Anjok07 & Kuielab MDX-Net)",
    ),
    "vocals_karaoke": CuratedModel(
        id="vocals_karaoke",
        filename="UVR_MDXNET_KARA_2.onnx",
        required_files=("UVR_MDXNET_KARA_2.onnx",),
        friendly_name="MDX-Net Karaoke 2 (Keep Backing Vocals)",
        architecture="MDX",
        mode="vocals_music",
        outputs=("vocals", "music"),
        native_stems=("Vocals", "Instrumental"),
        synthesizes_music=False,
        download_size_mb=50.3,
        cpu_recommended=True,
        gpu_recommended=True,
        speed_tier="Fast",
        quality_tier="High",
        summary="Lightweight model tuned for karaoke tracks where lead vocals are isolated cleanly.",
        license_info="MIT License (Ultimate Vocal Remover / Anjok07)",
    ),
    "vocals_music_hq": CuratedModel(
        id="vocals_music_hq",
        filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        required_files=(
            "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "model_bs_roformer_ep_317_sdr_12.9755.yaml",
        ),
        friendly_name="BS-Roformer Viperx 1297 (Maximum Quality)",
        architecture="MDXC",
        mode="vocals_music",
        outputs=("vocals", "music"),
        native_stems=("Vocals", "Instrumental"),
        synthesizes_music=False,
        download_size_mb=609.7,
        cpu_recommended=False,
        gpu_recommended=True,
        speed_tier="Slow on CPU / Fast on GPU",
        quality_tier="Studio Grade",
        summary="Top-scoring vocal and instrumental separator. Best with an NVIDIA GPU; slow on CPU.",
        license_info="MIT License (BS-Roformer / ViperX & lucidrains)",
    ),
    "instruments_4": CuratedModel(
        id="instruments_4",
        filename="htdemucs.yaml",
        required_files=("htdemucs.yaml", "955717e8-8726e21a.th"),
        friendly_name="Demucs v4 Hybrid Transformer (4-Track)",
        architecture="Demucs",
        mode="all_instruments",
        outputs=("vocals", "drums", "bass", "other", "music"),
        native_stems=("Vocals", "Drums", "Bass", "Other"),
        synthesizes_music=True,
        download_size_mb=80.2,
        cpu_recommended=True,
        gpu_recommended=True,
        speed_tier="Moderate",
        quality_tier="High",
        summary="Separates vocals, drums, bass, and other instruments, plus an optional combined music mix.",
        license_info="MIT License (Meta AI Research Demucs v4)",
    ),
    "instruments_6": CuratedModel(
        id="instruments_6",
        filename="htdemucs_6s.yaml",
        required_files=("htdemucs_6s.yaml", "5c90dfd2-34c22ccb.th"),
        friendly_name="Demucs v4 6-Source (Vocals, Drums, Bass, Guitar, Piano, Other)",
        architecture="Demucs",
        mode="extended_instruments",
        outputs=("vocals", "drums", "bass", "guitar", "piano", "other"),
        native_stems=("Vocals", "Drums", "Bass", "Guitar", "Piano", "Other"),
        synthesizes_music=False,
        download_size_mb=53.0,
        cpu_recommended=True,
        gpu_recommended=True,
        speed_tier="Moderate",
        quality_tier="Experimental (Guitar/Piano)",
        summary="Adds dedicated guitar and piano separation on top of vocals, drums, bass, and other.",
        license_info="MIT License (Meta AI Research Demucs v4 6s)",
    ),
}


@dataclass(frozen=True)
class SeparationPreset:
    """User-friendly separation goal shown on the primary interface."""

    id: str
    title: str
    subtitle: str
    icon: str
    default_tracks: Tuple[str, ...]
    cpu_default_model_id: str
    gpu_default_model_id: str


SEPARATION_PRESETS: Dict[str, SeparationPreset] = {
    "vocals_music": SeparationPreset(
        id="vocals_music",
        title="Vocals & Music",
        subtitle="Isolate the singer's voice and the instrumental backing track",
        icon="🎤",
        default_tracks=("vocals", "music"),
        cpu_default_model_id="vocals_music_fast",
        gpu_default_model_id="vocals_music_fast",
    ),
    "all_instruments": SeparationPreset(
        id="all_instruments",
        title="Drums, Bass, Vocals & Other",
        subtitle="Split a song into individual band instruments",
        icon="🥁",
        default_tracks=("vocals", "drums", "bass", "other"),
        cpu_default_model_id="instruments_4",
        gpu_default_model_id="instruments_4",
    ),
    "extended_instruments": SeparationPreset(
        id="extended_instruments",
        title="6 Instruments (with Guitar & Piano)",
        subtitle="Extract vocals, drums, bass, guitar, piano, and other instruments",
        icon="🎸",
        default_tracks=("vocals", "drums", "bass", "guitar", "piano", "other"),
        cpu_default_model_id="instruments_6",
        gpu_default_model_id="instruments_6",
    ),
}


def is_model_installed(model: CuratedModel, model_dir: Path) -> bool:
    """Return True if all required weight/config files exist and are non-empty in model_dir."""
    if not model_dir.exists():
        return False
    for req_file in model.required_files:
        candidate = model_dir / req_file
        if not candidate.is_file() or candidate.stat().st_size == 0:
            return False
    return True


def detect_hardware_info(output_dir: Path) -> Dict[str, object]:
    """Inspect PyTorch, ONNX Runtime, FFmpeg, and available disk space."""
    cuda_available = False
    device_name = "CPU"
    device = "cpu"
    onnx_providers: List[str] = ["CPUExecutionProvider"]

    try:
        import torch

        if torch.cuda.is_available():
            cuda_available = True
            device = "cuda"
            try:
                device_name = torch.cuda.get_device_name(0)
            except Exception:
                device_name = "NVIDIA CUDA GPU"
    except Exception:
        pass

    try:
        import onnxruntime as ort

        onnx_providers = list(ort.get_available_providers())
        if "CUDAExecutionProvider" in onnx_providers and not cuda_available:
            cuda_available = True
            device = "cuda"
            if device_name == "CPU":
                device_name = "NVIDIA GPU (ONNX Runtime CUDA)"
    except Exception:
        pass

    ffmpeg_available = shutil.which("ffmpeg") is not None

    free_disk_mb = 0
    try:
        target = output_dir if output_dir.exists() else output_dir.parent
        target.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(target)
        free_disk_mb = int(usage.free // (1024 * 1024))
    except Exception:
        free_disk_mb = 0

    return {
        "device": device,
        "device_name": device_name,
        "cuda_available": cuda_available,
        "onnx_providers": onnx_providers,
        "ffmpeg_available": ffmpeg_available,
        "free_disk_mb": free_disk_mb,
    }


def resolve_model_and_tracks(
    mode: Optional[str],
    model_id: Optional[str],
    requested_tracks: Optional[List[str]],
    cuda_available: bool = False,
) -> Tuple[CuratedModel, List[str]]:
    """
    Resolve and validate the separation model and output tracks.

    Raises ValueError with an explicit error code and message if invalid.
    """
    selected_model: Optional[CuratedModel] = None

    if model_id and model_id.strip() and model_id.strip().lower() != "auto":
        clean_id = model_id.strip()
        if clean_id not in CURATED_MODELS:
            supported = ", ".join(CURATED_MODELS.keys())
            raise ValueError(f"unsupported_model: Model '{clean_id}' is not in the supported catalog ({supported}).")
        selected_model = CURATED_MODELS[clean_id]
    else:
        clean_mode = (mode or "vocals_music").strip()
        if clean_mode not in SEPARATION_PRESETS:
            supported_modes = ", ".join(SEPARATION_PRESETS.keys())
            raise ValueError(f"unsupported_mode: Separation mode '{clean_mode}' is invalid ({supported_modes}).")
        preset = SEPARATION_PRESETS[clean_mode]
        chosen_id = preset.gpu_default_model_id if cuda_available else preset.cpu_default_model_id
        selected_model = CURATED_MODELS[chosen_id]

    if not requested_tracks:
        preset_for_model = SEPARATION_PRESETS.get(selected_model.mode)
        tracks = list(preset_for_model.default_tracks) if preset_for_model else list(selected_model.outputs)
    else:
        tracks = []
        for t in requested_tracks:
            slug = t.strip().lower()
            if slug and slug not in tracks:
                tracks.append(slug)

    if not tracks:
        raise ValueError("no_tracks_selected: Please select at least one output track to separate.")

    unsupported_tracks = [t for t in tracks if t not in selected_model.outputs]
    if unsupported_tracks:
        allowed_str = ", ".join(selected_model.outputs)
        bad_str = ", ".join(unsupported_tracks)
        raise ValueError(
            f"incompatible_tracks: Model '{selected_model.friendly_name}' cannot produce [{bad_str}]. "
            f"Supported outputs for this model: [{allowed_str}]."
        )

    return selected_model, tracks


def get_system_catalog_payload(model_dir: Path, output_dir: Path, max_upload_mb: int) -> Dict[str, object]:
    """Build the full `/api/system` response payload."""
    hw = detect_hardware_info(output_dir)

    tracks_payload = {
        k: {
            "id": v.id,
            "label": v.label,
            "description": v.description,
            "icon": v.icon,
        }
        for k, v in TRACK_DEFINITIONS.items()
    }

    formats_payload = [
        {
            "id": f.id,
            "label": f.label,
            "extension": f.extension,
            "mime_type": f.mime_type,
            "lossless": f.lossless,
            "description": f.description,
        }
        for f in OUTPUT_FORMATS.values()
    ]

    presets_payload = [
        {
            "id": p.id,
            "title": p.title,
            "subtitle": p.subtitle,
            "icon": p.icon,
            "default_tracks": list(p.default_tracks),
            "default_model_id": p.gpu_default_model_id if hw["cuda_available"] else p.cpu_default_model_id,
            "available_tracks": list(
                CURATED_MODELS[
                    p.gpu_default_model_id if hw["cuda_available"] else p.cpu_default_model_id
                ].outputs
            ),
        }
        for p in SEPARATION_PRESETS.values()
    ]

    models_payload = [
        {
            "id": m.id,
            "filename": m.filename,
            "friendly_name": m.friendly_name,
            "architecture": m.architecture,
            "mode": m.mode,
            "outputs": list(m.outputs),
            "download_size_mb": m.download_size_mb,
            "installed": is_model_installed(m, model_dir),
            "cpu_recommended": m.cpu_recommended,
            "gpu_recommended": m.gpu_recommended,
            "speed_tier": m.speed_tier,
            "quality_tier": m.quality_tier,
            "summary": m.summary,
            "license_info": m.license_info,
        }
        for m in CURATED_MODELS.values()
    ]

    return {
        **hw,
        "max_upload_mb": max_upload_mb,
        "tracks": tracks_payload,
        "formats": formats_payload,
        "presets": presets_payload,
        "models": models_payload,
    }
