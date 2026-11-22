"""HTTP API routes and web UI entrypoints for Stem Separator."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.core.catalog import detect_hardware_info, get_system_catalog_payload
from src.core.config import AppConfig, PROJECT_ROOT, get_config

logger = logging.getLogger(__name__)


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
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

        job_manager = getattr(request.app.state, "job_manager", None)
        active_jobs = job_manager.active_count if job_manager else 0
        queued_jobs = job_manager.queued_count if job_manager else 0

        payload = {
            "status": "healthy" if ffmpeg_ok else "degraded",
            "device": hw["device"],
            "device_name": hw["device_name"],
            "ffmpeg_available": ffmpeg_ok,
            "active_jobs": active_jobs,
            "queued_jobs": queued_jobs,
        }
        status_code = 200 if ffmpeg_ok else 503
        return JSONResponse(content=payload, status_code=status_code)

    @application.get("/api/system")
    async def get_system_info(request: Request):
        current_cfg: AppConfig = request.app.state.config
        payload = get_system_catalog_payload(
            model_dir=current_cfg.model_dir,
            output_dir=current_cfg.output_dir,
            max_upload_mb=current_cfg.max_upload_mb,
        )
        return payload

    return application


app = create_app()
