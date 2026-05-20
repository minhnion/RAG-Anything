from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_and_capabilities():
    client = TestClient(create_app())

    health = client.get("/v1/health")
    assert health.status_code == 200
    assert health.json()["service"] == "rag-core"

    capabilities = client.get("/v1/capabilities")
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["status"] == "ok"
    assert "mineru_cloud" in {item["id"] for item in body["parsers"]}
    assert body["defaults"]["retrieval_mode"] == "mix"




def test_upload_filename_preserves_source_suffix():
    from app.api.routes import _filename_with_source_suffix

    assert _filename_with_source_suffix(
        "CT_MICA_full_body_segementation",
        "CT_MICA_full_body_segmentation.pdf",
    ) == "CT_MICA_full_body_segementation.pdf"
    assert _filename_with_source_suffix("report.md", "source.pdf") == "report.md"
    assert _filename_with_source_suffix(None, "source.png") == "source.png"
