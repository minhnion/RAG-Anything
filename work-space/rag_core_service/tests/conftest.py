from __future__ import annotations

import os
import tempfile
from pathlib import Path
import sys

SERVICE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVICE_ROOT.parents[1]
WORKSPACE_ROOT = SERVICE_ROOT.parent
for path in (WORKSPACE_ROOT, PROJECT_ROOT, SERVICE_ROOT):
    value = str(path)
    if value in sys.path:
        sys.path.remove(value)
    sys.path.insert(0, value)

TEST_DATA_DIR = Path(tempfile.gettempdir()) / "rag_core_service_pytest"
TEST_LOG_DIR = TEST_DATA_DIR / "logs"
TEST_LOG_DIR.mkdir(parents=True, exist_ok=True)

os.environ["RAG_CORE_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["RAG_CORE_LOG_DIR"] = str(TEST_LOG_DIR)
os.environ.setdefault("RAG_CORE_SERVICE_TOKEN", "")
