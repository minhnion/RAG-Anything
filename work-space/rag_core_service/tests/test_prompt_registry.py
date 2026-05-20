from __future__ import annotations

from raganything.prompt import PromptRegistry

from app.services.rag_core import RAGCoreService


def test_prompt_registry_restore_supports_snapshot_swap():
    registry = PromptRegistry()
    registry["original"] = "value"

    snapshot = RAGCoreService._prompt_snapshot(registry)
    registry["temporary"] = "override"
    RAGCoreService._restore_prompts(registry, snapshot)

    assert registry.snapshot() == {"original": "value"}


def test_prompt_restore_supports_plain_dict():
    registry = {"original": "value"}
    snapshot = RAGCoreService._prompt_snapshot(registry)
    registry["temporary"] = "override"
    RAGCoreService._restore_prompts(registry, snapshot)

    assert registry == {"original": "value"}
