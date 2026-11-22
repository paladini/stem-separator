"""Tests for S3: Explicit failure handling, concurrency control, restart recovery, and cleanup (criteria 14-20)."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.core.catalog import CuratedModel
from src.core.config import AppConfig
from src.core.engine import SeparatorEngine
from src.core.job_manager import JobManager
from src.core.validation import AudioMetadata
from tests.test_s2_jobs_and_separation import (
    FakeSeparatorEngine,
    make_wav_bytes,
    wait_for_job_completion,
)


@pytest.fixture()
def s3_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        output_dir=tmp_path / "output",
        model_dir=tmp_path / "models",
        max_upload_mb=2,
        max_duration_minutes=1,
        min_free_disk_mb=50,
        max_concurrent_jobs=1,
        max_queue_size=2,
        job_retention_hours=24,
        host="127.0.0.1",
        port=7860,
    )


def test_invalid_empty_and_corrupted_uploads(s3_config: AppConfig):
    """Criterion 14: Unsupported extensions, 0-byte files, and corrupted audio return structured errors and clean temp files."""
    app = create_app(config=s3_config, engine=FakeSeparatorEngine(s3_config.model_dir))
    client = TestClient(app)

    # 1. Unsupported extension (.exe)
    res_ext = client.post(
        "/api/jobs",
        files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
        data={"mode": "vocals_music", "tracks": "vocals"},
    )
    assert res_ext.status_code == 400
    err_ext = res_ext.json()["error"]
    assert err_ext["code"] == "unsupported_format"
    assert "Traceback" not in json.dumps(err_ext)

    # 2. Empty file (0 bytes)
    res_empty = client.post(
        "/api/jobs",
        files={"file": ("empty.wav", b"", "audio/wav")},
        data={"mode": "vocals_music", "tracks": "vocals"},
    )
    assert res_empty.status_code == 400
    err_empty = res_empty.json()["error"]
    assert err_empty["code"] == "empty_file"
    assert err_empty["suggestion"]

    # 3. Corrupted audio (plain text inside .mp3/.wav)
    res_corrupt = client.post(
        "/api/jobs",
        files={"file": ("corrupted.wav", b"not-valid-riff-audio-headers-at-all", "audio/wav")},
        data={"mode": "vocals_music", "tracks": "vocals"},
    )
    assert res_corrupt.status_code == 422
    err_corrupt = res_corrupt.json()["error"]
    assert err_corrupt["code"] == "corrupted_audio"

    # Ensure no leftover upload_* temporary files remain in output_dir
    leftovers = list(s3_config.output_dir.glob("upload_*"))
    assert leftovers == []


def test_file_size_and_duration_limits(s3_config: AppConfig):
    """Criterion 15: Uploads exceeding MAX_UPLOAD_SIZE_MB or MAX_DURATION_MINUTES are rejected with 413."""
    # Set max_upload_mb=1 MB and max_duration_minutes=1 minute
    small_cfg = AppConfig(
        output_dir=s3_config.output_dir,
        model_dir=s3_config.model_dir,
        max_upload_mb=1,
        max_duration_minutes=1,
        min_free_disk_mb=10,
        max_concurrent_jobs=1,
        max_queue_size=5,
        job_retention_hours=24,
        host="127.0.0.1",
        port=7860,
    )
    app = create_app(config=small_cfg, engine=FakeSeparatorEngine(small_cfg.model_dir))
    client = TestClient(app)

    # 1. File larger than 1 MB
    oversized_payload = b"0" * (1024 * 1024 + 2048)
    res_size = client.post(
        "/api/jobs",
        files={"file": ("huge.wav", oversized_payload, "audio/wav")},
        data={"mode": "vocals_music", "tracks": "vocals"},
    )
    assert res_size.status_code == 413
    assert res_size.json()["error"]["code"] == "file_too_large"

    # 2. Audio duration longer than 1 minute (65 seconds at low sample rate so file size < 1 MB)
    long_wav = make_wav_bytes(channels=1, sample_rate=4000, duration_sec=65.0)
    assert len(long_wav) < 1024 * 1024
    res_dur = client.post(
        "/api/jobs",
        files={"file": ("long_podcast.wav", long_wav, "audio/wav")},
        data={"mode": "vocals_music", "tracks": "vocals"},
    )
    assert res_dur.status_code == 413
    assert res_dur.json()["error"]["code"] == "duration_too_long"


def test_insufficient_disk_space_rejection(s3_config: AppConfig):
    """Criterion 16: Low disk space below MIN_FREE_DISK_MB returns 507 insufficient_disk_space."""
    app = create_app(config=s3_config, engine=FakeSeparatorEngine(s3_config.model_dir))
    client = TestClient(app)

    fake_usage = os.statvfs_result((4096, 4096, 1000, 10, 10, 0, 0, 0, 0, 255)) if hasattr(os, "statvfs_result") else None
    from collections import namedtuple

    UsageTuple = namedtuple("usage", ["total", "used", "free"])
    low_free = UsageTuple(total=100 * 1024 * 1024, used=90 * 1024 * 1024, free=10 * 1024 * 1024)  # 10 MB free < 50 MB required

    wav_bytes = make_wav_bytes(channels=1, sample_rate=16000, duration_sec=0.3)
    with patch("src.core.validation.shutil.disk_usage", return_value=low_free):
        res = client.post(
            "/api/jobs",
            files={"file": ("song.wav", wav_bytes, "audio/wav")},
            data={"mode": "vocals_music", "tracks": "vocals"},
        )
        assert res.status_code == 507
        assert res.json()["error"]["code"] == "insufficient_disk_space"


def test_queue_full_concurrency_limit(s3_config: AppConfig):
    """Criterion 17: When MAX_QUEUE_SIZE pending jobs are already queued, new jobs are rejected with 429 queue_full."""
    gate = threading.Event()

    class BlockingEngine(FakeSeparatorEngine):
        def _invoke_audio_separator(self, *args, **kwargs):
            gate.wait(timeout=5.0)
            return super()._invoke_audio_separator(*args, **kwargs)

    # max_concurrent_jobs=1, max_queue_size=1 -> 1 active worker + 1 queued job allowed; 3rd submission fails with 429
    cfg = AppConfig(
        output_dir=s3_config.output_dir,
        model_dir=s3_config.model_dir,
        max_upload_mb=10,
        max_duration_minutes=10,
        min_free_disk_mb=10,
        max_concurrent_jobs=1,
        max_queue_size=1,
        job_retention_hours=24,
        host="127.0.0.1",
        port=7860,
    )
    app = create_app(config=cfg, engine=BlockingEngine(cfg.model_dir))
    client = TestClient(app)
    wav_bytes = make_wav_bytes(channels=1, sample_rate=16000, duration_sec=0.2)

    try:
        r1 = client.post("/api/jobs", files={"file": ("a.wav", wav_bytes, "audio/wav")}, data={"tracks": "vocals"})
        assert r1.status_code == 202
        # Give worker thread a moment to pull r1 into active state
        time.sleep(0.1)

        r2 = client.post("/api/jobs", files={"file": ("b.wav", wav_bytes, "audio/wav")}, data={"tracks": "vocals"})
        assert r2.status_code == 202

        # Queue now has r2 waiting; r3 must be rejected with 429 queue_full
        r3 = client.post("/api/jobs", files={"file": ("c.wav", wav_bytes, "audio/wav")}, data={"tracks": "vocals"})
        assert r3.status_code == 429
        assert r3.json()["error"]["code"] == "queue_full"
    finally:
        gate.set()


@pytest.mark.parametrize(
    ("simulated_error", "expected_code"),
    [
        (RuntimeError("Failed to download file from https://github.com/model.onnx, response code: 503"), "model_download_failed"),
        (RuntimeError("Downloaded file does not match its published SHA-256 checksum"), "model_checksum_failed"),
        (RuntimeError("CUDA error: out of memory when allocating tensor"), "out_of_memory"),
        (RuntimeError("missing_output: expected stem file not written"), "export_failed"),
    ],
)
def test_worker_runtime_failures_produce_friendly_errors_without_tracebacks(
    s3_config: AppConfig,
    simulated_error: Exception,
    expected_code: str,
):
    """Criterion 18: Model download, checksum, OOM, and export failures mark job failed with plain-English error and no stack trace."""

    class FailingEngine(SeparatorEngine):
        def _invoke_audio_separator(self, *args, **kwargs):
            raise simulated_error

    app = create_app(config=s3_config, engine=FailingEngine(s3_config.model_dir))
    client = TestClient(app)

    wav_bytes = make_wav_bytes(channels=1, sample_rate=16000, duration_sec=0.2)
    res = client.post(
        "/api/jobs",
        files={"file": ("song.wav", wav_bytes, "audio/wav")},
        data={"mode": "vocals_music", "tracks": "vocals"},
    )
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    finished = wait_for_job_completion(client, job_id)
    assert finished["status"] == "failed"
    assert finished["stage"] == "failed"
    err = finished["error"]
    assert err["code"] == expected_code
    assert err["title"]
    assert err["message"]
    assert err["suggestion"]
    assert "Traceback" not in json.dumps(err)


def test_explicit_cuda_request_when_gpu_unavailable(s3_config: AppConfig):
    """Criterion 18: Requesting device_preference='cuda' on a CPU-only machine returns 400 gpu_unavailable."""
    app = create_app(config=s3_config, engine=FakeSeparatorEngine(s3_config.model_dir))
    client = TestClient(app)
    wav_bytes = make_wav_bytes(channels=1, sample_rate=16000, duration_sec=0.2)

    with patch(
        "src.core.engine.detect_hardware_info",
        return_value={"device": "cpu", "device_name": "CPU", "cuda_available": False, "onnx_providers": ["CPUExecutionProvider"], "ffmpeg_available": True, "free_disk_mb": 5000},
    ):
        res = client.post(
            "/api/jobs",
            files={"file": ("song.wav", wav_bytes, "audio/wav")},
            data={"mode": "vocals_music", "tracks": "vocals", "device_preference": "cuda"},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "gpu_unavailable"


def test_startup_recovery_and_job_deletion_and_retention_cleanup(s3_config: AppConfig):
    """Criteria 19 & 20: Startup marks interrupted jobs failed; DELETE and retention cleanup remove old jobs safely without touching models."""
    s3_config.output_dir.mkdir(parents=True, exist_ok=True)
    s3_config.model_dir.mkdir(parents=True, exist_ok=True)

    # Create a cached model file to ensure cleanup never deletes MODEL_DIR contents
    cached_model = s3_config.model_dir / "UVR-MDX-NET-Inst_HQ_3.onnx"
    cached_model.write_bytes(b"cached-model-weights")

    # 1. Create a fake mid-flight job left behind by a crash/restart
    interrupted_id = "aa11bb22cc33"
    interrupted_dir = s3_config.output_dir / interrupted_id
    interrupted_dir.mkdir(parents=True, exist_ok=True)
    (interrupted_dir / "job.json").write_text(
        json.dumps(
            {
                "job_id": interrupted_id,
                "status": "running",
                "stage": "separating",
                "input_filename": "unfinished.wav",
            }
        ),
        encoding="utf-8",
    )

    # Initializing the app / JobManager should recover the interrupted job
    app = create_app(config=s3_config, engine=FakeSeparatorEngine(s3_config.model_dir))
    client = TestClient(app)

    rec_res = client.get(f"/api/jobs/{interrupted_id}")
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["status"] == "failed"
    assert rec_data["error"]["code"] == "interrupted_by_restart"

    # 2. Explicit DELETE /api/jobs/{job_id} removes the job directory
    del_res = client.delete(f"/api/jobs/{interrupted_id}")
    assert del_res.status_code == 200
    assert del_res.json() == {"deleted": True, "job_id": interrupted_id}
    assert not interrupted_dir.exists()
    assert client.get(f"/api/jobs/{interrupted_id}").status_code == 404

    # 3. Retention cleanup removes expired terminal jobs while preserving cached models
    expired_id = "dd44ee55ff66"
    expired_dir = s3_config.output_dir / expired_id
    expired_dir.mkdir(parents=True, exist_ok=True)
    expired_json = expired_dir / "job.json"
    expired_json.write_text(
        json.dumps({"job_id": expired_id, "status": "completed", "stage": "completed"}),
        encoding="utf-8",
    )
    old_time = time.time() - (48 * 3600)
    os.utime(expired_json, (old_time, old_time))

    jm: JobManager = app.state.job_manager
    removed_count = jm.cleanup_expired_jobs(max_age_hours=24)
    assert removed_count == 1
    assert not expired_dir.exists()
    assert cached_model.is_file()
