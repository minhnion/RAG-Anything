from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app import __version__
from app.config import get_settings
from app.core import build_capabilities, require_service_token
from app.dependencies import (
    get_asset_service,
    get_document_store,
    get_graph_service,
    get_job_manager,
    get_path_store,
    get_rag_core_service,
    get_workspace_store,
)
from app.errors import ServiceError
from app.schemas import IngestRefRequest, NodePatchRequest, PruneRequest, QueryRequest, WorkspaceCreateRequest
from app.storage import safe_filename, safe_id


router = APIRouter(prefix="/v1", dependencies=[Depends(require_service_token)])


def _parse_json_field(raw: str | None, field_name: str) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ServiceError("invalid_json", f"{field_name} is not valid JSON", 400) from exc
    if not isinstance(value, dict):
        raise ServiceError("invalid_json", f"{field_name} must be a JSON object", 400)
    return value


def _filename_with_source_suffix(preferred: str | None, source_filename: str | None) -> str:
    name = (preferred or source_filename or "document").strip() or "document"
    source_suffix = Path(source_filename or "").suffix
    if source_suffix and not Path(name).suffix:
        name = f"{name}{source_suffix}"
    return name


@router.get("/health", dependencies=[])
async def health():
    settings = get_settings()
    return {
        "status": "healthy",
        "service": settings.service_name,
        "version": __version__,
        "data_dir": str(settings.data_dir),
    }


@router.get("/capabilities")
async def capabilities():
    return build_capabilities()


@router.put("/workspaces/{workspace_id}")
async def put_workspace(workspace_id: str, request: WorkspaceCreateRequest):
    record, created = get_workspace_store().create_or_update(
        workspace_id,
        name=request.name,
        description=request.description,
        remote_id=request.remote_id,
        config=request.config,
    )
    return {
        "status": "ok",
        "workspace_id": workspace_id,
        "created": created,
        "config": record.get("config", {}),
    }


@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str):
    store = get_workspace_store()
    record = store.get(workspace_id)
    if record is None:
        raise ServiceError("workspace_not_found", "Workspace not found", 404)
    documents = get_document_store().all(workspace_id)
    stats = get_graph_service().graph_stats(workspace_id)
    indexed = sum(1 for item in documents.values() if item.get("index_state") == "completed")
    return {
        "status": "ok",
        "workspace_id": workspace_id,
        "name": record.get("name"),
        "description": record.get("description"),
        "remote_id": record.get("remote_id"),
        "document_count": len(documents),
        "indexed_document_count": indexed,
        "graph": {
            "total_nodes": stats["total_nodes"],
            "total_edges": stats["total_edges"],
        },
        "config": record.get("config", {}),
        "updated_at": record.get("updated_at"),
    }


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str):
    deleted = get_workspace_store().delete(workspace_id)
    return {"status": "ok", "workspace_id": workspace_id, "deleted": deleted}


@router.post("/workspaces/{workspace_id}/documents:ingest", status_code=202)
async def ingest_document(
    workspace_id: str,
    file: Annotated[UploadFile, File(...)],
    document_id: Annotated[str, Form(...)],
    filename: Annotated[str | None, Form()] = None,
    source: Annotated[str, Form()] = "upload",
    content_hash: Annotated[str | None, Form()] = None,
    request_id: Annotated[str | None, Form()] = None,
    options_json: Annotated[str | None, Form()] = None,
    metadata_json: Annotated[str | None, Form()] = None,
):
    core = get_rag_core_service()
    resolved_filename = _filename_with_source_suffix(filename, file.filename)
    options = _parse_json_field(options_json, "options_json")
    metadata = _parse_json_field(metadata_json, "metadata_json")
    saved_path = await core.save_upload(workspace_id, document_id, resolved_filename, file)
    return await core.enqueue_ingest(
        workspace_id,
        file_path=saved_path,
        document_id=document_id,
        filename=resolved_filename,
        source=source,
        content_hash=content_hash,
        options=options,
        metadata=metadata,
        request_id=request_id,
    )


@router.post("/workspaces/{workspace_id}/documents:ingest-ref", status_code=202)
async def ingest_document_ref(workspace_id: str, request: IngestRefRequest):
    if request.file_ref.type != "path" or not request.file_ref.path:
        raise ServiceError(
            "unsupported_file_ref",
            "Only local path file_ref is implemented in this first service module.",
            422,
        )
    source_path = Path(request.file_ref.path)
    if not source_path.exists():
        raise ServiceError("file_not_found", f"File not found: {source_path}", 404)
    root = get_path_store().ensure_workspace(workspace_id)
    dest_dir = root / "uploads" / safe_id(request.document_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    resolved_filename = _filename_with_source_suffix(request.filename, source_path.name)
    dest = dest_dir / safe_filename(resolved_filename)
    shutil.copy2(source_path, dest)
    return await get_rag_core_service().enqueue_ingest(
        workspace_id,
        file_path=dest,
        document_id=request.document_id,
        filename=resolved_filename,
        source=request.source,
        content_hash=request.content_hash,
        options=request.options,
        metadata=request.metadata,
        request_id=request.request_id,
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = get_job_manager().get(job_id)
    if job is None:
        raise ServiceError("job_not_found", "Job not found", 404)
    return {"status": "ok", "job": job.model_dump()}


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str):
    manager = get_job_manager()
    if manager.get(job_id) is None:
        raise ServiceError("job_not_found", "Job not found", 404)
    path = manager.job_log_path(job_id)
    if not path.exists():
        raise ServiceError("job_log_not_found", "Job log not found", 404)
    return FileResponse(path, media_type="text/plain", filename=path.name)


@router.get("/workspaces/{workspace_id}/documents")
async def list_documents(workspace_id: str):
    get_workspace_store().require(workspace_id)
    documents = get_document_store().all(workspace_id)
    return {"status": "ok", "workspace_id": workspace_id, "documents": list(documents.values())}


@router.get("/workspaces/{workspace_id}/documents/{document_id}")
async def get_document(workspace_id: str, document_id: str):
    document = get_document_store().get(workspace_id, document_id)
    if document is None:
        raise ServiceError("document_not_found", "Document not found", 404)
    return {"status": "ok", "workspace_id": workspace_id, **document}


@router.delete("/workspaces/{workspace_id}/documents/{document_id}")
async def delete_document(workspace_id: str, document_id: str):
    document = get_document_store().mark_deleted(workspace_id, document_id)
    if document is None:
        raise ServiceError("document_not_found", "Document not found", 404)
    return {
        "status": "ok",
        "workspace_id": workspace_id,
        "document_id": document_id,
        "deleted": True,
        "graph_changed": False,
        "requires_rebuild": True,
        "warning": "Document is marked deleted. Physical LightRAG index deletion should be handled by a rebuild job.",
    }


@router.get("/workspaces/{workspace_id}/documents/{document_id}/assets")
async def document_assets(workspace_id: str, document_id: str):
    manifest = get_asset_service().load_manifest(workspace_id)
    assets = [asset for asset in manifest.values() if asset.get("document_id") == document_id]
    return {"status": "ok", "workspace_id": workspace_id, "document_id": document_id, "assets": assets}


@router.get("/workspaces/{workspace_id}/assets/{asset_id:path}")
async def get_asset(workspace_id: str, asset_id: str):
    asset = get_asset_service().get_asset(workspace_id, asset_id)
    if asset is None or not asset.get("path"):
        raise ServiceError("asset_not_found", "Asset not found", 404)
    path = Path(asset["path"])
    if not path.exists():
        raise ServiceError("asset_file_missing", "Asset file is missing on disk", 404)
    return FileResponse(path, media_type=asset.get("mime_type"), filename=path.name)


@router.get("/workspaces/{workspace_id}/graph")
async def get_graph(
    workspace_id: str,
    view: str = Query("full", pattern="^(full|pruned)$"),
    pruning_profile: str | None = None,
    limit_nodes: int | None = None,
    include_chunks: bool = False,
    include_metadata: bool = True,
    include_assets: bool = True,
):
    get_workspace_store().require(workspace_id)
    return get_graph_service().get_graph_response(
        workspace_id,
        view=view,
        pruning_profile=pruning_profile,
        limit_nodes=limit_nodes,
        include_chunks=include_chunks,
        include_metadata=include_metadata,
        include_assets=include_assets,
    )


@router.get("/workspaces/{workspace_id}/graph/stats")
async def graph_stats(workspace_id: str):
    get_workspace_store().require(workspace_id)
    return get_graph_service().graph_stats(workspace_id)


@router.post("/workspaces/{workspace_id}/graph:prune")
async def prune_graph(workspace_id: str, request: PruneRequest):
    get_workspace_store().require(workspace_id)
    return get_graph_service().get_graph_response(
        workspace_id,
        view="pruned",
        pruning_profile=request.pruning_profile,
        limit_nodes=request.max_nodes,
        include_chunks=request.include_chunks,
        include_metadata=True,
        include_assets=request.include_assets,
    )


@router.patch("/workspaces/{workspace_id}/graph/nodes/{node_id:path}")
async def patch_node(workspace_id: str, node_id: str, request: NodePatchRequest):
    get_workspace_store().require(workspace_id)
    patch = request.model_dump(exclude_none=True)
    updated = get_graph_service().patch_node(workspace_id, node_id, patch)
    return {
        "status": "ok",
        "workspace_id": workspace_id,
        "node_id": node_id,
        "updated": updated,
        "vector_index_updated": False,
    }


@router.post("/workspaces/{workspace_id}/query")
async def query_workspace(workspace_id: str, request: QueryRequest):
    return await get_rag_core_service().query(workspace_id, request)


@router.post("/workspaces/{workspace_id}/query/stream")
async def query_workspace_stream(workspace_id: str, request: QueryRequest):
    async def events():
        response = await get_rag_core_service().query(workspace_id, request)
        answer = response.get("answer", "")
        for token in answer.split(" "):
            yield f"event: token\ndata: {json.dumps({'text': token + ' '}, ensure_ascii=False)}\n\n"
        yield f"event: final\ndata: {json.dumps(response, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")

