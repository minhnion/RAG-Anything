from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.bootstrap import SERVICE_ROOT
from app.config import get_settings


def _file_handler(log_dir: Path, level: int, formatter: logging.Formatter) -> RotatingFileHandler:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "rag_core_service.log",
        maxBytes=get_settings().log_max_bytes,
        backupCount=get_settings().log_backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler._rag_core_handler = True  # type: ignore[attr-defined]
    return handler


def configure_logging() -> None:
    settings = get_settings()
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

    logger = logging.getLogger("rag_core_service")
    try:
        handler = _file_handler(settings.log_dir, level, formatter)
    except OSError as exc:
        fallback_dir = SERVICE_ROOT / ".local-data" / "logs"
        try:
            if fallback_dir.resolve() == settings.log_dir.resolve():
                raise
            handler = _file_handler(fallback_dir, level, formatter)
            logger.warning(
                "Configured log dir %s is not writable (%s); using %s",
                settings.log_dir,
                exc,
                fallback_dir,
            )
        except OSError as fallback_exc:
            logger.warning(
                "File logging disabled; configured log dir %s is not writable (%s), fallback %s also failed (%s)",
                settings.log_dir,
                exc,
                fallback_dir,
                fallback_exc,
            )
            return

    root.addHandler(handler)
    logger.info("Logging initialized at %s", Path(handler.baseFilename).parent)
