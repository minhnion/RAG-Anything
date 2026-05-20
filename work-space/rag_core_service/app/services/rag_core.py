from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from lightrag import QueryParam

from app.config import Settings, deep_merge
from app.errors import ServiceError
from app.jobs import JobManager
from app.storage import DocumentStore, PathStore, WorkspaceStore, safe_filename, safe_id, utc_now

from .assets import AssetService
from .graph import GraphService
from .model_factory import build_model_bundle


logger = logging.getLogger("rag_core_service.core")


RAGANYTHING_IMPORT_ERROR: Exception | None = None

try:
    from raganything import RAGAnything, RAGAnythingConfig
    from raganything.prompt import PROMPTS as RAG_PROMPTS
    from lightrag.prompt import PROMPTS as LIGHTRAG_PROMPTS
except Exception as exc:  # pragma: no cover - import error becomes runtime error in health/integration
    RAGANYTHING_IMPORT_ERROR = exc
    RAGAnything = None
    RAGAnythingConfig = None
    RAG_PROMPTS = {}
    LIGHTRAG_PROMPTS = {}


class RAGCoreService:
    def __init__(
        self,
        settings: Settings,
        paths: PathStore,
        workspaces: WorkspaceStore,
        documents: DocumentStore,
        jobs: JobManager,
        assets: AssetService,
        graph: GraphService,
    ):
        self.settings = settings
        self.paths = paths
        self.workspaces = workspaces
        self.documents = documents
        self.jobs = jobs
        self.assets = assets
        self.graph = graph
        self._locks: dict[str, asyncio.Lock] = {}

    def workspace_lock(self, workspace_id: str) -> asyncio.Lock:
        if workspace_id not in self._locks:
            self._locks[workspace_id] = asyncio.Lock()
        return self._locks[workspace_id]

    def create_workspace(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        remote_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        return self.workspaces.create_or_update(
            workspace_id,
            name=name,
            description=description,
            remote_id=remote_id,
            config=config,
        )

    async def enqueue_ingest(
        self,
        workspace_id: str,
        *,
        file_path: Path,
        document_id: str,
        filename: str,
        source: str = "upload",
        content_hash: str | None = None,
        options: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self.workspaces.require(workspace_id)
        logger.info("Enqueue ingest workspace=%s document=%s filename=%s", workspace_id, document_id, filename)
        resolved_hash = content_hash or self.sha256_file(file_path)
        current = self.documents.get(workspace_id, document_id)
        force = bool((options or {}).get("force_reprocess"))
        if (
            current
            and current.get("content_hash") == resolved_hash
            and current.get("index_state") == "completed"
            and not force
        ):
            job = self.jobs.create(
                workspace_id,
                document_id=document_id,
                request_id=request_id,
                result={"document": current, "idempotent": True},
                state="completed",
            )
            return {
                "status": "accepted",
                "workspace_id": workspace_id,
                "document_id": document_id,
                "job_id": job.job_id,
                "idempotency": {
                    "matched_existing_document": True,
                    "content_hash": resolved_hash,
                },
            }

        self.documents.upsert(
            workspace_id,
            document_id,
            {
                "filename": filename,
                "source": source,
                "content_hash": resolved_hash,
                "index_state": "queued",
                "metadata": metadata or {},
                "upload_path": str(file_path),
            },
        )
        job = self.jobs.create(workspace_id, document_id=document_id, request_id=request_id)
        self.jobs.start(
            job,
            lambda job_id: self.ingest_document(
                job_id,
                workspace_id=workspace_id,
                file_path=file_path,
                document_id=document_id,
                filename=filename,
                source=source,
                content_hash=resolved_hash,
                options=options or {},
                metadata=metadata or {},
            ),
        )
        return {
            "status": "accepted",
            "workspace_id": workspace_id,
            "document_id": document_id,
            "job_id": job.job_id,
            "idempotency": {
                "matched_existing_document": False,
                "content_hash": resolved_hash,
            },
        }

    async def ingest_document(
        self,
        job_id: str,
        *,
        workspace_id: str,
        file_path: Path,
        document_id: str,
        filename: str,
        source: str,
        content_hash: str,
        options: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        async with self.workspace_lock(workspace_id):
            if RAGAnything is None or RAGAnythingConfig is None:
                message = "RAGAnything package is not importable."
                if RAGANYTHING_IMPORT_ERROR is not None:
                    message = f"{message} Root cause: {RAGANYTHING_IMPORT_ERROR!r}"
                raise RuntimeError(message) from RAGANYTHING_IMPORT_ERROR
            logger.info("Start ingest job=%s workspace=%s document=%s file=%s", job_id, workspace_id, document_id, file_path)

            workspace = self.workspaces.require(workspace_id)
            effective_config = deep_merge(workspace.get("config", {}), options or {})
            self.documents.upsert(workspace_id, document_id, {"index_state": "parsing", "error": None})
            self.jobs.update(job_id, stage="parsing", percent=10, message="Parsing document")

            rag = self._build_rag(workspace_id, effective_config)
            content_list_path: Path | None = None
            try:
                with self._prompt_overrides(effective_config):
                    logger.info("Parsing document job=%s workspace=%s document=%s", job_id, workspace_id, document_id)
                    content_list, _parser_doc_id = await rag.parse_document(
                        str(file_path),
                        output_dir=str(self.paths.workspace_dir(workspace_id) / "parsed"),
                        display_stats=False,
                    )
                    content_list_path = self._find_latest_content_list(workspace_id, filename)
                    logger.info("Parsed %d content blocks job=%s document=%s", len(content_list), job_id, document_id)
                    self.assets.build_from_content_list(
                        workspace_id,
                        document_id,
                        filename,
                        content_list,
                        content_list_path=content_list_path,
                    )

                    self.documents.upsert(workspace_id, document_id, {"index_state": "build_graph"})
                    self.jobs.update(job_id, stage="build_graph", percent=55, message="Building graph and vector index")
                    logger.info("Insert content into RAG indexes job=%s document=%s", job_id, document_id)
                    await rag.insert_content_list(
                        content_list,
                        str(file_path),
                        doc_id=document_id,
                        display_stats=False,
                    )

                    self.jobs.update(job_id, stage="indexing", percent=90, message="Persisting indexes")
                    await self._finalize_rag(rag)
                    logger.info("Finished persisting RAG indexes job=%s document=%s", job_id, document_id)
            except Exception:
                self.documents.upsert(
                    workspace_id,
                    document_id,
                    {"index_state": "failed", "error": "See job error for details"},
                )
                try:
                    await self._finalize_rag(rag)
                except Exception:
                    pass
                logger.exception("Ingest failed job=%s workspace=%s document=%s", job_id, workspace_id, document_id)
                raise

            stats = self.graph.graph_stats(workspace_id)
            doc_record = self.documents.upsert(
                workspace_id,
                document_id,
                {
                    "filename": filename,
                    "source": source,
                    "content_hash": content_hash,
                    "index_state": "completed",
                    "parser": effective_config.get("parser", {}).get("default"),
                    "parse_method": effective_config.get("parser", {}).get("parse_method"),
                    "graph_builder": effective_config.get("pipeline", {}).get("graph_builder"),
                    "provider": effective_config.get("llm", {}).get("provider"),
                    "metadata": metadata,
                    "content_list_path": str(content_list_path) if content_list_path else None,
                    "indexed_at": utc_now(),
                    "graph": {
                        "total_nodes": stats["total_nodes"],
                        "total_edges": stats["total_edges"],
                    },
                },
            )
            logger.info("Completed ingest job=%s workspace=%s document=%s nodes=%s edges=%s", job_id, workspace_id, document_id, stats["total_nodes"], stats["total_edges"])
            return {"document": doc_record, "graph": doc_record.get("graph", {})}

    async def query(self, workspace_id: str, request) -> dict[str, Any]:
        logger.info("Start query workspace=%s request_id=%s", workspace_id, getattr(request, "request_id", None))
        workspace = self.workspaces.get(workspace_id)
        if workspace is None:
            raise ServiceError("workspace_not_found", "Workspace not found", status_code=404)
        config = workspace.get("config", {})
        start = asyncio.get_running_loop().time()
        rag = self._build_rag(workspace_id, config)
        await rag._ensure_lightrag_initialized()

        query_kwargs = self._query_kwargs(config, request.top_k, request.options)
        if request.include_images:
            query_kwargs["vlm_enhanced"] = bool(config.get("answer", {}).get("multimodal", True))
            query_kwargs["extra_safe_dirs"] = [
                str(self.paths.workspace_dir(workspace_id) / "assets"),
                str(self.paths.workspace_dir(workspace_id) / "parsed"),
            ]
        else:
            query_kwargs["vlm_enhanced"] = False

        multimodal_content = self._resolve_query_multimodal(workspace_id, request.multimodal_content)
        mode = request.mode or config.get("retrieval", {}).get("mode", "mix")
        if multimodal_content:
            answer = await rag.aquery_with_multimodal(
                request.question,
                multimodal_content=multimodal_content,
                mode=mode,
                **query_kwargs,
            )
        else:
            answer = await rag.aquery(request.question, mode=mode, **query_kwargs)
        await self._finalize_rag(rag)

        context_graph = {"nodes": [], "links": []}
        if request.include_graph_context:
            context_graph = self.graph.get_graph_response(
                workspace_id,
                view="pruned",
                pruning_profile=config.get("pruning", {}).get("default_profile", "baseline_50"),
                include_assets=request.include_images,
            )

        latency_ms = int((asyncio.get_running_loop().time() - start) * 1000)
        logger.info("Completed query workspace=%s mode=%s latency_ms=%s", workspace_id, mode, latency_ms)
        return {
            "answer": answer,
            "content_blocks": [{"type": "markdown", "markdown": answer}],
            "sources": [],
            "context": context_graph.get("nodes", [])[:50],
            "edges": context_graph.get("links", [])[:100],
            "confidence": None,
            "metadata": {
                "request_id": request.request_id,
                "workspace_id": workspace_id,
                "query_mode": mode,
                "top_k": query_kwargs.get("top_k"),
                "latency_ms": latency_ms,
                "core_version": "0.1.0",
            },
        }

    def _build_rag(self, workspace_id: str, config: dict[str, Any]):
        provider = config.get("llm", {}).get("provider", "openai")
        model_bundle = build_model_bundle(provider, self.settings, config)
        workspace_root = self.paths.ensure_workspace(workspace_id)
        parser_config = config.get("parser", {})
        rag_config = RAGAnythingConfig(
            working_dir=str(workspace_root / "rag_storage"),
            parser_output_dir=str(workspace_root / "parsed"),
            parser=parser_config.get("default", "mineru_cloud"),
            parse_method=parser_config.get("parse_method", "api"),
            parser_kwargs=self._parser_kwargs(config),
            enable_image_processing=bool(parser_config.get("extract_images", True)),
            enable_table_processing=bool(parser_config.get("extract_tables", True)),
            enable_equation_processing=bool(parser_config.get("extract_equations", True)),
            max_concurrent_files=int(config.get("pipeline", {}).get("max_concurrent_files", 1)),
        )
        return RAGAnything(
            config=rag_config,
            llm_model_func=model_bundle.llm_func,
            vision_model_func=model_bundle.vision_func,
            embedding_func=model_bundle.embedding_func,
            lightrag_kwargs=self._lightrag_kwargs(config),
        )

    def _parser_kwargs(self, config: dict[str, Any]) -> dict[str, Any]:
        parser_cfg = dict(config.get("parser", {}))
        kwargs = dict(parser_cfg.get("kwargs") or {})
        if parser_cfg.get("default", "mineru_cloud") == "mineru_cloud":
            kwargs.setdefault("api_key", self.settings.mineru_api_key)
            kwargs.setdefault("api_base_url", self.settings.mineru_api_base_url)
            kwargs.setdefault("model_version", parser_cfg.get("model_version", "vlm"))
            kwargs.setdefault("language", parser_cfg.get("language", "en"))
            kwargs.setdefault("enable_formula", bool(parser_cfg.get("extract_equations", True)))
            kwargs.setdefault("enable_table", bool(parser_cfg.get("extract_tables", True)))
            kwargs.setdefault("poll_interval_sec", int(parser_cfg.get("poll_interval_sec", 5)))
            kwargs.setdefault("timeout_sec", int(parser_cfg.get("timeout_sec", 1800)))
        return {key: value for key, value in kwargs.items() if value not in (None, "")}

    def _lightrag_kwargs(self, config: dict[str, Any]) -> dict[str, Any]:
        kwargs = dict(config.get("pipeline", {}).get("lightrag_kwargs") or {})
        if config.get("pipeline", {}).get("profile") == "medical":
            try:
                from src.prompts import MEDICAL_ENTITY_TYPES

                kwargs.setdefault("chunk_token_size", 2400)
                kwargs.setdefault("entity_extract_max_gleaning", 0)
                kwargs.setdefault("addon_params", {"entity_types": MEDICAL_ENTITY_TYPES})
            except Exception:
                kwargs.setdefault("chunk_token_size", 2400)
                kwargs.setdefault("entity_extract_max_gleaning", 0)
        return kwargs

    @staticmethod
    def _prompt_snapshot(registry) -> dict[str, Any]:
        if hasattr(registry, "snapshot"):
            return registry.snapshot()
        return dict(registry)

    @staticmethod
    def _restore_prompts(registry, snapshot: dict[str, Any]) -> None:
        if hasattr(registry, "swap"):
            registry.swap(snapshot)
            return
        registry.clear()
        registry.update(snapshot)

    @contextmanager
    def _prompt_overrides(self, config: dict[str, Any]):
        old_rag = self._prompt_snapshot(RAG_PROMPTS)
        old_lightrag = self._prompt_snapshot(LIGHTRAG_PROMPTS)
        try:
            if config.get("pipeline", {}).get("profile") == "medical":
                try:
                    from src.prompts import MEDICAL_PROMPT_OVERRIDES

                    for key, value in dict(MEDICAL_PROMPT_OVERRIDES).items():
                        if key == "lightrag_entity_extract":
                            LIGHTRAG_PROMPTS["entity_extraction"] = value
                        else:
                            RAG_PROMPTS[key] = value
                except Exception:
                    pass
            yield
        finally:
            self._restore_prompts(RAG_PROMPTS, old_rag)
            self._restore_prompts(LIGHTRAG_PROMPTS, old_lightrag)

    @staticmethod
    async def _finalize_rag(rag) -> None:
        if rag is None:
            return
        try:
            await rag.finalize_storages()
        finally:
            try:
                from lightrag.kg.shared_storage import finalize_share_data

                finalize_share_data()
            except Exception:
                pass

    def _query_kwargs(self, config: dict[str, Any], top_k: int | None, options: dict[str, Any]) -> dict[str, Any]:
        candidates = {
            "top_k": top_k or config.get("retrieval", {}).get("internal_top_k", 50),
            "chunk_top_k": options.get("chunk_top_k") or config.get("retrieval", {}).get("chunk_top_k", 12),
            "response_type": options.get("response_type") or config.get("answer", {}).get("response_type", "Multiple Paragraphs"),
            "enable_rerank": bool(options.get("reranker") and options.get("reranker") != "none"),
        }
        supported = set(inspect.signature(QueryParam).parameters)
        return {key: value for key, value in candidates.items() if key in supported}

    def _resolve_query_multimodal(self, workspace_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []
        resolved = []
        manifest = self.assets.load_manifest(workspace_id)
        for item in items:
            current = dict(item)
            asset_id = current.get("asset_id")
            asset = manifest.get(asset_id) if asset_id else None
            if asset and asset.get("path"):
                if asset.get("type") == "image":
                    current.setdefault("type", "image")
                    current.setdefault("img_path", asset["path"])
                elif asset.get("type") == "table":
                    current.setdefault("type", "table")
                    current.setdefault("table_data", asset.get("html") or asset.get("content") or "")
                elif asset.get("type") == "equation":
                    current.setdefault("type", "equation")
                    current.setdefault("latex", asset.get("latex") or asset.get("content") or "")
            resolved.append(current)
        return resolved

    def _find_latest_content_list(self, workspace_id: str, filename: str) -> Path | None:
        parsed_dir = self.paths.workspace_dir(workspace_id) / "parsed"
        stem = Path(filename).stem
        candidates = list((parsed_dir / stem).glob("**/*_content_list.json"))
        if not candidates:
            candidates = list(parsed_dir.glob("**/*_content_list.json"))
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def save_upload(self, workspace_id: str, document_id: str, filename: str, file) -> Path:
        root = self.paths.ensure_workspace(workspace_id)
        dest_dir = root / "uploads" / safe_id(document_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_filename(filename)
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        return dest

