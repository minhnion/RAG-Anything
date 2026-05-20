from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import deep_merge, get_app_config

from .paths import PathStore, read_json, safe_id, utc_now, write_json


class WorkspaceStore:
    def __init__(self, paths: PathStore):
        self.paths = paths

    def create_or_update(
        self,
        workspace_id: str,
        name: str | None = None,
        description: str | None = None,
        remote_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        root = self.paths.ensure_workspace(workspace_id)
        path = self.paths.metadata_path(workspace_id)
        created = not path.exists()
        defaults = get_app_config().raw
        current = read_json(path, {})
        now = utc_now()
        merged_config = deep_merge(defaults, current.get("config", {}))
        merged_config = deep_merge(merged_config, config or {})
        record = {
            "workspace_id": workspace_id,
            "safe_workspace_id": safe_id(workspace_id),
            "name": name if name is not None else current.get("name"),
            "description": description if description is not None else current.get("description"),
            "remote_id": remote_id if remote_id is not None else current.get("remote_id"),
            "config": merged_config,
            "created_at": current.get("created_at", now),
            "updated_at": now,
            "root": str(root),
        }
        write_json(path, record)
        return record, created

    def get(self, workspace_id: str) -> dict[str, Any] | None:
        path = self.paths.metadata_path(workspace_id)
        if not path.exists():
            return None
        return read_json(path, {})

    def require(self, workspace_id: str) -> dict[str, Any]:
        record = self.get(workspace_id)
        if record is None:
            record, _ = self.create_or_update(workspace_id)
        return record

    def delete(self, workspace_id: str) -> bool:
        root = self.paths.workspace_dir(workspace_id)
        if not root.exists():
            return False
        import shutil

        shutil.rmtree(root)
        return True


class DocumentStore:
    def __init__(self, paths: PathStore):
        self.paths = paths

    def all(self, workspace_id: str) -> dict[str, Any]:
        return read_json(self.paths.documents_path(workspace_id), {})

    def get(self, workspace_id: str, document_id: str) -> dict[str, Any] | None:
        return self.all(workspace_id).get(document_id)

    def upsert(self, workspace_id: str, document_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        data = self.all(workspace_id)
        now = utc_now()
        current = data.get(document_id, {})
        current.update(patch)
        current.setdefault("document_id", document_id)
        current.setdefault("created_at", now)
        current["updated_at"] = now
        data[document_id] = current
        write_json(self.paths.documents_path(workspace_id), data)
        return current

    def mark_deleted(self, workspace_id: str, document_id: str) -> dict[str, Any] | None:
        current = self.get(workspace_id, document_id)
        if current is None:
            return None
        return self.upsert(workspace_id, document_id, {"index_state": "deleted", "deleted_at": utc_now()})


class JsonManifest:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        return read_json(self.path, {})

    def save(self, data: dict[str, Any]) -> None:
        write_json(self.path, data)

