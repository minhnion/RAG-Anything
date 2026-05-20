from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers when uvicorn reloads or tests create multiple apps.
    for handler in list(root.handlers):
        if getattr(handler, "_rag_core_handler", False):
            root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    console._rag_core_handler = True  # type: ignore[attr-defined]
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.log_dir / "rag_core_service.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler._rag_core_handler = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    logging.getLogger("rag_core_service").info(
        "Logging initialized at %s", settings.log_dir
    )

