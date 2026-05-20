from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any

import networkx as nx

from app.config import get_app_config
from app.storage import PathStore, read_json, utc_now

from .assets import AssetService
from .pruning import PruningService


def _clean_text(value: Any, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    if limit and len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if len(token) > 2}


def _split_source_ids(value: Any) -> list[str]:
    if not value:
        return []
    return [part for part in re.split(r"<SEP>|[,;\n|]+", str(value)) if part.strip()]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _edge_id(source: str, target: str, attrs: dict[str, Any]) -> str:
    raw = f"{source}|{target}|{attrs.get('keywords') or attrs.get('label') or attrs.get('description') or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


class GraphService:
    def __init__(self, paths: PathStore, asset_service: AssetService, pruning_service: PruningService):
        self.paths = paths
        self.asset_service = asset_service
        self.pruning_service = pruning_service

    def load_graph(self, workspace_id: str) -> nx.Graph:
        graph_path = self.paths.graph_path(workspace_id)
        if not graph_path.exists():
            return nx.Graph()
        return nx.read_graphml(graph_path)

    def graph_stats(self, workspace_id: str) -> dict[str, Any]:
        graph = self.load_graph(workspace_id)
        counts = Counter()
        for _, attrs in graph.nodes(data=True):
            counts[str(attrs.get("entity_type") or attrs.get("type") or "entity").lower()] += 1
        documents = read_json(self.paths.documents_path(workspace_id), {})
        indexed = sum(1 for doc in documents.values() if doc.get("index_state") == "completed")
        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "total_nodes": graph.number_of_nodes(),
            "total_edges": graph.number_of_edges(),
            "counts": dict(counts),
            "documents": {"total": len(documents), "indexed": indexed},
        }

    def get_graph_response(
        self,
        workspace_id: str,
        *,
        view: str = "full",
        pruning_profile: str | None = None,
        limit_nodes: int | None = None,
        include_chunks: bool = False,
        include_metadata: bool = True,
        include_assets: bool = True,
    ) -> dict[str, Any]:
        graph = self.load_graph(workspace_id)
        full_node_count = graph.number_of_nodes()
        full_edge_count = graph.number_of_edges()

        if not include_chunks:
            chunk_nodes = [
                node
                for node, attrs in graph.nodes(data=True)
                if str(node).startswith("chunk-")
                or str(attrs.get("entity_type") or "").lower() in {"chunk", "textchunk", "documentchunk"}
            ]
            if chunk_nodes:
                graph = graph.copy()
                graph.remove_nodes_from(chunk_nodes)

        if view == "pruned":
            default_profile = get_app_config().get("pruning.default_profile", "baseline_50")
            graph = self.pruning_service.prune(
                graph,
                profile=pruning_profile or default_profile,
                max_nodes=limit_nodes,
            )
        elif limit_nodes and graph.number_of_nodes() > limit_nodes:
            graph = self.pruning_service.prune(graph, profile="baseline_50", max_nodes=limit_nodes)

        overrides = read_json(self.paths.node_overrides_path(workspace_id), {})
        assets = self.asset_service.load_manifest(workspace_id)
        normalized_nodes = []
        node_lookup: dict[str, dict[str, Any]] = {}

        for node_id, attrs in graph.nodes(data=True):
            node = self._node_payload(workspace_id, str(node_id), attrs, include_metadata)
            if node["id"] in overrides:
                patch = overrides[node["id"]]
                for key in ("name", "description", "type"):
                    if patch.get(key) is not None:
                        node[key] = patch[key]
                node["metadata"].update(patch.get("metadata") or {})
            linked_assets = self._match_assets(node, assets)
            if linked_assets:
                node["media"] = [
                    self._asset_ref(workspace_id, asset)
                    for asset in linked_assets[:3]
                ]
            normalized_nodes.append(node)
            node_lookup[node["id"]] = node

        links = [
            self._edge_payload(str(source), str(target), attrs, include_metadata)
            for source, target, attrs in graph.edges(data=True)
        ]

        if include_assets:
            self._append_asset_widgets(workspace_id, assets, normalized_nodes, node_lookup, links, view)

        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "view": view,
            "nodes": normalized_nodes,
            "links": links,
            "metadata": {
                "total_nodes": full_node_count,
                "total_edges": full_edge_count,
                "returned_nodes": len(normalized_nodes),
                "returned_edges": len(links),
                "pruning_profile": pruning_profile if view == "pruned" else None,
                "include_assets": include_assets,
                "generated_at": utc_now(),
            },
        }

    def patch_node(self, workspace_id: str, node_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        overrides = read_json(self.paths.node_overrides_path(workspace_id), {})
        current = overrides.get(node_id, {})
        current.update({key: value for key, value in patch.items() if value is not None})
        current["updated_at"] = utc_now()
        overrides[node_id] = current
        from app.storage import write_json

        write_json(self.paths.node_overrides_path(workspace_id), overrides)
        return current

    def _node_payload(
        self,
        workspace_id: str,
        node_id: str,
        attrs: dict[str, Any],
        include_metadata: bool,
    ) -> dict[str, Any]:
        entity_type = str(attrs.get("entity_type") or attrs.get("type") or "entity")
        name = _clean_text(attrs.get("entity_id") or attrs.get("label") or node_id)
        description = _clean_text(attrs.get("description"), 800)
        source_ids = _split_source_ids(attrs.get("source_id") or attrs.get("source_ids"))
        display_type = self._display_type(entity_type, name, description)
        payload = {
            "id": node_id,
            "name": name,
            "label": name,
            "type": entity_type,
            "node_type": display_type,
            "description": description,
            "source_id": source_ids[0] if source_ids else None,
            "source_ids": source_ids,
            "file_path": attrs.get("file_path"),
            "val": max(1, len(source_ids)),
            "display": {
                "widget_type": display_type,
                "title": name,
                "text": description or name,
            },
            "media": [],
            "metadata": {},
        }
        if include_metadata:
            payload["metadata"] = _jsonable(dict(attrs))
        return payload

    @staticmethod
    def _edge_payload(source: str, target: str, attrs: dict[str, Any], include_metadata: bool) -> dict[str, Any]:
        source_ids = _split_source_ids(attrs.get("source_id") or attrs.get("source_ids"))
        label = _clean_text(attrs.get("keywords") or attrs.get("label") or "related_to", 120)
        payload = {
            "id": _edge_id(source, target, attrs),
            "source": source,
            "target": target,
            "label": label,
            "description": _clean_text(attrs.get("description"), 500),
            "weight": float(attrs.get("weight") or 1.0),
            "keywords": attrs.get("keywords"),
            "source_id": source_ids[0] if source_ids else None,
            "source_ids": source_ids,
            "metadata": _jsonable(dict(attrs)) if include_metadata else {},
        }
        return payload

    @staticmethod
    def _display_type(entity_type: str, name: str, description: str) -> str:
        haystack = f"{entity_type} {name}".lower()
        if "table" in haystack:
            return "table"
        if "figure" in haystack or "image" in haystack or "visual" in haystack:
            return "image"
        if "equation" in haystack or "formula" in haystack:
            return "equation"
        return "text"

    def _match_assets(self, node: dict[str, Any], assets: dict[str, Any]) -> list[dict[str, Any]]:
        node_doc = str(node.get("file_path") or "")
        node_text = f"{node.get('name')} {node.get('description')} {node.get('type')}"
        node_tokens = _tokens(node_text)
        matches: list[tuple[int, dict[str, Any]]] = []
        for asset in assets.values():
            asset_doc = str(asset.get("filename") or "")
            if asset_doc and node_doc and asset_doc not in node_doc and node_doc not in asset_doc:
                continue
            asset_text = f"{asset.get('title')} {asset.get('caption')} {asset.get('type')}"
            asset_tokens = _tokens(asset_text)
            overlap = len(node_tokens & asset_tokens)
            type_bonus = 2 if str(asset.get("type")) == node.get("node_type") else 0
            if overlap + type_bonus >= 2:
                matches.append((overlap + type_bonus, asset))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [asset for _, asset in matches]

    def _asset_ref(self, workspace_id: str, asset: dict[str, Any]) -> dict[str, Any]:
        return {
            "asset_id": asset["asset_id"],
            "type": asset.get("type"),
            "title": asset.get("title"),
            "caption": asset.get("caption"),
            "page": asset.get("page"),
            "bbox": asset.get("bbox"),
            "url": self.asset_service.asset_url(workspace_id, asset["asset_id"]) if asset.get("path") else None,
            "display": self.asset_service.as_display(workspace_id, asset),
        }

    def _append_asset_widgets(
        self,
        workspace_id: str,
        assets: dict[str, Any],
        nodes: list[dict[str, Any]],
        node_lookup: dict[str, dict[str, Any]],
        links: list[dict[str, Any]],
        view: str,
    ) -> None:
        if not assets:
            return
        limit = int(get_app_config().get("pruning.max_media_nodes", 8 if view == "pruned" else 50))
        appended = 0
        existing_ids = set(node_lookup)
        for asset in assets.values():
            if appended >= limit:
                break
            asset_id = f"asset:{asset['asset_id']}"
            if asset_id in existing_ids:
                continue
            display = self.asset_service.as_display(workspace_id, asset)
            node = {
                "id": asset_id,
                "name": asset.get("title") or asset["asset_id"],
                "label": asset.get("title") or asset["asset_id"],
                "type": asset.get("type", "asset"),
                "node_type": asset.get("type", "asset"),
                "description": asset.get("caption") or "",
                "source_id": None,
                "source_ids": [],
                "file_path": asset.get("filename"),
                "val": 1,
                "display": display,
                "media": [self._asset_ref(workspace_id, asset)],
                "metadata": {
                    "document_id": asset.get("document_id"),
                    "page": asset.get("page"),
                    "bbox": asset.get("bbox"),
                    "filename": asset.get("filename"),
                },
            }
            nodes.append(node)
            node_lookup[asset_id] = node
            target = self._best_asset_target(asset, node_lookup)
            if target:
                links.append(
                    {
                        "id": _edge_id(asset_id, target, {"label": "supports"}),
                        "source": asset_id,
                        "target": target,
                        "label": "supports",
                        "description": "Media widget extracted from the same document context.",
                        "weight": 0.5,
                        "keywords": "media,source",
                        "source_id": None,
                        "source_ids": [],
                        "metadata": {"generated": True},
                    }
                )
            appended += 1

    def _best_asset_target(self, asset: dict[str, Any], node_lookup: dict[str, dict[str, Any]]) -> str | None:
        asset_text = f"{asset.get('title')} {asset.get('caption')} {asset.get('type')}"
        asset_tokens = _tokens(asset_text)
        best_id = None
        best_score = 0
        for node_id, node in node_lookup.items():
            if node_id.startswith("asset:"):
                continue
            if asset.get("filename") and node.get("file_path") and str(asset["filename"]) not in str(node["file_path"]):
                continue
            score = len(asset_tokens & _tokens(f"{node.get('name')} {node.get('description')} {node.get('type')}"))
            if node.get("node_type") == asset.get("type"):
                score += 2
            if score > best_score:
                best_id = node_id
                best_score = score
        return best_id

