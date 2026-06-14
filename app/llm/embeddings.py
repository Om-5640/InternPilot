"""Local embedding service using sentence-transformers (free, no API calls).

Model: all-MiniLM-L6-v2
Dimension: 384 — import EMBEDDING_DIM wherever you need the pgvector column size.

Usage:
    from app.llm.embeddings import embed, EMBEDDING_DIM
    vectors = await embed(["text one", "text two"])
    # vectors: list[list[float]], each inner list has EMBEDDING_DIM elements
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer as SentenceTransformerT

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformerT:
    from sentence_transformers import SentenceTransformer

    return cast("SentenceTransformerT", SentenceTransformer(EMBEDDING_MODEL))


async def embed(texts: list[str]) -> list[list[float]]:
    """Return one float vector per text, each of length EMBEDDING_DIM."""
    if not texts:
        return []
    loop = asyncio.get_event_loop()
    model = _get_model()
    # encode() is CPU-bound → run in thread pool so the event loop is not blocked
    result: list[list[float]] = await loop.run_in_executor(
        None,
        lambda: model.encode(texts, show_progress_bar=False).tolist(),
    )
    return result
