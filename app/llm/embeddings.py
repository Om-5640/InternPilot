"""Embedding service using fastembed (ONNX Runtime — no PyTorch, ~80 MB RAM).

Model: all-MiniLM-L6-v2  (same model, same 384-dim output as before)
Dimension: 384 — import EMBEDDING_DIM wherever you need the pgvector column size.

Usage:
    from app.llm.embeddings import embed, EMBEDDING_DIM
    vectors = await embed(["text one", "text two"])
    # vectors: list[list[float]], each inner list has EMBEDDING_DIM elements
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model() -> object:
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=EMBEDDING_MODEL)


async def embed(texts: list[str]) -> list[list[float]]:
    """Return one float vector per text, each of length EMBEDDING_DIM."""
    if not texts:
        return []
    loop = asyncio.get_event_loop()
    model = _get_model()
    result: list[list[float]] = await loop.run_in_executor(
        None,
        lambda: [v.tolist() for v in model.embed(texts)],  # type: ignore[attr-defined]
    )
    return result
