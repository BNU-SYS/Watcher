"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import config
from .catalog import get_catalog, load_catalog
from .job_manager import manager
from .routers import catalog, feedback, model, scans
from .store import store

logger = logging.getLogger("watcher")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.ensure_dirs()
    store.load()
    load_catalog(force=True)
    manager.recover_stale()
    yield
    await manager.shutdown()


app = FastAPI(
    title="Watcher 代码缺陷检测平台",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.include_router(catalog.router, prefix="/api")
app.include_router(model.router, prefix="/api")
app.include_router(scans.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if response.status_code in (200, 206) and path.startswith("/js/") and path.endswith(".js"):
        # Some system MIME databases classify .js as plain text, which nosniff blocks.
        response.headers["Content-Type"] = "text/javascript; charset=utf-8"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if not path.startswith(("/api/docs", "/api/openapi")):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'",
        )
    return response


@app.exception_handler(Exception)
async def unhandled_exception(_request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc.__class__.__name__)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


@app.get("/api/health")
def health() -> dict:
    info = get_catalog()["framework"]
    return {
        "status": "ok",
        "framework_available": info["available"],
        "framework_path": info["path"],
        "detector_path": info["detector_path"],
    }


if config.FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
