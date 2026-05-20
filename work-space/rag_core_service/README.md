# RAG Core Service

Standalone FastAPI service that wraps the current RAGAnything/LightRAG core for
Canvus workspaces.

It owns:

- document parsing through MinerU Cloud or other configured parsers
- graph/vector/index construction
- multimodal asset manifests for image/table/equation widgets
- full/pruned graph APIs for Canvus rendering
- retrieval and multimodal QA APIs

The service keeps full graph/index data intact. Pruning only creates a display
view for Canvus.

## Defaults

Defaults live in `config/defaults.yaml`.

The current production-quality default is based on the benchmark conclusions:

- parser: `mineru_cloud`
- graph builder: `llm_entity_relation`
- LLM provider: `openai`
- retrieval mode: `mix`
- answer mode: `multimodal_mix`
- pruning profile: `baseline_50`

NER/RE backends remain listed as experimental capabilities, not defaults.

## Local Run

From repo root, activate the intended environment, then install the repo package and the service package there:

```bash
conda activate gsk-raganything
pip install -e .
pip install -e work-space/rag_core_service
```

Then create the service env file:

```bash
cp work-space/rag_core_service/.env.example work-space/rag_core_service/.env
```

Fill at least:

```bash
OPENAI_API_KEY=...
MINERU_API_KEY=...
```

Start API from the service directory so `app` resolves to `work-space/rag_core_service/app`, not `work-space/app.py`:

```bash
cd work-space/rag_core_service
uvicorn app.main:app --host 0.0.0.0 --port 7220 --reload
```

If you prefer starting from repo root, set `PYTHONPATH` to the service directory first:

```bash
PYTHONPATH=/home/azureuser/minhnion/RAG-Anything/work-space/rag_core_service \
  uvicorn app.main:app --host 0.0.0.0 --port 7220 --reload
```

Health:

```bash
curl http://127.0.0.1:7220/v1/health
```

Capabilities:

```bash
curl http://127.0.0.1:7220/v1/capabilities
```

Create workspace:

```bash
curl -X PUT http://127.0.0.1:7220/v1/workspaces/demo \
  -H 'Content-Type: application/json' \
  -d '{"name":"Demo Canvus Workspace","config":{}}'
```

Upload and ingest:

```bash
curl -X POST http://127.0.0.1:7220/v1/workspaces/demo/documents:ingest \
  -F file=@/path/to/document.pdf \
  -F document_id=doc_001 \
  -F filename=document.pdf \
  -F source=canvus
```

Poll job:

```bash
curl http://127.0.0.1:7220/v1/jobs/<job_id>
```

Get pruned graph for Canvus:

```bash
curl 'http://127.0.0.1:7220/v1/workspaces/demo/graph?view=pruned&include_assets=true'
```

Ask a question:

```bash
curl -X POST http://127.0.0.1:7220/v1/workspaces/demo/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What are the main findings?","include_images":true}'
```

## Multimodal Widget Contract

Graph nodes include a `display` object:

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

Canvus should render by `display.widget_type`:

- `text`: text widget
- `image`: image widget through `asset_url`
- `table`: table widget through `display.html`, with image fallback when present
- `equation`: equation widget through `display.latex`

The service never exposes local filesystem paths in graph display payloads.


## Logs

The service writes rotating process logs and per-job logs under:

```text
work-space/rag_core_service/data/logs/
  rag_core_service.log
  jobs/<job_id>.log
```

You can override this with `RAG_CORE_LOG_DIR` in `.env`.

Useful commands:

```bash
tail -f work-space/rag_core_service/data/logs/rag_core_service.log
tail -f work-space/rag_core_service/data/logs/jobs/<job_id>.log
curl http://127.0.0.1:7220/v1/jobs/<job_id>/logs
```

## Docker

From `work-space/rag_core_service`:

```bash
cp .env.example .env
docker compose up --build
```

API will be available at:

```text
http://127.0.0.1:7220
```

## Notes

- `DELETE /documents/{document_id}` currently marks the document deleted and
  reports `requires_rebuild=true`; physical deletion from LightRAG graph/vector
  storage should be implemented as a rebuild job when the product needs it.
- `PATCH /graph/nodes/{node_id}` currently persists metadata/display overrides.
  It intentionally reports `vector_index_updated=false`.
- Query streaming emits SSE token events after the core answer is produced. True
  token-level model streaming can be added later without changing the endpoint.

