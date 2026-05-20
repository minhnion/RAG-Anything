from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.storage import PathStore, read_json, safe_id, utc_now, write_json


MEDIA_TYPES = {"image", "table", "equation"}


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value or "")


def _item_title(item: dict[str, Any], fallback: str) -> str:
    for key in ("image_caption", "table_caption", "caption", "text"):
        text = _first_text(item.get(key)).strip()
        if text:
            return text
    return fallback


class AssetService:
    def __init__(self, paths: PathStore):
        self.paths = paths

    def load_manifest(self, workspace_id: str) -> dict[str, Any]:
        return read_json(self.paths.assets_path(workspace_id), {})

    def get_asset(self, workspace_id: str, asset_id: str) -> dict[str, Any] | None:
        return self.load_manifest(workspace_id).get(asset_id)

    def asset_url(self, workspace_id: str, asset_id: str) -> str:
        base = get_settings().public_base_url.rstrip("/")
        path = f"/v1/workspaces/{workspace_id}/assets/{asset_id}"
        return f"{base}{path}" if base else path

    def build_from_content_list(
        self,
        workspace_id: str,
        document_id: str,
        filename: str,
        content_list: list[dict[str, Any]],
        content_list_path: Path | None = None,
    ) -> dict[str, Any]:
        manifest = self.load_manifest(workspace_id)
        root = self.paths.ensure_workspace(workspace_id)
        safe_document_id = safe_id(document_id)
        assets_dir = root / "assets" / safe_document_id
        assets_dir.mkdir(parents=True, exist_ok=True)
        content_root = content_list_path.parent if content_list_path else root / "parsed"

        # Drop stale assets for this document from manifest; files are overwritten by id.
        manifest = {
            asset_id: value
            for asset_id, value in manifest.items()
            if value.get("document_id") != document_id
        }

        for index, item in enumerate(content_list):
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "text").lower()
            if item_type not in MEDIA_TYPES:
                continue

            raw_path = item.get("img_path") or item.get("image_path") or item.get("table_img_path")
            source_path = self._resolve_media_path(raw_path, content_root)
            asset_hash = hashlib.sha1(
                f"{document_id}:{index}:{item_type}:{raw_path or _item_title(item, '')}".encode("utf-8")
            ).hexdigest()[:16]
            asset_id = f"{safe_document_id}:{item_type}:{asset_hash}"
            copied_path = None
            mime_type = None
            if source_path and source_path.exists():
                ext = source_path.suffix or ".bin"
                dest = assets_dir / f"{asset_hash}{ext}"
                shutil.copy2(source_path, dest)
                copied_path = dest
                mime_type = mimetypes.guess_type(dest.name)[0]

            html = str(item.get("table_body") or "") if item_type == "table" else ""
            latex = str(item.get("latex") or item.get("text") or "") if item_type == "equation" else ""
            title = _item_title(item, f"{item_type.title()} {index + 1}")
            manifest[asset_id] = {
                "asset_id": asset_id,
                "type": item_type,
                "document_id": document_id,
                "filename": filename,
                "title": title,
                "caption": title,
                "page": item.get("page_idx"),
                "bbox": item.get("bbox"),
                "mime_type": mime_type,
                "path": str(copied_path) if copied_path else None,
                "source_path": str(source_path) if source_path else None,
                "html": html,
                "latex": latex,
                "content": item.get("content") or item.get("text") or "",
                "created_at": utc_now(),
            }

        write_json(self.paths.assets_path(workspace_id), manifest)
        return manifest

    @staticmethod
    def _resolve_media_path(raw_path: Any, content_root: Path) -> Path | None:
        if not raw_path:
            return None
        candidate = Path(str(raw_path))
        if candidate.is_absolute():
            return candidate
        relative = content_root / candidate
        if relative.exists():
            return relative
        # MinerU content_list typically stores images/foo.jpg beside the JSON.
        for parent in [content_root, *content_root.parents]:
            probe = parent / candidate
            if probe.exists():
                return probe
        return relative

    def as_display(self, workspace_id: str, asset: dict[str, Any]) -> dict[str, Any]:
        asset_id = asset["asset_id"]
        payload = {
            "widget_type": asset.get("type", "asset"),
            "title": asset.get("title") or asset_id,
            "asset_id": asset_id,
            "asset_url": self.asset_url(workspace_id, asset_id) if asset.get("path") else None,
            "mime_type": asset.get("mime_type"),
            "caption": asset.get("caption"),
        }
        if asset.get("html"):
            payload["html"] = asset["html"]
        if asset.get("latex"):
            payload["latex"] = asset["latex"]
        return payload

