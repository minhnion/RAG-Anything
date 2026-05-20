from __future__ import annotations

from app import __version__
from app.config import get_app_config


def build_capabilities() -> dict:
    cfg = get_app_config()
    return {
        "status": "ok",
        "service": "rag-core",
        "version": __version__,
        "parsers": cfg.get("capabilities.parsers", []),
        "parse_methods": cfg.get("capabilities.parse_methods", ["auto", "api", "ocr", "text", "vlm"]),
        "graph_builders": cfg.get("capabilities.graph_builders", []),
        "query_modes": cfg.get("capabilities.query_modes", ["local", "global", "hybrid", "naive", "mix"]),
        "rerankers": cfg.get("capabilities.rerankers", []),
        "answer_modes": cfg.get("capabilities.answer_modes", []),
        "pruning_profiles": cfg.get("pruning.profiles", []),
        "defaults": {
            "parser": cfg.get("parser.default"),
            "pipeline_profile": cfg.get("pipeline.profile"),
            "llm_provider": cfg.get("llm.provider"),
            "retrieval_mode": cfg.get("retrieval.mode"),
            "answer_mode": cfg.get("answer.mode"),
            "pruning_profile": cfg.get("pruning.default_profile"),
        },
    }

