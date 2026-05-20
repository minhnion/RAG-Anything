from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None = None


class WorkspaceCreateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    remote_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class WorkspaceResponse(BaseModel):
    status: str = "ok"
    workspace_id: str
    created: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class FileRef(BaseModel):
    type: Literal["path", "url"] = "path"
    path: str | None = None
    url: str | None = None


class IngestRefRequest(BaseModel):
    document_id: str
    filename: str
    source: str = "canvus"
    content_hash: str | None = None
    file_ref: FileRef
    options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class JobProgress(BaseModel):
    stage: str = "pending"
    percent: int = 0
    message: str = ""


class JobRecord(BaseModel):
    job_id: str
    workspace_id: str
    document_id: str | None = None
    state: str = "pending"
    progress: JobProgress = Field(default_factory=JobProgress)
    created_at: str
    updated_at: str
    error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class QueryRequest(BaseModel):
    question: str
    mode: str | None = None
    top_k: int | None = None
    include_images: bool = True
    include_graph_context: bool = True
    multimodal_content: list[dict[str, Any]] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class PruneRequest(BaseModel):
    pruning_profile: str | None = None
    algorithm: str | None = None
    max_nodes: int | None = None
    include_chunks: bool = False
    include_assets: bool = True
    options: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class NodePatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

