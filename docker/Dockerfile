FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WATCHER_FRAMEWORK_DIR=/app \
    WATCHER_DATA_DIR=/data

WORKDIR /app

COPY pyproject.toml ./
COPY README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY skills/ ./skills/
COPY src/ ./src/
COPY web/requirements.txt ./web/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2,<27" \
    && python -m pip install --no-cache-dir -e . -r web/requirements.txt \
    && python -m pip check

COPY web/backend/ ./web/backend/
COPY web/frontend/ ./web/frontend/
COPY docker/healthcheck.py ./docker/healthcheck.py

RUN useradd --uid 10001 --create-home watcher \
    && mkdir -p /data \
    && chown watcher:watcher /data

USER watcher
WORKDIR /app/web/backend
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]

# Task scheduling and file-backed records currently require a single worker.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
