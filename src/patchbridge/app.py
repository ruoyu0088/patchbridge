from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .api import create_api
from .config import AppConfig, load_config

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def _configure_logging(config: AppConfig) -> None:
    logger = logging.getLogger("patchbridge")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return
    handler = RotatingFileHandler(
        config.logs_dir / "app.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or load_config()
    _configure_logging(config)
    app = create_api(config)

    if (WEB_DIR / "index.html").exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

        @app.get("/favicon.ico")
        def favicon() -> Response:
            return Response(status_code=204)

    return app
