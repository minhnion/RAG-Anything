from __future__ import annotations

from typing import Any

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc

from app.config import Settings


class ModelBundle:
    def __init__(self, llm_func, vision_func, embedding_func: EmbeddingFunc):
        self.llm_func = llm_func
        self.vision_func = vision_func
        self.embedding_func = embedding_func


def build_model_bundle(provider: str, settings: Settings, config: dict[str, Any]) -> ModelBundle:
    provider = (provider or "openai").lower()
    if provider == "openai":
        llm_model = config.get("llm", {}).get("model") or settings.openai_llm_model
        vision_model = config.get("llm", {}).get("vision_model") or settings.openai_vision_model
        embed_model = config.get("embedding", {}).get("model") or settings.openai_embed_model
        embed_dim = int(config.get("embedding", {}).get("dim") or settings.openai_embed_dim)
        api_key = settings.openai_api_key
        base_url = settings.openai_base_url or None
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing for provider 'openai'.")
    elif provider == "ollama":
        llm_model = config.get("llm", {}).get("model") or settings.ollama_llm_model
        vision_model = config.get("llm", {}).get("vision_model") or settings.ollama_vision_model or llm_model
        embed_model = config.get("embedding", {}).get("model") or settings.ollama_embed_model
        embed_dim = int(config.get("embedding", {}).get("dim") or settings.ollama_embed_dim)
        api_key = settings.ollama_api_key or "ollama"
        base_url = settings.ollama_base_url or None
        if not base_url:
            raise RuntimeError("OLLAMA_BASE_URL is missing for provider 'ollama'.")
    else:
        raise RuntimeError(f"Unsupported LLM provider: {provider}")

    if not llm_model:
        raise RuntimeError(f"Missing LLM model for provider '{provider}'.")
    if not vision_model:
        raise RuntimeError(f"Missing vision model for provider '{provider}'.")
    if not embed_model:
        raise RuntimeError(f"Missing embedding model for provider '{provider}'.")

    async def llm_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        return await openai_complete_if_cache(
            model=llm_model,
            prompt=prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    async def vision_func(
        prompt,
        system_prompt=None,
        history_messages=None,
        image_data=None,
        messages=None,
        **kwargs,
    ):
        if messages:
            return await openai_complete_if_cache(
                model=vision_model,
                prompt="",
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        if image_data:
            vision_messages = [
                {"role": "system", "content": system_prompt}
                if system_prompt
                else None,
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}",
                            },
                        },
                    ],
                },
            ]
            return await openai_complete_if_cache(
                model=vision_model,
                prompt="",
                messages=[item for item in vision_messages if item is not None],
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        return await llm_func(prompt, system_prompt, history_messages, **kwargs)

    embedding_func = EmbeddingFunc(
        embedding_dim=embed_dim,
        max_token_size=8192,
        func=lambda texts: openai_embed.func(
            texts,
            model=embed_model,
            api_key=api_key,
            base_url=base_url,
        ),
    )
    return ModelBundle(llm_func, vision_func, embedding_func)

