"""Tests for S1: System discovery, curated catalog, and main web interface (criteria 1-6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.core.catalog import (
    CURATED_MODELS,
    is_model_installed,
    resolve_model_and_tracks,
)
from src.core.config import AppConfig


@pytest.fixture()
def temp_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        output_dir=tmp_path / "output",
        model_dir=tmp_path / "models",
        max_upload_mb=250,
        max_duration_minutes=30,
        min_free_disk_mb=50,
        max_concurrent_jobs=1,
        max_queue_size=5,
        job_retention_hours=24,
        host="127.0.0.1",
        port=7860,
    )


def test_health_endpoint_healthy_and_degraded(temp_config: AppConfig):
    """Criterion 1: GET /health returns 200 when FFmpeg is available, 503 when missing."""
    app = create_app(temp_config)
    client = TestClient(app)

    with patch("src.core.catalog.shutil.which", return_value="/usr/bin/ffmpeg"):
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["ffmpeg_available"] is True
        assert data["device"] in ("cpu", "cuda")
        assert data["active_jobs"] == 0
        assert data["queued_jobs"] == 0

    with patch("src.core.catalog.shutil.which", return_value=None):
        res_deg = client.get("/health")
        assert res_deg.status_code == 503
        data_deg = res_deg.json()
        assert data_deg["status"] == "degraded"
        assert data_deg["ffmpeg_available"] is False


def test_system_catalog_endpoint(temp_config: AppConfig):
    """Criterion 2 & 5: GET /api/system exposes hardware, formats, presets, and curated models with install state."""
    app = create_app(temp_config)
    client = TestClient(app)

    res = client.get("/api/system")
    assert res.status_code == 200
    payload = res.json()

    assert payload["max_upload_mb"] == 250
    assert payload["device"] in ("cpu", "cuda")
    assert isinstance(payload["free_disk_mb"], int)

    format_ids = [f["id"] for f in payload["formats"]]
    assert format_ids == ["WAV", "FLAC", "MP3"]
    assert any(f["lossless"] is True for f in payload["formats"])

    preset_ids = [p["id"] for p in payload["presets"]]
    assert preset_ids == ["vocals_music", "all_instruments", "extended_instruments"]

    models_by_id = {m["id"]: m for m in payload["models"]}
    assert set(models_by_id.keys()) == {
        "vocals_music_fast",
        "vocals_karaoke",
        "vocals_music_hq",
        "instruments_4",
        "instruments_6",
    }

    # Initially no model files exist in tmp_path / "models"
    assert models_by_id["vocals_music_fast"]["installed"] is False
    assert models_by_id["vocals_music_fast"]["download_size_mb"] == pytest.approx(63.7)
    assert "MIT" in models_by_id["vocals_music_fast"]["license_info"]

    # Simulate cached model file on disk
    cached_file = temp_config.model_dir / "UVR-MDX-NET-Inst_HQ_3.onnx"
    cached_file.write_bytes(b"onnx-weights-placeholder")

    res_after = client.get("/api/system")
    models_after = {m["id"]: m for m in res_after.json()["models"]}
    assert models_after["vocals_music_fast"]["installed"] is True
    assert models_after["instruments_4"]["installed"] is False


def test_model_and_track_compatibility_rules(temp_config: AppConfig):
    """Criterion 4: Only output tracks supported by the active model can be resolved."""
    # vocals_music_fast supports only vocals and music
    model, tracks = resolve_model_and_tracks(
        mode="vocals_music",
        model_id="vocals_music_fast",
        requested_tracks=["vocals", "music"],
    )
    assert model.id == "vocals_music_fast"
    assert tracks == ["vocals", "music"]

    # Requesting drums from a 2-track vocals/music model must fail
    with pytest.raises(ValueError, match="incompatible_tracks"):
        resolve_model_and_tracks(
            mode="vocals_music",
            model_id="vocals_music_fast",
            requested_tracks=["vocals", "drums"],
        )

    # instruments_4 supports vocals, drums, bass, other, and synthesized music
    model_4, tracks_4 = resolve_model_and_tracks(
        mode="all_instruments",
        model_id="instruments_4",
        requested_tracks=["vocals", "drums", "bass", "other", "music"],
    )
    assert model_4.id == "instruments_4"
    assert tracks_4 == ["vocals", "drums", "bass", "other", "music"]

    # instruments_4 does NOT support guitar or piano
    with pytest.raises(ValueError, match="incompatible_tracks"):
        resolve_model_and_tracks(
            mode="all_instruments",
            model_id="instruments_4",
            requested_tracks=["vocals", "guitar"],
        )

    # instruments_6 supports guitar and piano
    model_6, tracks_6 = resolve_model_and_tracks(
        mode="extended_instruments",
        model_id="instruments_6",
        requested_tracks=["vocals", "drums", "bass", "guitar", "piano", "other"],
    )
    assert model_6.id == "instruments_6"
    assert "guitar" in tracks_6 and "piano" in tracks_6

    # Unknown model ID is rejected
    with pytest.raises(ValueError, match="unsupported_model"):
        resolve_model_and_tracks(
            mode="vocals_music",
            model_id="unverified_random_model.ckpt",
            requested_tracks=["vocals"],
        )


def test_main_page_plain_english_and_accessibility(temp_config: AppConfig):
    """Criteria 3 & 6: Main page renders Stem Separator with plain-English labels and accessibility attributes."""
    app = create_app(temp_config)
    client = TestClient(app)

    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    assert "Stem Separator" in html
    assert "Split My Music" not in html

    # Plain-English track labels
    assert "Vocals" in html
    assert "Music (Instrumental)" in html
    assert "Drums" in html
    assert "Bass" in html
    assert "Guitar" in html
    assert "Piano" in html
    assert "Other Instruments" in html

    # Accessibility landmarks & live regions
    assert 'class="skip-link"' in html
    assert 'aria-live="polite"' in html
    assert 'role="radiogroup"' in html
    assert 'role="alert"' in html
