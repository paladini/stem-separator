"""Structured error types with plain-English titles, messages, and recovery suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class SeparationError(Exception):
    """Domain exception carrying user-facing plain-English diagnostics and HTTP status."""

    code: str
    title: str
    message: str
    suggestion: str
    http_status: int = 400

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def classify_runtime_exception(exc: BaseException, model_name: str = "selected model") -> SeparationError:
    """Convert raw engine, PyTorch, ONNX, network, or filesystem errors into a friendly SeparationError."""
    if isinstance(exc, SeparationError):
        return exc

    raw = str(exc)
    low = raw.lower()

    if "out of memory" in low or "cuda error: out of memory" in low or "alloc" in low or isinstance(exc, MemoryError):
        return SeparationError(
            code="out_of_memory",
            title="Not enough memory to finish separation",
            message=f"The server ran out of RAM or GPU memory while running {model_name}.",
            suggestion="Switch to the fast 'MDX-Net Inst HQ 3' model, force CPU mode in Advanced Settings, or try a shorter audio file.",
            http_status=500,
        )

    if "sha-256" in low or "checksum" in low:
        return SeparationError(
            code="model_checksum_failed",
            title="Model download verification failed",
            message=f"The downloaded file for {model_name} was incomplete or did not match its verified checksum.",
            suggestion="Click 'Try Again' to re-download the model cleanly, or check your server's internet connection.",
            http_status=502,
        )

    if (
        "failed to download" in low
        or "connection" in low
        or "timeout" in low
        or "read timed out" in low
        or "url" in low
        or "http" in low
    ):
        return SeparationError(
            code="model_download_failed",
            title="Could not download the AI model",
            message=f"The server could not reach the model repository to download {model_name}.",
            suggestion="Check the server's internet connection and DNS settings, then click 'Try Again'.",
            http_status=502,
        )

    if "cuda" in low or "nvidia" in low or "gpu" in low or "cudnn" in low or "executionprovider" in low:
        return SeparationError(
            code="gpu_unavailable",
            title="GPU acceleration could not be initialized",
            message="The NVIDIA GPU or required CUDA/cuDNN libraries were not available for this job.",
            suggestion="In Advanced Settings, set Processing Device to 'Automatic' or 'Force CPU' and try again.",
            http_status=400,
        )

    if "no space left" in low or "disk full" in low or "enospc" in low:
        return SeparationError(
            code="insufficient_disk_space",
            title="Server disk is full",
            message="There is not enough free disk space on the server to save the separated audio files.",
            suggestion="Delete old jobs or free up disk space on the host volume, then try again.",
            http_status=507,
        )

    if "no audio frames" in low or "non-finite" in low or "invalidaudiodata" in type(exc).__name__.lower():
        return SeparationError(
            code="corrupted_audio",
            title="Audio file could not be decoded",
            message="The uploaded file contains empty, unreadable, or corrupted audio data.",
            suggestion="Try exporting the song again as a standard WAV, FLAC, or MP3 file and upload the new copy.",
            http_status=422,
        )

    if "export" in low or "audioexporterror" in type(exc).__name__.lower() or "missing_output" in low:
        return SeparationError(
            code="export_failed",
            title="Could not export the separated audio files",
            message="The separation engine finished, but one or more output files could not be written.",
            suggestion="Verify that FFmpeg is installed and that the output folder is writable, or try WAV output format.",
            http_status=500,
        )

    return SeparationError(
        code="processing_failed",
        title="Audio separation did not complete",
        message="An unexpected processing error occurred while separating your audio file.",
        suggestion="Try again with the default 'Vocals & Music' preset or convert your audio file to WAV/MP3 first.",
        http_status=500,
    )
