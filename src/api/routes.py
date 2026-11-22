"""HTTP API routes and web UI entrypoints for Stem Separator."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.core.catalog import (
    OUTPUT_FORMATS,
    detect_hardware_info,
    get_system_catalog_payload,
    resolve_model_and_tracks,
)
from src.core.config import AppConfig, PROJECT_ROOT, get_config
from src.core.engine import SeparatorEngine
from src.core.errors import SeparationError, classify_runtime_exception
from src.core.job_manager import JobManager
from src.core.validation import (
    check_free_disk_space,
    probe_and_validate_audio,
    resolve_safe_job_track_path,
    sanitize_display_filename,
    stream_upload_to_path,
    validate_extension,
)

logger = logging.getLogger(__name__)


def _error_response(err: SeparationError) -> JSONResponse:
    return JSONResponse(
        status_code=err.http_status,
        content={
            "success": False,
            "error": err.to_dict(),
        },
    )


def create_app(
    config: Optional[AppConfig] = None,
    engine: Optional[SeparatorEngine] = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    cfg = config or get_config()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    cfg.model_dir.mkdir(parents=True, exist_ok=True)

    application = FastAPI(
        title="Stem Separator",
        description="Self-hosted AI audio separation for vocals, music, and instruments",
        version="1.0.0",
    )
    application.state.config = cfg
    application.state.job_manager = JobManager(config=cfg, engine=engine)

    @application.exception_handler(SeparationError)
    async def handle_separation_error(_request: Request, exc: SeparationError):
        return _error_response(exc)

    static_dir = PROJECT_ROOT / "static"
    templates_dir = PROJECT_ROOT / "templates"
    static_dir.mkdir(parents=True, exist_ok=True)
    templates_dir.mkdir(parents=True, exist_ok=True)

    application.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    templates = Jinja2Templates(directory=str(templates_dir))

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {})

    @application.get("/health")
    async def health_check(request: Request):
        current_cfg: AppConfig = request.app.state.config
        hw = detect_hardware_info(current_cfg.output_dir)
        ffmpeg_ok = bool(hw["ffmpeg_available"])

        job_manager: JobManager = request.app.state.job_manager
        payload = {
            "status": "healthy" if ffmpeg_ok else "degraded",
            "device": hw["device"],
            "device_name": hw["device_name"],
            "ffmpeg_available": ffmpeg_ok,
            "active_jobs": job_manager.active_count,
            "queued_jobs": job_manager.queued_count,
        }
        status_code = 200 if ffmpeg_ok else 503
        return JSONResponse(content=payload, status_code=status_code)

    @application.get("/api/system")
    async def get_system_info(request: Request):
        current_cfg: AppConfig = request.app.state.config
        return get_system_catalog_payload(
            model_dir=current_cfg.model_dir,
            output_dir=current_cfg.output_dir,
            max_upload_mb=current_cfg.max_upload_mb,
        )

    @application.post("/api/jobs")
    async def create_job(
        request: Request,
        file: UploadFile = File(...),
        mode: str = Form(default="vocals_music"),
        tracks: str = Form(default="vocals,music"),
        output_format: str = Form(default="WAV"),
        model_id: str = Form(default="auto"),
        device_preference: str = Form(default="auto"),
    ):
        current_cfg: AppConfig = request.app.state.config
        job_manager: JobManager = request.app.state.job_manager

        # 1. Validate free disk space first
        check_free_disk_space(
            [current_cfg.output_dir, current_cfg.model_dir],
            current_cfg.min_free_disk_mb,
        )

        # 2. Validate output format
        fmt_upper = (output_format or "WAV").strip().upper()
        if fmt_upper not in OUTPUT_FORMATS:
            raise SeparationError(
                code="invalid_output_format",
                title="Unsupported output format",
                message=f"Format '{output_format}' is not supported.",
                suggestion="Please choose WAV, FLAC, or MP3.",
                http_status=400,
            )

        # 3. Validate model and tracks
        hw = detect_hardware_info(current_cfg.output_dir)
        requested_tracks = [t.strip() for t in (tracks or "").split(",") if t.strip()]
        try:
            model_spec, resolved_tracks = resolve_model_and_tracks(
                mode=mode,
                model_id=model_id,
                requested_tracks=requested_tracks,
                cuda_available=bool(hw["cuda_available"]),
            )
        except ValueError as val_err:
            raw_msg = str(val_err)
            code = raw_msg.split(":", 1)[0].strip() if ":" in raw_msg else "invalid_selection"
            detail = raw_msg.split(":", 1)[1].strip() if ":" in raw_msg else raw_msg
            raise SeparationError(
                code=code,
                title="Incompatible model or track selection",
                message=detail,
                suggestion="Select one of the highlighted output tracks supported by the active model.",
                http_status=400,
            ) from val_err

        # 4. Validate filename & extension
        clean_filename = sanitize_display_filename(file.filename)
        ext = validate_extension(clean_filename)

        # 5. Stream upload in chunks to a temporary file inside output_dir
        temp_fd, temp_str = tempfile.mkstemp(
            prefix="upload_",
            suffix=ext,
            dir=str(current_cfg.output_dir),
        )
        import os

        os.close(temp_fd)
        temp_path = Path(temp_str)

        try:
            await stream_upload_to_path(
                upload=file,
                destination=temp_path,
                max_upload_mb=current_cfg.max_upload_mb,
            )
            audio_meta = probe_and_validate_audio(
                file_path=temp_path,
                max_duration_minutes=current_cfg.max_duration_minutes,
            )
            record = job_manager.submit_job(
                temp_upload_path=temp_path,
                original_filename=clean_filename,
                input_metadata=audio_meta,
                model_spec=model_spec,
                selected_tracks=resolved_tracks,
                output_format=fmt_upper,
                device_preference=device_preference,
            )
        except SeparationError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            logger.error("Unexpected error creating job: %s", exc, exc_info=True)
            raise classify_runtime_exception(exc) from exc

        return JSONResponse(status_code=202, content=record)

    @application.get("/api/jobs/{job_id}")
    async def get_job_status(request: Request, job_id: str):
        job_manager: JobManager = request.app.state.job_manager
        return job_manager.get_job(job_id)

    @application.get("/api/jobs/{job_id}/files/{filename:path}")
    async def download_job_track(request: Request, job_id: str, filename: str):
        current_cfg: AppConfig = request.app.state.config
        track_path = resolve_safe_job_track_path(current_cfg.output_dir, job_id, filename)
        ext = track_path.suffix.lstrip(".").upper()
        fmt_spec = OUTPUT_FORMATS.get(ext)
        media_type = fmt_spec.mime_type if fmt_spec else "application/octet-stream"
        return FileResponse(
            path=str(track_path),
            media_type=media_type,
            filename=track_path.name,
        )

    @application.get("/api/jobs/{job_id}/zip")
    async def download_job_zip(request: Request, job_id: str):
        job_manager: JobManager = request.app.state.job_manager
        zip_path = job_manager.get_zip_path(job_id)
        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=f"stem_separator_{job_id}.zip",
        )

    @application.delete("/api/jobs/{job_id}")
    async def delete_job(request: Request, job_id: str):
        job_manager: JobManager = request.app.state.job_manager
        return job_manager.delete_job(job_id)

    return application


app = create_app()
