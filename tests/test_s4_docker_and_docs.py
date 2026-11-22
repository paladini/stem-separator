"""Tests for S4: Docker CPU/GPU packaging, verification, and bilingual documentation (criteria 21-23)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.catalog import CURATED_MODELS
from src.core.config import PROJECT_ROOT
from src.core.engine import SeparatorEngine
from src.core.validation import probe_and_validate_audio
from tests.test_s2_jobs_and_separation import make_wav_bytes


def test_docker_and_compose_configurations():
    """Criteria 21 & 22: Dockerfile, Dockerfile.gpu, docker-compose.yml, and docker-compose.gpu.yml exist and meet requirements."""
    dockerfile_cpu = PROJECT_ROOT / "Dockerfile"
    dockerfile_gpu = PROJECT_ROOT / "Dockerfile.gpu"
    compose_cpu = PROJECT_ROOT / "docker-compose.yml"
    compose_gpu = PROJECT_ROOT / "docker-compose.gpu.yml"

    assert dockerfile_cpu.is_file()
    assert dockerfile_gpu.is_file()
    assert compose_cpu.is_file()
    assert compose_gpu.is_file()

    cpu_text = dockerfile_cpu.read_text(encoding="utf-8")
    gpu_text = dockerfile_gpu.read_text(encoding="utf-8")
    compose_cpu_text = compose_cpu.read_text(encoding="utf-8")
    compose_gpu_text = compose_gpu.read_text(encoding="utf-8")

    # CPU Dockerfile checks
    assert "ffmpeg" in cpu_text
    assert "HEALTHCHECK" in cpu_text
    assert "http://localhost:7860/health" in cpu_text
    assert "/data/models" in cpu_text
    assert "/data/output" in cpu_text

    # GPU Dockerfile checks
    assert "nvidia/cuda:" in gpu_text
    assert "onnxruntime-gpu" in gpu_text
    assert "audio-separator[gpu]" in gpu_text
    assert "HEALTHCHECK" in gpu_text
    assert "http://localhost:7860/health" in gpu_text

    # Compose checks: single service name 'stem-separator' upgraded by override (no dual service collision on 7860)
    assert "stem-separator:" in compose_cpu_text
    assert "7860:7860" in compose_cpu_text
    assert "AUDIO_SEPARATOR_MODEL_DIR=/data/models" in compose_cpu_text
    assert "STEM_SEPARATOR_OUTPUT_DIR=/data/output" in compose_cpu_text
    assert "healthcheck:" in compose_cpu_text

    assert "stem-separator:" in compose_gpu_text
    assert "Dockerfile.gpu" in compose_gpu_text
    assert "gpus: all" in compose_gpu_text


def test_license_and_bilingual_readmes():
    """Criterion 23: LICENSE, README.md, and README_PT-BR.md exist and include required sections and real screenshots."""
    license_file = PROJECT_ROOT / "LICENSE"
    readme_en = PROJECT_ROOT / "README.md"
    readme_pt = PROJECT_ROOT / "README_PT-BR.md"

    assert license_file.is_file()
    assert "MIT License" in license_file.read_text(encoding="utf-8")

    assert readme_en.is_file()
    assert readme_pt.is_file()

    en_text = readme_en.read_text(encoding="utf-8")
    pt_text = readme_pt.read_text(encoding="utf-8")

    for text in (en_text, pt_text):
        assert "Stem Separator" in text
        assert "Split My Music" not in text
        assert "python-audio-separator" in text
        assert "docker compose" in text
        assert "docker-compose.gpu.yml" in text
        assert "NVIDIA Container Toolkit" in text
        assert "UVR-MDX-NET-Inst_HQ_3.onnx" in text
        assert "docs/screenshots/" in text


def test_real_audio_separator_engine_integration(tmp_path: Path):
    """
    Integration test with real python-audio-separator using cached UVR-MDX-NET-Inst_HQ_3.onnx.
    Runs automatically when the model file is cached in data/models (or when STEM_SEPARATOR_RUN_REAL_MODEL_TEST=1).
    """
    model_dir = PROJECT_ROOT / "data" / "models"
    model_spec = CURATED_MODELS["vocals_music_fast"]
    model_file = model_dir / model_spec.filename

    if not model_file.is_file() and os.environ.get("STEM_SEPARATOR_RUN_REAL_MODEL_TEST") != "1":
        pytest.skip("Real model weights not cached locally; set STEM_SEPARATOR_RUN_REAL_MODEL_TEST=1 to download and run.")

    input_wav = tmp_path / "real_test_tone.wav"
    input_wav.write_bytes(make_wav_bytes(channels=2, sample_rate=44100, duration_sec=1.0))

    meta = probe_and_validate_audio(input_wav, max_duration_minutes=5)
    engine = SeparatorEngine(model_dir=model_dir)
    tracks_dir = tmp_path / "tracks"

    stages_seen: list[str] = []
    published = engine.run_separation(
        input_path=input_wav,
        tracks_dir=tracks_dir,
        model_spec=model_spec,
        output_format="WAV",
        selected_tracks=["vocals", "music"],
        input_metadata=meta,
        device_preference="cpu",
        on_stage_change=stages_seen.append,
    )

    assert len(published) == 2
    assert [t["track_id"] for t in published] == ["vocals", "music"]
    for t in published:
        out_file = tracks_dir / str(t["filename"])
        assert out_file.is_file()
        assert out_file.stat().st_size > 1000
    assert "separating" in stages_seen
    assert "exporting" in stages_seen
