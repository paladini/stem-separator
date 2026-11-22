"""Input validation, streaming upload saving, disk checks, and audio metadata probing."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import soundfile as sf
from fastapi import UploadFile

from .errors import SeparationError


ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}

JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class AudioMetadata:
    """Verified audio stream characteristics."""

    duration_seconds: float
    sample_rate: int
    channels: int
    format_name: str
    file_size_bytes: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "duration_seconds": round(self.duration_seconds, 2),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "format_name": self.format_name,
            "file_size_bytes": self.file_size_bytes,
        }


def sanitize_display_filename(raw_filename: Optional[str]) -> str:
    """Strip directory traversal components and control characters from a user-supplied filename."""
    if not raw_filename:
        return "audio.wav"
    base = os.path.basename(raw_filename.replace("\\", "/"))
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" ._")
    if not cleaned:
        return "audio.wav"
    return cleaned[:120]


def validate_extension(filename: Optional[str]) -> str:
    """Verify the file extension is in ALLOWED_EXTENSIONS and return the lowercase extension."""
    clean_name = sanitize_display_filename(filename)
    ext = Path(clean_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed_list = ", ".join(sorted(e.lstrip(".").upper() for e in ALLOWED_EXTENSIONS))
        raise SeparationError(
            code="unsupported_format",
            title="Unsupported file format",
            message=f"The file '{clean_name}' does not appear to be a supported audio format.",
            suggestion=f"Please choose an audio file in one of these formats: {allowed_list}.",
            http_status=400,
        )
    return ext


def check_free_disk_space(paths: list[Path], min_free_mb: int) -> None:
    """Ensure every target volume has at least min_free_mb megabytes available."""
    if min_free_mb <= 0:
        return
    for path in paths:
        target = path if path.exists() else path.parent
        target.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(target)
        free_mb = int(usage.free // (1024 * 1024))
        if free_mb < min_free_mb:
            raise SeparationError(
                code="insufficient_disk_space",
                title="Low disk space on server",
                message=f"Only {free_mb} MB of disk space is available, which is below the {min_free_mb} MB safety limit.",
                suggestion="Free up disk space on the server or delete completed separation jobs before starting a new one.",
                http_status=507,
            )


async def stream_upload_to_path(
    upload: UploadFile,
    destination: Path,
    max_upload_mb: int,
    chunk_size: int = 1024 * 1024,
) -> int:
    """
    Stream an UploadFile to destination in chunks without loading the whole file into memory.
    Enforces max_upload_mb and checks for 0-byte uploads.
    """
    max_bytes = max_upload_mb * 1024 * 1024
    total_bytes = 0

    try:
        with open(destination, "wb") as out_file:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    out_file.close()
                    destination.unlink(missing_ok=True)
                    raise SeparationError(
                        code="file_too_large",
                        title="Audio file is too large",
                        message=f"The uploaded file exceeds the maximum allowed size of {max_upload_mb} MB.",
                        suggestion=f"Choose a file under {max_upload_mb} MB, compress it to FLAC/MP3, or increase STEM_SEPARATOR_MAX_UPLOAD_MB.",
                        http_status=413,
                    )
                out_file.write(chunk)
    except SeparationError:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise SeparationError(
            code="upload_failed",
            title="File upload was interrupted",
            message="The audio file could not be saved completely on the server.",
            suggestion="Check your network connection and available disk space, then try uploading again.",
            http_status=400,
        ) from exc

    if total_bytes == 0:
        destination.unlink(missing_ok=True)
        raise SeparationError(
            code="empty_file",
            title="The uploaded file is empty",
            message="The selected file contains 0 bytes of data.",
            suggestion="Please select a valid, non-empty audio file and try again.",
            http_status=400,
        )

    return total_bytes


def _probe_with_ffprobe(file_path: Path) -> Optional[AudioMetadata]:
    """Probe audio stream metadata using ffprobe with a strict argument list (no shell)."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels,duration:format=duration,format_name",
                "-of",
                "json",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        data = json.loads(proc.stdout)
        streams = data.get("streams") or []
        if not streams:
            return None
        stream = streams[0]
        fmt = data.get("format") or {}

        duration_raw = stream.get("duration") or fmt.get("duration")
        duration = float(duration_raw) if duration_raw is not None else 0.0
        sample_rate = int(stream.get("sample_rate") or 44100)
        channels = int(stream.get("channels") or 2)
        codec = str(stream.get("codec_name") or fmt.get("format_name") or "audio")

        if duration <= 0 or sample_rate <= 0 or channels <= 0:
            return None

        return AudioMetadata(
            duration_seconds=duration,
            sample_rate=sample_rate,
            channels=channels,
            format_name=codec,
            file_size_bytes=file_path.stat().st_size,
        )
    except Exception:
        return None


def probe_and_validate_audio(file_path: Path, max_duration_minutes: int) -> AudioMetadata:
    """
    Validate that file_path is a readable, non-corrupted audio file and check duration bounds.
    Uses soundfile header inspection first, then falls back to ffprobe or pydub.
    """
    if not file_path.is_file() or file_path.stat().st_size == 0:
        raise SeparationError(
            code="empty_file",
            title="The uploaded file is empty",
            message="The uploaded file contains no audio data.",
            suggestion="Please select a valid audio file and try again.",
            http_status=400,
        )

    metadata: Optional[AudioMetadata] = None

    # 1. Fast header check via libsndfile (WAV, FLAC, OGG)
    try:
        info = sf.info(str(file_path))
        if info.frames > 0 and info.samplerate > 0 and info.channels > 0:
            metadata = AudioMetadata(
                duration_seconds=float(info.frames) / float(info.samplerate),
                sample_rate=int(info.samplerate),
                channels=int(info.channels),
                format_name=str(info.format),
                file_size_bytes=file_path.stat().st_size,
            )
    except Exception:
        metadata = None

    # 2. Fallback to ffprobe for MP3/M4A/AAC/OPUS
    if metadata is None:
        metadata = _probe_with_ffprobe(file_path)

    # 3. Fallback to pydub if ffprobe binary wasn't found directly
    if metadata is None:
        try:
            from pydub import AudioSegment

            seg = AudioSegment.from_file(str(file_path))
            if len(seg) > 0 and seg.frame_rate > 0 and seg.channels > 0:
                metadata = AudioMetadata(
                    duration_seconds=len(seg) / 1000.0,
                    sample_rate=int(seg.frame_rate),
                    channels=int(seg.channels),
                    format_name=file_path.suffix.lstrip(".").lower() or "audio",
                    file_size_bytes=file_path.stat().st_size,
                )
        except Exception:
            metadata = None

    if metadata is None or metadata.duration_seconds <= 0.05:
        raise SeparationError(
            code="corrupted_audio",
            title="Invalid or corrupted audio file",
            message="The file could not be decoded as valid audio or has zero duration.",
            suggestion="Check that the file plays in your music player, or re-export it as WAV, FLAC, or MP3.",
            http_status=422,
        )

    max_seconds = max_duration_minutes * 60.0
    if metadata.duration_seconds > max_seconds:
        mins = int(metadata.duration_seconds // 60)
        secs = int(metadata.duration_seconds % 60)
        raise SeparationError(
            code="duration_too_long",
            title="Audio track is longer than the allowed limit",
            message=f"This audio file is {mins}m {secs:02d}s long, which exceeds the {max_duration_minutes}-minute limit.",
            suggestion=f"Trim the audio file to under {max_duration_minutes} minutes or increase STEM_SEPARATOR_MAX_DURATION_MINUTES.",
            http_status=413,
        )

    return metadata


def resolve_safe_job_track_path(output_dir: Path, job_id: str, filename: str) -> Path:
    """
    Validate job_id and filename strictly to prevent path traversal and ensure the resolved
    file sits directly inside OUTPUT_DIR/<job_id>/tracks/.
    """
    if not JOB_ID_RE.fullmatch(job_id or ""):
        raise SeparationError(
            code="invalid_job_id",
            title="Invalid job identifier",
            message="The requested job identifier is malformed.",
            suggestion="Refresh the page and select a valid separation job.",
            http_status=400,
        )

    if (
        not filename
        or ".." in filename
        or "/" in filename
        or "\\" in filename
        or not SAFE_FILENAME_RE.fullmatch(filename)
    ):
        raise SeparationError(
            code="invalid_filename",
            title="Invalid track filename",
            message="The requested filename contains disallowed characters.",
            suggestion="Use the download buttons inside the results section.",
            http_status=400,
        )

    tracks_root = (output_dir / job_id / "tracks").resolve()
    candidate = (tracks_root / filename).resolve()

    if candidate.parent != tracks_root:
        raise SeparationError(
            code="invalid_filename",
            title="Access denied",
            message="Access outside the job track directory is not allowed.",
            suggestion="Use the download buttons inside the results section.",
            http_status=400,
        )

    if not candidate.is_file():
        raise SeparationError(
            code="track_not_found",
            title="Separated track not found",
            message="The requested audio track does not exist or has expired.",
            suggestion="Run the separation again if the job was cleaned up.",
            http_status=404,
        )

    return candidate
