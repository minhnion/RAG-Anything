from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.jobs import JobManager
from app.services import AssetService, GraphService, PruningService, RAGCoreService
from app.storage import DocumentStore, PathStore, WorkspaceStore


@lru_cache(maxsize=1)
def get_path_store() -> PathStore:
    return PathStore(get_settings().data_dir)


@lru_cache(maxsize=1)
def get_workspace_store() -> WorkspaceStore:
    return WorkspaceStore(get_path_store())


@lru_cache(maxsize=1)
def get_document_store() -> DocumentStore:
    return DocumentStore(get_path_store())


@lru_cache(maxsize=1)
def get_job_manager() -> JobManager:
    return JobManager(get_path_store())


@lru_cache(maxsize=1)
def get_asset_service() -> AssetService:
    return AssetService(get_path_store())


@lru_cache(maxsize=1)
def get_pruning_service() -> PruningService:
    return PruningService()


@lru_cache(maxsize=1)
def get_graph_service() -> GraphService:
    return GraphService(get_path_store(), get_asset_service(), get_pruning_service())


@lru_cache(maxsize=1)
def get_rag_core_service() -> RAGCoreService:
    return RAGCoreService(
        get_settings(),
        get_path_store(),
        get_workspace_store(),
        get_document_store(),
        get_job_manager(),
        get_asset_service(),
        get_graph_service(),
    )

