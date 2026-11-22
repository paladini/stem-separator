# Stem Separator — CPU Dockerfile
# Self-hosted web UI & FastAPI server powered by python-audio-separator[cpu]

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUDIO_SEPARATOR_MODEL_DIR=/data/models \
    STEM_SEPARATOR_OUTPUT_DIR=/data/output \
    STEM_SEPARATOR_HOST=0.0.0.0 \
    STEM_SEPARATOR_PORT=7860

LABEL maintainer="Fernando Paladini <fernando@paladini.dev>"
LABEL description="Stem Separator (CPU) - AI audio track separation powered by python-audio-separator"
LABEL version="1.0.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY src ./src
COPY templates ./templates
COPY static ./static

RUN mkdir -p /data/models /data/output && \
    chmod 777 /data/models /data/output

EXPOSE 7860
VOLUME ["/data/models", "/data/output"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:7860/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
