"""LLM fallback router tests (all providers mocked — no real API calls)."""
from __future__ import annotations

import pytest

import app.llm.router as llm_router
from app.llm.router import _ProviderSkippedError, complete

# ---------------------------------------------------------------------------
# Provider 1 succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_uses_first_provider(mocker) -> None:
    mocker.patch.object(llm_router, "_try_gemini", return_value="hello from gemini")
    result = await complete([{"role": "user", "content": "hi"}])
    assert result == "hello from gemini"


# ---------------------------------------------------------------------------
# Provider 1 raises 429 → falls back to provider 2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_on_rate_limit(mocker) -> None:
    mocker.patch.object(llm_router, "_try_gemini", side_effect=Exception("429 Too Many Requests"))
    mocker.patch.object(llm_router, "_try_groq", return_value="hello from groq")

    result = await complete([{"role": "user", "content": "hi"}])
    assert result == "hello from groq"


# ---------------------------------------------------------------------------
# Provider with missing key is skipped (raises _ProviderSkippedError)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_key_provider_is_skipped(mocker) -> None:
    mocker.patch.object(llm_router, "_try_gemini", side_effect=_ProviderSkippedError("no key"))
    mocker.patch.object(llm_router, "_try_groq", side_effect=_ProviderSkippedError("no key"))
    mocker.patch.object(llm_router, "_try_openrouter", return_value="openrouter response")

    result = await complete([{"role": "user", "content": "hi"}])
    assert result == "openrouter response"


# ---------------------------------------------------------------------------
# All providers fail → RuntimeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_providers_fail_raises(mocker) -> None:
    mocker.patch.object(llm_router, "_try_gemini", side_effect=Exception("err"))
    mocker.patch.object(llm_router, "_try_groq", side_effect=Exception("err"))
    mocker.patch.object(llm_router, "_try_openrouter", side_effect=Exception("err"))
    mocker.patch.object(llm_router, "_try_deepseek", side_effect=Exception("err"))
    mocker.patch.object(llm_router, "_try_ollama", side_effect=Exception("err"))

    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        await complete([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Skipped providers do not count as failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skipped_then_success(mocker) -> None:
    mocker.patch.object(llm_router, "_try_gemini", side_effect=_ProviderSkippedError("no key"))
    mocker.patch.object(llm_router, "_try_groq", return_value="groq wins")

    result = await complete([{"role": "user", "content": "ping"}])
    assert result == "groq wins"
