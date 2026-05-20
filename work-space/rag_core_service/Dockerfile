FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RAG_CORE_HOST=0.0.0.0 \
    RAG_CORE_PORT=7220 \
    RAG_CORE_DATA_DIR=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md requirements.txt setup.py ./
COPY raganything ./raganything
COPY work-space/rag_core_service ./work-space/rag_core_service
COPY work-space/src ./work-space/src

RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir -e work-space/rag_core_service

WORKDIR /app/work-space/rag_core_service

EXPOSE 7220

CMD ["sh", "-c", "uvicorn app.main:app --host ${RAG_CORE_HOST} --port ${RAG_CORE_PORT}"]

