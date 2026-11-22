"""Tests for S2: Audio upload validation, background job lifecycle, playback, and ZIP download (criteria 7-13)."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from typing import Dict

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from src.api import create_app
from src.core.catalog import CuratedModel
from src.core.config import AppConfig
from src.core.engine import SeparatorEngine
from src.core.validation import AudioMetadata


def make_wav_bytes(channels: int = 2, sample_rate: int = 44100, duration_sec: float = 1.0) -> bytes:
    """Create a valid in-memory PCM 16-bit WAV tone."""
    num_samples = int(sample_rate * duration_sec)
    t = np.linspace(0.0, duration_sec, num_samples, endpoint=False, dtype=np.float32)
    sine = 0.35 * np.sin(2.0 * np.pi * 440.0 * t)
    if channels == 1:
        audio = sine
    else:
        audio = np.column_stack([sine for _ in range(channels)])
    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class FakeSeparatorEngine(SeparatorEngine):
    """
    Deterministic fake engine that writes synthetic WAV tracks for every native stem
    of the selected model so we can test the full job pipeline, mono/stereo preservation,
    synthesized music tracks, format conversion (WAV/FLAC/MP3), and ZIP packaging quickly.
    """

    def _invoke_audio_separator(
        self,
        input_path: Path,
        work_dir: Path,
        model_spec: CuratedModel,
        selected_tracks: list[str],
        input_metadata: AudioMetadata,
        device_used: str,
        on_stage_change=None,
    ) -> Dict[str, Path]:
        if on_stage_change:
            on_stage_change("separating")

        # Read the uploaded audio (audio-separator internally outputs stereo 2ch at sample_rate)
        data, sr = sf.read(str(input_path), dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            stereo_data = np.column_stack([data[:, 0], data[:, 0]])
        else:
            stereo_data = data

        stem_map = {
            "Vocals": "vocals",
            "Instrumental": "music",
            "Drums": "drums",
            "Bass": "bass",
            "Guitar": "guitar",
            "Piano": "piano",
            "Other": "other",
        }
        outputs: Dict[str, Path] = {}
        for idx, native_stem in enumerate(model_spec.native_stems):
            track_id = stem_map[native_stem]
            out_wav = work_dir / f"raw_{track_id}.wav"
            scaled = stereo_data * (0.8 - 0.1 * idx)
            sf.write(str(out_wav), scaled, sr, format="WAV", subtype="PCM_16")
            outputs[track_id] = out_wav

        return outputs


@pytest.fixture()
def s2_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        output_dir=tmp_path / "output",
        model_dir=tmp_path / "models",
        max_upload_mb=250,
        max_duration_minutes=30,
        min_free_disk_mb=10,
        max_concurrent_jobs=1,
        max_queue_size=5,
        job_retention_hours=24,
        host="127.0.0.1",
        port=7860,
    )


def wait_for_job_completion(client: TestClient, job_id: str, timeout_sec: float = 10.0) -> dict:
    deadline = time.time() + timeout_sec
    last_data = {}
    while time.time() < deadline:
        res = client.get(f"/api/jobs/{job_id}")
        assert res.status_code == 200
        last_data = res.json()
        if last_data["status"] in ("completed", "failed"):
            return last_data
        # Criterion 9: while running, progress_percent must be None rather than fake numbers
        assert last_data["progress_percent"] is None
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not complete in time. Last state: {last_data}")


def test_stereo_job_lifecycle_flac_and_zip_download(s2_config: AppConfig):
    """Criteria 8, 9, 10, 12: Submit stereo WAV, separate into FLAC tracks, stream audio and download ZIP."""
    engine = FakeSeparatorEngine(s2_config.model_dir)
    app = create_app(config=s2_config, engine=engine)
    client = TestClient(app)

    stereo_bytes = make_wav_bytes(channels=2, sample_rate=48000, duration_sec=0.5)
    res = client.post(
        "/api/jobs",
        files={"file": ("stereo_song.wav", stereo_bytes, "audio/wav")},
        data={
            "mode": "vocals_music",
            "tracks": "vocals,music",
            "output_format": "FLAC",
            "model_id": "vocals_music_fast",
        },
    )
    assert res.status_code == 202
    submitted = res.json()
    job_id = submitted["job_id"]
    assert len(job_id) == 12

    completed = wait_for_job_completion(client, job_id)
    assert completed["status"] == "completed"
    assert completed["stage"] == "completed"
    assert completed["progress_percent"] == 100
    assert completed["output_format"] == "FLAC"

    tracks = completed["tracks"]
    assert len(tracks) == 2
    track_ids = [t["track_id"] for t in tracks]
    assert track_ids == ["vocals", "music"]

    # Verify individual track download and channel/sample-rate preservation (stereo 2ch, 48000 Hz)
    for track in tracks:
        dl = client.get(track["url"])
        assert dl.status_code == 200
        assert dl.headers["content-type"].startswith("audio/flac")
        info = sf.info(io.BytesIO(dl.content))
        assert info.channels == 2
        assert info.samplerate == 48000
        assert info.format == "FLAC"

    # Verify ZIP archive download
    zip_res = client.get(completed["zip_url"])
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zip_res.content), "r") as zf:
        names = sorted(zf.namelist())
        assert names == ["music.flac", "vocals.flac"]


def test_mono_input_preserves_mono_and_4stem_synthesizes_music(s2_config: AppConfig):
    """Criterion 10: Mono 1-channel input produces 1-channel output tracks; 4-stem model synthesizes music track."""
    engine = FakeSeparatorEngine(s2_config.model_dir)
    app = create_app(config=s2_config, engine=engine)
    client = TestClient(app)

    mono_bytes = make_wav_bytes(channels=1, sample_rate=22050, duration_sec=0.5)
    res = client.post(
        "/api/jobs",
        files={"file": ("mono_voice.wav", mono_bytes, "audio/wav")},
        data={
            "mode": "all_instruments",
            "tracks": "vocals,drums,bass,other,music",
            "output_format": "WAV",
            "model_id": "instruments_4",
        },
    )
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    completed = wait_for_job_completion(client, job_id)
    assert completed["status"] == "completed"
    tracks = completed["tracks"]
    assert [t["track_id"] for t in tracks] == ["vocals", "drums", "bass", "other", "music"]

    for track in tracks:
        dl = client.get(track["url"])
        assert dl.status_code == 200
        info = sf.info(io.BytesIO(dl.content))
        assert info.channels == 1, f"Track {track['track_id']} should preserve mono 1ch"
        assert info.samplerate == 22050


def test_path_traversal_and_directory_isolation(s2_config: AppConfig):
    """Criterion 13: Requests with path traversal characters or files outside tracks/ are rejected with 400 or 404."""
    engine = FakeSeparatorEngine(s2_config.model_dir)
    app = create_app(config=s2_config, engine=engine)
    client = TestClient(app)

    wav_bytes = make_wav_bytes(channels=1, sample_rate=44100, duration_sec=0.3)
    res = client.post(
        "/api/jobs",
        files={"file": ("../../etc/passwd.wav", wav_bytes, "audio/wav")},
        data={"mode": "vocals_music", "tracks": "vocals", "output_format": "MP3"},
    )
    assert res.status_code == 202
    job = wait_for_job_completion(client, res.json()["job_id"])
    assert job["status"] == "completed"
    assert job["input_filename"] == "passwd.wav"  # sanitized basename

    job_id = job["job_id"]

    # Valid MP3 file works
    ok_res = client.get(f"/api/jobs/{job_id}/files/vocals.mp3")
    assert ok_res.status_code == 200

    # Traversal attempts must be rejected
    for malicious in [
        "../job.json",
        "..%2Fjob.json",
        "..\\job.json",
        "../../job.json",
        "subdir/vocals.mp3",
    ]:
        bad_res = client.get(f"/api/jobs/{job_id}/files/{malicious}")
        assert bad_res.status_code in (400, 404), f"Expected 400/404 for {malicious}, got {bad_res.status_code}"

    # Malformed job_id must be rejected
    bad_job_res = client.get("/api/jobs/not-a-valid-hex-id/files/vocals.mp3")
    assert bad_job_res.status_code in (400, 404)
