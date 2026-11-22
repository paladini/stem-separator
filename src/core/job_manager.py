"""Background job lifecycle, persistence, bounded concurrency queue, ZIP export, and cleanup."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .catalog import CURATED_MODELS, CuratedModel, is_model_installed
from .config import AppConfig
from .engine import SeparatorEngine
from .errors import SeparationError, classify_runtime_exception
from .validation import JOB_ID_RE, AudioMetadata

logger = logging.getLogger(__name__)

INCOMPLETE_STATUSES = {"queued", "preparing", "downloading_model", "separating", "exporting"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    """
    Manages separation jobs persisted on disk under `OUTPUT_DIR/<job_id>/job.json`
    with bounded concurrency (`max_concurrent_jobs`) and a bounded queue (`max_queue_size`).
    """

    def __init__(self, config: AppConfig, engine: Optional[SeparatorEngine] = None):
        self.config = config
        self.output_dir = Path(config.output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine or SeparatorEngine(config.model_dir)

        self._lock = threading.Lock()
        self._active_ids: set[str] = set()
        self._queued_ids: set[str] = set()
        self._executor = ThreadPoolExecutor(
            max_workers=config.max_concurrent_jobs,
            thread_name_prefix="stem-sep-worker",
        )

        self.recover_interrupted_jobs()
        self.cleanup_expired_jobs()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active_ids)

    @property
    def queued_count(self) -> int:
        with self._lock:
            return len(self._queued_ids)

    def _job_dir(self, job_id: str) -> Path:
        return self.output_dir / job_id

    def _job_json_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    def _write_job_state(self, job_id: str, data: Dict[str, object]) -> None:
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = _utc_now_iso()
        temp_path = job_dir / f"job.json.{os.getpid()}.tmp" if "os" in globals() else job_dir / "job.json.tmp"
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_path.replace(self._job_json_path(job_id))

    def get_job(self, job_id: str) -> Dict[str, object]:
        """Read persisted job state from disk, or raise 404 SeparationError if not found."""
        if not JOB_ID_RE.fullmatch(job_id or ""):
            raise SeparationError(
                code="job_not_found",
                title="Separation job not found",
                message=f"No separation job exists with ID '{job_id}'.",
                suggestion="Start a new separation from the main screen.",
                http_status=404,
            )
        json_path = self._job_json_path(job_id)
        if not json_path.is_file():
            raise SeparationError(
                code="job_not_found",
                title="Separation job not found",
                message=f"Job '{job_id}' does not exist or has already been deleted.",
                suggestion="Upload your audio file to run a new separation.",
                http_status=404,
            )
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SeparationError(
                code="job_not_found",
                title="Could not read job status",
                message=f"The state file for job '{job_id}' could not be read.",
                suggestion="Start a new separation job.",
                http_status=404,
            ) from exc

    def recover_interrupted_jobs(self) -> int:
        """
        On startup, transition any job left in a non-terminal state (`queued`, `preparing`,
        `downloading_model`, `separating`, `exporting`) to `failed` with `interrupted_by_restart`.
        """
        recovered = 0
        if not self.output_dir.exists():
            return 0

        for child in self.output_dir.iterdir():
            if not child.is_dir() or not JOB_ID_RE.fullmatch(child.name):
                continue
            json_path = child / "job.json"
            if not json_path.is_file():
                continue
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                status = str(data.get("status") or "")
                stage = str(data.get("stage") or "")
                if status in INCOMPLETE_STATUSES or stage in INCOMPLETE_STATUSES:
                    data["status"] = "failed"
                    data["stage"] = "failed"
                    data["progress_percent"] = None
                    data["error"] = {
                        "code": "interrupted_by_restart",
                        "title": "Job interrupted by server restart",
                        "message": "The server restarted while this separation job was still in progress.",
                        "suggestion": "Click 'Try Again' or re-upload your audio file to start a fresh separation.",
                    }
                    self._write_job_state(child.name, data)
                    recovered += 1
                    logger.info("Marked interrupted job %s as failed on startup", child.name)
            except Exception as exc:
                logger.warning("Failed to inspect job directory %s during startup recovery: %s", child, exc)

        return recovered

    def cleanup_expired_jobs(self, max_age_hours: Optional[float] = None) -> int:
        """
        Delete completed or failed job directories older than `max_age_hours`
        (defaults to `config.job_retention_hours`). Never deletes active/queued jobs.
        """
        retention_hours = self.config.job_retention_hours if max_age_hours is None else max_age_hours
        cutoff_seconds = retention_hours * 3600.0
        now = time.time()
        removed = 0

        if not self.output_dir.exists():
            return 0

        for child in self.output_dir.iterdir():
            if not child.is_dir() or not JOB_ID_RE.fullmatch(child.name):
                continue
            job_id = child.name
            with self._lock:
                if job_id in self._active_ids or job_id in self._queued_ids:
                    continue

            json_path = child / "job.json"
            try:
                if json_path.is_file():
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    if data.get("status") in INCOMPLETE_STATUSES:
                        continue
                mtime = json_path.stat().st_mtime if json_path.is_file() else child.stat().st_mtime
                if (now - mtime) >= cutoff_seconds:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
                    logger.info("Cleaned up expired job directory %s", job_id)
            except Exception as exc:
                logger.warning("Could not clean up job directory %s: %s", job_id, exc)

        return removed

    def submit_job(
        self,
        temp_upload_path: Path,
        original_filename: str,
        input_metadata: AudioMetadata,
        model_spec: CuratedModel,
        selected_tracks: List[str],
        output_format: str,
        device_preference: str = "auto",
    ) -> Dict[str, object]:
        """
        Create an isolated job directory, move the validated upload into it, persist initial
        `queued` state, and schedule background processing.
        """
        # Enforce device availability upfront before queueing
        device_used = self.engine.resolve_execution_device(device_preference, self.output_dir)

        with self._lock:
            if len(self._queued_ids) >= self.config.max_queue_size:
                temp_upload_path.unlink(missing_ok=True)
                raise SeparationError(
                    code="queue_full",
                    title="Server job queue is full",
                    message=f"There are already {len(self._queued_ids)} jobs waiting in the queue (limit: {self.config.max_queue_size}).",
                    suggestion="Please wait a minute for the current separation jobs to finish, then try again.",
                    http_status=429,
                )

            job_id = uuid.uuid4().hex[:12]
            while (self.output_dir / job_id).exists():
                job_id = uuid.uuid4().hex[:12]
            self._queued_ids.add(job_id)

        job_dir = self._job_dir(job_id)
        tracks_dir = job_dir / "tracks"
        tracks_dir.mkdir(parents=True, exist_ok=True)

        input_ext = temp_upload_path.suffix.lower() or ".wav"
        stored_input_path = job_dir / f"input{input_ext}"
        shutil.move(str(temp_upload_path), str(stored_input_path))

        model_cached = is_model_installed(model_spec, self.config.model_dir)
        now_iso = _utc_now_iso()

        job_record: Dict[str, object] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "progress_percent": None,
            "input_filename": original_filename,
            "input_metadata": input_metadata.to_dict(),
            "model_id": model_spec.id,
            "model_name": model_spec.friendly_name,
            "model_filename": model_spec.filename,
            "model_cached": model_cached,
            "estimated_download_mb": 0.0 if model_cached else model_spec.download_size_mb,
            "device_preference": device_preference,
            "device_used": device_used,
            "output_format": output_format.upper(),
            "requested_tracks": list(selected_tracks),
            "tracks": [],
            "zip_url": None,
            "error": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        self._write_job_state(job_id, job_record)

        self._executor.submit(
            self._run_job_worker,
            job_id,
            stored_input_path,
            input_metadata,
            model_spec,
            selected_tracks,
            output_format.upper(),
            device_preference,
        )

        return job_record

    def _update_stage(self, job_id: str, stage: str, status: Optional[str] = None) -> None:
        try:
            record = self.get_job(job_id)
            record["stage"] = stage
            record["status"] = status or ("running" if stage not in ("completed", "failed", "queued") else stage)
            record["progress_percent"] = 100 if stage == "completed" else None
            self._write_job_state(job_id, record)
        except Exception as exc:
            logger.warning("Failed to update stage for job %s to %s: %s", job_id, stage, exc)

    def _run_job_worker(
        self,
        job_id: str,
        stored_input_path: Path,
        input_metadata: AudioMetadata,
        model_spec: CuratedModel,
        selected_tracks: List[str],
        output_format: str,
        device_preference: str,
    ) -> None:
        with self._lock:
            self._queued_ids.discard(job_id)
            self._active_ids.add(job_id)

        job_dir = self._job_dir(job_id)
        tracks_dir = job_dir / "tracks"

        try:
            self._update_stage(job_id, "preparing", status="running")

            published_tracks = self.engine.run_separation(
                input_path=stored_input_path,
                tracks_dir=tracks_dir,
                model_spec=model_spec,
                output_format=output_format,
                selected_tracks=selected_tracks,
                input_metadata=input_metadata,
                device_preference=device_preference,
                on_stage_change=lambda st: self._update_stage(job_id, st, status="running"),
            )

            # Build track URLs and ZIP archive
            tracks_with_urls = []
            for item in published_tracks:
                fname = str(item["filename"])
                tracks_with_urls.append(
                    {
                        **item,
                        "url": f"/api/jobs/{job_id}/files/{fname}",
                    }
                )

            zip_path = self._build_zip_archive(job_id, tracks_dir, published_tracks)
            if not zip_path.is_file() or zip_path.stat().st_size == 0:
                raise SeparationError(
                    code="export_failed",
                    title="Could not create ZIP package",
                    message="Separated tracks were saved, but the ZIP archive could not be created.",
                    suggestion="You can download the individual tracks or try running the separation again.",
                    http_status=500,
                )

            record = self.get_job(job_id)
            record["status"] = "completed"
            record["stage"] = "completed"
            record["progress_percent"] = 100
            record["tracks"] = tracks_with_urls
            record["zip_url"] = f"/api/jobs/{job_id}/zip"
            record["error"] = None
            self._write_job_state(job_id, record)
            logger.info("Job %s completed successfully (%d tracks)", job_id, len(tracks_with_urls))

        except Exception as exc:
            sep_err = classify_runtime_exception(exc, model_spec.friendly_name)
            logger.error("Job %s failed (%s): %s", job_id, sep_err.code, exc, exc_info=True)
            try:
                record = self.get_job(job_id)
                record["status"] = "failed"
                record["stage"] = "failed"
                record["progress_percent"] = None
                record["error"] = sep_err.to_dict()
                self._write_job_state(job_id, record)
            except Exception as write_exc:
                logger.error("Could not persist failed state for job %s: %s", job_id, write_exc)
        finally:
            # Remove the temporary input copy inside the job directory to save disk space
            try:
                stored_input_path.unlink(missing_ok=True)
            except Exception:
                pass
            with self._lock:
                self._active_ids.discard(job_id)

    def _build_zip_archive(
        self,
        job_id: str,
        tracks_dir: Path,
        published_tracks: List[Dict[str, object]],
    ) -> Path:
        zip_path = self._job_dir(job_id) / f"stem_separator_{job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in published_tracks:
                fname = str(item["filename"])
                fpath = tracks_dir / fname
                if fpath.is_file():
                    zf.write(fpath, arcname=fname)
        return zip_path

    def get_zip_path(self, job_id: str) -> Path:
        record = self.get_job(job_id)
        if record.get("status") != "completed":
            raise SeparationError(
                code="job_not_completed",
                title="ZIP package is not ready yet",
                message="This separation job has not finished exporting its tracks.",
                suggestion="Wait until the job status reaches Completed before downloading the ZIP archive.",
                http_status=409,
            )
        zip_path = self._job_dir(job_id) / f"stem_separator_{job_id}.zip"
        if not zip_path.is_file():
            tracks_dir = self._job_dir(job_id) / "tracks"
            tracks = record.get("tracks") or []
            if tracks_dir.is_dir() and tracks:
                self._build_zip_archive(job_id, tracks_dir, tracks)
        if not zip_path.is_file():
            raise SeparationError(
                code="zip_not_found",
                title="ZIP package not found",
                message="The ZIP archive for this job is missing on disk.",
                suggestion="Download the individual tracks or start a new separation.",
                http_status=404,
            )
        return zip_path

    def delete_job(self, job_id: str) -> Dict[str, object]:
        """Safely delete a completed or failed job directory."""
        record = self.get_job(job_id)
        with self._lock:
            is_running = job_id in self._active_ids or job_id in self._queued_ids
        if is_running or record.get("status") in INCOMPLETE_STATUSES:
            raise SeparationError(
                code="job_in_progress",
                title="Cannot delete a running job",
                message="This separation job is currently queued or running.",
                suggestion="Wait for the job to complete before deleting its output files.",
                http_status=409,
            )
        job_dir = self._job_dir(job_id)
        if job_dir.is_dir():
            shutil.rmtree(job_dir, ignore_errors=True)
        return {"deleted": True, "job_id": job_id}
