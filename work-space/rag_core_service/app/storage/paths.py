from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


def safe_id(value: str) -> str:
    value = str(value or "").strip()
    value = _SAFE_ID_RE.sub("_", value)
    return value.strip("._") or "default"


def safe_filename(value: str) -> str:
    name = Path(value or "document").name
    name = _SAFE_ID_RE.sub("_", name)
    return name.strip("._") or "document"


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class PathStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.workspaces_dir = self.data_dir / "workspaces"
        self.jobs_dir = self.data_dir / "jobs"
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def workspace_dir(self, workspace_id: str) -> Path:
        return self.workspaces_dir / safe_id(workspace_id)

    def ensure_workspace(self, workspace_id: str) -> Path:
        root = self.workspace_dir(workspace_id)
        for child in [
            "uploads",
            "parsed",
            "assets",
            "rag_storage",
            "graph_cache",
            "pruning_cache",
            "manifests",
            "node_overrides",
        ]:
            (root / child).mkdir(parents=True, exist_ok=True)
        return root

    def metadata_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "workspace.json"

    def documents_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "manifests" / "documents.json"

    def assets_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "manifests" / "assets.json"

    def node_overrides_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "node_overrides" / "overrides.json"

    def graph_path(self, workspace_id: str) -> Path:
        return self.workspace_dir(workspace_id) / "rag_storage" / "graph_chunk_entity_relation.graphml"

    def job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{safe_id(job_id)}.json"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)

