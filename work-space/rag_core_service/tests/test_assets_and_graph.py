from __future__ import annotations

from pathlib import Path

import networkx as nx

from app.services import AssetService, GraphService, PruningService
from app.storage import PathStore, write_json


def test_asset_manifest_and_graph_display(tmp_path: Path):
    paths = PathStore(tmp_path)
    workspace_id = "ws"
    paths.ensure_workspace(workspace_id)

    result_dir = tmp_path / "parser_result"
    image_dir = result_dir / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "figure.jpg"
    image_path.write_bytes(b"fake image bytes")

    content_list = [
        {
            "type": "image",
            "img_path": "images/figure.jpg",
            "image_caption": ["Figure 1: Transformer architecture"],
            "page_idx": 2,
            "bbox": [1, 2, 3, 4],
        },
        {
            "type": "table",
            "table_caption": ["Table 1: Scores"],
            "table_body": "<table><tr><td>A</td></tr></table>",
            "page_idx": 3,
        },
    ]
    content_list_path = result_dir / "doc_content_list.json"
    write_json(content_list_path, content_list)

    assets = AssetService(paths)
    manifest = assets.build_from_content_list(
        workspace_id,
        "doc1",
        "paper.pdf",
        content_list,
        content_list_path=content_list_path,
    )
    assert len(manifest) == 2
    assert any(item["type"] == "image" and item["path"] for item in manifest.values())
    assert any(item["type"] == "table" and item["html"] for item in manifest.values())

    graph = nx.Graph()
    graph.add_node(
        "Transformer architecture",
        entity_type="concept",
        description="Figure 1 shows the Transformer architecture.",
        file_path="paper.pdf",
        source_id="chunk-1",
    )
    graph.add_node("Attention", entity_type="concept", description="Attention module.", file_path="paper.pdf")
    graph.add_edge("Transformer architecture", "Attention", description="uses", keywords="uses")
    nx.write_graphml(graph, paths.graph_path(workspace_id))

    service = GraphService(paths, assets, PruningService())
    response = service.get_graph_response(workspace_id, view="pruned", include_assets=True)

    assert response["status"] == "ok"
    assert any(node["id"].startswith("asset:") for node in response["nodes"])
    image_nodes = [node for node in response["nodes"] if node["display"]["widget_type"] == "image"]
    assert image_nodes
    assert image_nodes[0]["display"]["asset_url"].startswith("/v1/workspaces/ws/assets/")

