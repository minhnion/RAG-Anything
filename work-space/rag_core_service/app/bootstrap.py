"""Runtime path/bootstrap helpers for the standalone service.

The service lives under ``work-space/`` while the reusable RAGAnything package
and the research helpers live one directory above/next to it.  Keeping this in a
single module makes imports deterministic both from Docker and local runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


SERVICE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SERVICE_ROOT.parent
PROJECT_ROOT = WORKSPACE_ROOT.parent


def bootstrap_runtime() -> None:
    """Expose repo modules and load service/research env files."""

    # Keep the service package before work-space/app.py. This matters for
    # uvicorn --reload because the child process inherits sys.path from the
    # reloader process.
    for path in (PROJECT_ROOT, WORKSPACE_ROOT, SERVICE_ROOT):
        value = str(path)
        while value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)

    # Real process/container environment wins. The repo and service .env files
    # are fallbacks for local development and benchmark defaults.
    load_dotenv(WORKSPACE_ROOT / ".env", override=False)
    load_dotenv(SERVICE_ROOT / ".env", override=False)


bootstrap_runtime()

