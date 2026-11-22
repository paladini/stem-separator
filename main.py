"""
Stem Separator - Main Entrypoint

Self-hosted web application for separating vocals, background music, and
instruments from audio files using python-audio-separator.
"""

from __future__ import annotations

import uvicorn

from src.api import app
from src.core.config import get_config


if __name__ == "__main__":
    cfg = get_config()
    print("🎵 Starting Stem Separator...")
    print(f"🚀 Web UI: http://localhost:{cfg.port}")
    print(f"🔍 Health Check: http://localhost:{cfg.port}/health")
    uvicorn.run(
        "main:app",
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )
