"""Isolated adapter around python-audio-separator with channel/sample-rate preservation and error mapping."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import soundfile as sf

from .catalog import (
    OUTPUT_FORMATS,
    TRACK_DEFINITIONS,
    CuratedModel,
    detect_hardware_info,
    is_model_installed,
)
from .errors import SeparationError, classify_runtime_exception
from .validation import AudioMetadata

logger = logging.getLogger(__name__)

# Canonical mapping from audio-separator output stem names to our UI track ids
STEM_TO_TRACK_ID: Dict[str, str] = {
    "vocals": "vocals",
    "instrumental": "music",
    "no vocals": "music",
    "drums": "drums",
    "bass": "bass",
    "guitar": "guitar",
    "piano": "piano",
    "other": "other",
}


class SeparatorEngine:
    """Isolated separation adapter wrapping audio_separator.separator.Separator."""

    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir).resolve()
        self.model_dir.mkdir(parents=True, exist_ok=True)

    def resolve_execution_device(self, device_preference: str, output_dir: Path) -> str:
        """
        Determine whether the job runs on 'cpu' or 'cuda'.
        Raises SeparationError if 'cuda' was explicitly requested but no CUDA device is available.
        """
        pref = (device_preference or "auto").strip().lower()
        hw = detect_hardware_info(output_dir)
        cuda_ok = bool(hw["cuda_available"])

        if pref == "cuda":
            if not cuda_ok:
                raise SeparationError(
                    code="gpu_unavailable",
                    title="NVIDIA GPU not detected",
                    message="You selected 'Require NVIDIA GPU (CUDA)', but no compatible CUDA GPU or driver was detected on this server.",
                    suggestion="Change Processing Device to 'Automatic' or 'Force CPU' in Advanced Settings.",
                    http_status=400,
                )
            return "cuda"
        if pref == "cpu":
            return "cpu"
        return "cuda" if cuda_ok else "cpu"

    def run_separation(
        self,
        input_path: Path,
        tracks_dir: Path,
        model_spec: CuratedModel,
        output_format: str,
        selected_tracks: List[str],
        input_metadata: AudioMetadata,
        device_preference: str = "auto",
        on_stage_change: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, object]]:
        """
        Execute audio separation in a temporary working folder, post-process requested tracks
        (including synthesized instrumental for 4-stem models and mono channel restoration),
        export to tracks_dir, and verify every output file exists and is non-empty.
        """
        fmt_key = (output_format or "WAV").strip().upper()
        if fmt_key not in OUTPUT_FORMATS:
            fmt_key = "WAV"
        fmt_spec = OUTPUT_FORMATS[fmt_key]

        device_used = self.resolve_execution_device(device_preference, tracks_dir)
        tracks_dir.mkdir(parents=True, exist_ok=True)

        model_already_cached = is_model_installed(model_spec, self.model_dir)
        if on_stage_change:
            on_stage_change("separating" if model_already_cached else "downloading_model")

        with tempfile.TemporaryDirectory(prefix="stem-sep-work-") as work_dir_str:
            work_dir = Path(work_dir_str)
            try:
                raw_outputs = self._invoke_audio_separator(
                    input_path=input_path,
                    work_dir=work_dir,
                    model_spec=model_spec,
                    selected_tracks=selected_tracks,
                    input_metadata=input_metadata,
                    device_used=device_used,
                    on_stage_change=on_stage_change,
                )
            except Exception as exc:
                logger.error("Separator engine error for model %s: %s", model_spec.filename, exc, exc_info=True)
                raise classify_runtime_exception(exc, model_spec.friendly_name) from exc

            if on_stage_change:
                on_stage_change("exporting")

            try:
                published_tracks = self._finalize_and_export_tracks(
                    raw_outputs=raw_outputs,
                    tracks_dir=tracks_dir,
                    selected_tracks=selected_tracks,
                    model_spec=model_spec,
                    fmt_spec=fmt_spec,
                    input_metadata=input_metadata,
                )
            except Exception as exc:
                logger.error("Track export error: %s", exc, exc_info=True)
                raise classify_runtime_exception(exc, model_spec.friendly_name) from exc

        return published_tracks

    def _invoke_audio_separator(
        self,
        input_path: Path,
        work_dir: Path,
        model_spec: CuratedModel,
        selected_tracks: List[str],
        input_metadata: AudioMetadata,
        device_used: str,
        on_stage_change: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Path]:
        """Instantiate audio_separator.separator.Separator, load model, and run separate()."""
        from audio_separator.separator import Separator

        # If only a single native track is requested (and we don't need to synthesize 'music' from 3 stems),
        # we can pass output_single_stem to save export work.
        single_stem: Optional[str] = None
        if len(selected_tracks) == 1:
            only_track = selected_tracks[0]
            if only_track == "vocals":
                single_stem = "Vocals"
            elif only_track == "music" and not model_spec.synthesizes_music:
                single_stem = "Instrumental"
            elif only_track in ("drums", "bass", "guitar", "piano", "other"):
                single_stem = only_track.capitalize()

        # Use WAV inside the working directory so any channel conversion or stem mixing is lossless
        target_sr = input_metadata.sample_rate if input_metadata.sample_rate > 0 else 44100
        chunk_duration = 600 if input_metadata.duration_seconds > 1800 else None

        sep = Separator(
            log_level=logging.INFO,
            model_file_dir=str(self.model_dir),
            output_dir=str(work_dir),
            output_format="WAV",
            output_single_stem=single_stem,
            sample_rate=target_sr,
            use_soundfile=True,
            use_autocast=(device_used == "cuda"),
            chunk_duration=chunk_duration,
        )

        # Enforce CPU if requested by user even on a machine with CUDA
        if device_used == "cpu":
            import torch

            sep.torch_device = torch.device("cpu")
            sep.onnx_execution_provider = ["CPUExecutionProvider"]

        sep.load_model(model_filename=model_spec.filename)

        if on_stage_change:
            on_stage_change("separating")

        # Provide deterministic custom_output_names for each native stem
        custom_names = {
            stem: f"raw_{STEM_TO_TRACK_ID.get(stem.lower(), stem.lower())}"
            for stem in model_spec.native_stems
        }

        output_files = sep.separate(str(input_path), custom_output_names=custom_names)
        if not output_files:
            raise SeparationError(
                code="export_failed",
                title="No separated audio tracks were produced",
                message="The separation engine returned an empty output list.",
                suggestion="Try running the separation again or switch to another model.",
                http_status=500,
            )

        resolved_map: Dict[str, Path] = {}
        for fpath_str in output_files:
            fpath = Path(fpath_str)
            if not fpath.is_absolute():
                fpath = work_dir / fpath
            if not fpath.is_file():
                continue

            stem_lower = fpath.stem.lower()
            for stem_key, track_id in STEM_TO_TRACK_ID.items():
                if stem_Lower_matches(stem_lower, stem_key, track_id):
                    resolved_map[track_id] = fpath
                    break

        return resolved_map

    def _finalize_and_export_tracks(
        self,
        raw_outputs: Dict[str, Path],
        tracks_dir: Path,
        selected_tracks: List[str],
        model_spec: CuratedModel,
        fmt_spec: object,
        input_metadata: AudioMetadata,
    ) -> List[Dict[str, object]]:
        """
        Synthesize combined instrumental if needed, restore mono channel layout when input was mono,
        and encode each requested track in the user's chosen format.
        """
        # Synthesize 'music' = drums + bass + other for 4-stem models when requested
        if "music" in selected_tracks and "music" not in raw_outputs and model_spec.synthesizes_music:
            required_parts = ["drums", "bass", "other"]
            if all(p in raw_outputs for p in required_parts):
                synth_path = raw_outputs["drums"].parent / "raw_music.wav"
                _combine_wav_tracks([raw_outputs[p] for p in required_parts], synth_path)
                raw_outputs["music"] = synth_path

        published: List[Dict[str, object]] = []
        for track_id in selected_tracks:
            raw_wav = raw_outputs.get(track_id)
            if raw_wav is None or not raw_wav.is_file() or raw_wav.stat().st_size == 0:
                raise SeparationError(
                    code="export_failed",
                    title="Missing separated audio output",
                    message=f"Expected output track '{track_id}' was not generated by the model.",
                    suggestion="Try running the job again or select a different model.",
                    http_status=500,
                )

            # Restore mono channel count if the input file was mono (1 channel)
            if input_metadata.channels == 1:
                _downmix_wav_to_mono_inplace(raw_wav)

            dest_filename = f"{track_id}.{fmt_spec.extension}"
            dest_path = tracks_dir / dest_filename
            _convert_wav_to_target_format(raw_wav, dest_path, fmt_spec.id)

            if not dest_path.is_file() or dest_path.stat().st_size == 0:
                raise SeparationError(
                    code="export_failed",
                    title="Could not export output file",
                    message=f"Failed to write output track '{dest_filename}'.",
                    suggestion="Verify disk space and FFmpeg installation on the server.",
                    http_status=500,
                )

            track_def = TRACK_DEFINITIONS.get(track_id)
            published.append(
                {
                    "track_id": track_id,
                    "label": track_def.label if track_def else track_id.capitalize(),
                    "icon": track_def.icon if track_def else "🎵",
                    "filename": dest_filename,
                    "format": fmt_spec.id,
                    "mime_type": fmt_spec.mime_type,
                    "size_bytes": dest_path.stat().st_size,
                }
            )

        return published


def stem_Lower_matches(filename_stem: str, stem_key: str, track_id: str) -> bool:
    """Match either our custom `raw_<track_id>` filename or audio-separator's `_(<Stem>)_` pattern."""
    if filename_stem == f"raw_{track_id}":
        return True
    if f"_({stem_key})" in filename_stem or f"_({track_id})" in filename_stem:
        return True
    return False


def _combine_wav_tracks(part_paths: List[Path], destination: Path) -> None:
    """Sum multiple aligned WAV files into a single instrumental WAV file without clipping."""
    combined: Optional[np.ndarray] = None
    sample_rate = 44100

    for p in part_paths:
        data, sr = sf.read(str(p), dtype="float32", always_2d=True)
        sample_rate = sr
        if combined is None:
            combined = data
        else:
            min_len = min(len(combined), len(data))
            combined = combined[:min_len] + data[:min_len]

    if combined is None:
        raise RuntimeError("missing_output: No audio parts available to synthesize instrumental track")

    peak = float(np.max(np.abs(combined)))
    if peak > 0.98:
        combined = combined * (0.95 / peak)

    sf.write(str(destination), combined, sample_rate, subtype="PCM_16")


def _downmix_wav_to_mono_inplace(wav_path: Path) -> None:
    """Convert a multi-channel WAV file back to 1-channel mono if the original upload was mono."""
    data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    if data.shape[1] <= 1:
        return
    mono = np.mean(data, axis=1)
    sf.write(str(wav_path), mono, sr, subtype="PCM_16")


def _convert_wav_to_target_format(source_wav: Path, dest_path: Path, format_id: str) -> None:
    """Convert a WAV file to WAV, FLAC, or MP3 (320 kbps)."""
    fmt = format_id.upper()
    if fmt == "WAV":
        shutil.copyfile(source_wav, dest_path)
        return

    if fmt == "FLAC":
        data, sr = sf.read(str(source_wav), dtype="float32")
        sf.write(str(dest_path), data, sr, format="FLAC", subtype="PCM_16")
        return

    if fmt == "MP3":
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            proc = subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(source_wav),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "320k",
                    str(dest_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if proc.returncode == 0 and dest_path.is_file() and dest_path.stat().st_size > 0:
                return

        # Fallback to pydub
        from pydub import AudioSegment

        seg = AudioSegment.from_wav(str(source_wav))
        seg.export(str(dest_path), format="mp3", bitrate="320k")
        return

    raise ValueError(f"Unsupported export format: {format_id}")
