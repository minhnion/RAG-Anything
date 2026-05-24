# RAG Core Service

Standalone FastAPI service that wraps the integrated RAGAnything/LightRAG core for Canvus workspaces.

It owns:

- document parsing through MinerU Cloud or other configured parsers;
- graph/vector/index construction;
- multimodal asset manifests for image/table/equation nodes;
- full/pruned graph APIs for web and Canvus rendering;
- retrieval and multimodal QA APIs;
- per-workspace data and per-job logs.

The service keeps full graph/index data intact. Pruning only creates a display view for web/Canvus.

## Defaults

Defaults live in `config/defaults.yaml`. The current production-quality profile is based on benchmark conclusions:

- parser: `mineru_cloud`
- parse method: `api`
- graph builder: `llm_entity_relation`
- LLM provider: `openai`
- retrieval mode: `mix`
- answer mode: `multimodal_mix`
- pruning profile: `baseline_50`

NER/RE graph builders remain experimental capabilities, not defaults.

## Local Run In This Monorepo

From the repository root:

```bash
make rag-core
```

Equivalent explicit command:

```bash
uv run --project apps/rag-anything/work-space/rag_core_service   python -m uvicorn app.main:app   --host 0.0.0.0   --port 7220   --reload   --reload-dir apps/rag-anything/work-space/rag_core_service/app   --reload-dir apps/rag-anything/work-space/rag_core_service/config
```

`pyproject.toml` uses a local uv source so `gsk-raganything` resolves to `apps/rag-anything`, not a registry/GitHub package.

Create the service env file:

```bash
cd apps/rag-anything/work-space/rag_core_service
cp .env.example .env
```

Fill the keys required by your selected defaults, normally:

```env
OPENAI_API_KEY=...
MINERU_API_KEY=...
RAG_CORE_DATA_DIR=./.local-data
RAG_CORE_LOG_DIR=./.local-data/logs
```

Use `.local-data` for local dev so Docker-created `data/` files do not cause permission conflicts.

## Smoke Checks

```bash
curl http://127.0.0.1:7220/v1/health
curl http://127.0.0.1:7220/v1/capabilities
```

Create workspace:

```bash
curl -X PUT http://127.0.0.1:7220/v1/workspaces/demo   -H 'Content-Type: application/json'   -d '{"name":"Demo Canvus Workspace","config":{}}'
```

Upload and ingest:

```bash
curl -X POST http://127.0.0.1:7220/v1/workspaces/demo/documents:ingest   -F file=@/path/to/document.pdf   -F document_id=doc_001   -F filename=document.pdf   -F source=canvus
```

Poll job:

```bash
curl http://127.0.0.1:7220/v1/jobs/<job_id>
```

Get pruned graph:

```bash
curl 'http://127.0.0.1:7220/v1/workspaces/demo/graph?view=pruned&include_assets=true'
```

Ask a question:

```bash
curl -X POST http://127.0.0.1:7220/v1/workspaces/demo/query   -H 'Content-Type: application/json'   -d '{"question":"What are the main findings?","mode":"mix","include_images":true}'
```

## Multimodal Widget Contract

Graph nodes can include a `display` object:

```json
{
  "id": "asset:doc_001:image:abc123",
  "type": "image",
  "node_type": "image",
  "display": {
    "widget_type": "image",
    "title": "Figure 1",
    "asset_id": "doc_001:image:abc123",
    "asset_url": "/v1/workspaces/demo/assets/doc_001:image:abc123",
    "mime_type": "image/jpeg",
    "caption": "Figure 1"
  }
}
```

Consumers should render by `display.widget_type`:

- `text`: text/note widget.
- `image`: image widget through `asset_url`.
- `table`: table HTML through `display.html`, with note/image fallback when needed.
- `equation`: equation through `display.latex`.

The service does not expose local filesystem paths in graph display payloads. The main API rewrites RAG Core asset URLs to `/rag-core/assets/...` so web and Canvus sync can fetch media through the API facade.

## Logs

For local dev:

```text
apps/rag-anything/work-space/rag_core_service/.local-data/logs/
  rag_core_service.log
  jobs/<job_id>.log
```

For Docker, logs live under container `/data/logs`, mounted to:

```text
apps/rag-anything/work-space/rag_core_service/data/logs/
```

Useful commands:

```bash
tail -f apps/rag-anything/work-space/rag_core_service/.local-data/logs/rag_core_service.log
curl http://127.0.0.1:7220/v1/jobs/<job_id>/logs
```

## Docker

From the repository root:

```bash
docker compose -f infra/docker-compose.yml up --build rag-core
```

The standalone image build context is `apps/rag-anything` and uses `work-space/rag_core_service/Dockerfile`.

## Notes

- `DELETE /documents/{document_id}` marks the document deleted and reports `requires_rebuild=true`; physical deletion from LightRAG graph/vector storage should be handled as a rebuild flow when the product needs it.
- `PATCH /graph/nodes/{node_id}` persists metadata/display overrides and intentionally reports `vector_index_updated=false`.
- Query streaming emits SSE token events after the core answer is produced. True token-level model streaming can be added later without changing the endpoint.
