"""Embedding tests — uses real sentence-transformers model (downloaded on first run)."""
from __future__ import annotations

import pytest

from app.llm.embeddings import EMBEDDING_DIM, embed


@pytest.mark.asyncio
async def test_embed_returns_correct_dimension() -> None:
    vectors = await embed(["hello world"])
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM


@pytest.mark.asyncio
async def test_embed_multiple_texts() -> None:
    texts = ["foo", "bar", "baz"]
    vectors = await embed(texts)
    assert len(vectors) == len(texts)
    for v in vectors:
        assert len(v) == EMBEDDING_DIM


@pytest.mark.asyncio
async def test_embed_empty_list_returns_empty() -> None:
    result = await embed([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_values_are_floats() -> None:
    vectors = await embed(["test"])
    assert all(isinstance(x, float) for x in vectors[0])


def test_embedding_dim_constant_is_correct() -> None:
    assert EMBEDDING_DIM == 384
