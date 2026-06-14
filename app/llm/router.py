"""LLM Fallback Router.

Provider chain (in order):
  1. Google Gemini 2.5 Flash
  2. Groq  (Llama 3.3 70B)
  3. OpenRouter  (OpenAI-compatible, default model: openai/gpt-4o-mini)
  4. DeepSeek  (optional backstop via DEEPSEEK_API_KEY)
  5. Ollama    (optional local backstop via OLLAMA_URL)

Behaviour:
- A provider whose API key / URL is absent (empty string) is silently skipped.
- On 429 / timeout / any error the call is transparently retried on the next provider.
- BACKOFF_S is awaited between provider attempts to be polite.
- Returns the text content of the first successful completion.
- Raises RuntimeError when every provider fails.

Public API:  ``await complete(messages, **opts) -> str``
Messages follow the OpenAI message format:
  [{"role": "system"|"user"|"assistant", "content": "..."}]
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

Message = dict[str, str]

PROVIDER_TIMEOUT: float = 30.0
BACKOFF_S: float = 0.5


# ---------------------------------------------------------------------------
# Sentinel — raised when a provider is skipped (no key configured).
# Not logged as an error.
# ---------------------------------------------------------------------------

class _ProviderSkippedError(Exception):
    pass


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

async def _try_gemini(messages: list[Message], **opts: Any) -> str:
    if not settings.GEMINI_API_KEY:
        raise _ProviderSkippedError("GEMINI_API_KEY not set")

    import google.generativeai as genai

    genai.configure(api_key=settings.GEMINI_API_KEY)  # type: ignore[attr-defined]

    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    chat_msgs = [m for m in messages if m["role"] != "system"]

    model_kwargs: dict[str, Any] = {}
    if system_parts:
        model_kwargs["system_instruction"] = "\n".join(system_parts)

    model = genai.GenerativeModel("gemini-2.5-flash", **model_kwargs)  # type: ignore[attr-defined]

    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in chat_msgs
    ]
    if not contents:
        contents = [{"role": "user", "parts": [{"text": ""}]}]

    response = await asyncio.wait_for(
        model.generate_content_async(contents),
        timeout=PROVIDER_TIMEOUT,
    )
    return str(response.text)


async def _try_groq(messages: list[Message], **opts: Any) -> str:
    if not settings.GROQ_API_KEY:
        raise _ProviderSkippedError("GROQ_API_KEY not set")

    from groq import AsyncGroq

    client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    # Remove opts that Groq doesn't support
    allowed = {k: v for k, v in opts.items() if k in {"temperature", "max_tokens", "top_p", "stop"}}
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,  # type: ignore[arg-type]
            **allowed,
        ),
        timeout=PROVIDER_TIMEOUT,
    )
    return str(resp.choices[0].message.content)


async def _try_openrouter(messages: list[Message], **opts: Any) -> str:
    if not settings.OPENROUTER_API_KEY:
        raise _ProviderSkippedError("OPENROUTER_API_KEY not set")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )
    allowed = {k: v for k, v in opts.items() if k in {"temperature", "max_tokens", "top_p", "stop", "model"}}
    model = allowed.pop("model", "openai/gpt-4o-mini")

    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            **allowed,
        ),
        timeout=PROVIDER_TIMEOUT,
    )
    content = resp.choices[0].message.content
    return str(content) if content is not None else ""


async def _try_deepseek(messages: list[Message], **opts: Any) -> str:
    if not settings.DEEPSEEK_API_KEY:
        raise _ProviderSkippedError("DEEPSEEK_API_KEY not set")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,  # type: ignore[arg-type]
        ),
        timeout=PROVIDER_TIMEOUT,
    )
    content = resp.choices[0].message.content
    return str(content) if content is not None else ""


async def _try_ollama(messages: list[Message], **opts: Any) -> str:
    if not settings.OLLAMA_URL:
        raise _ProviderSkippedError("OLLAMA_URL not set")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key="ollama",
        base_url=f"{settings.OLLAMA_URL.rstrip('/')}/v1",
    )
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=opts.get("model", "llama3"),
            messages=messages,  # type: ignore[arg-type]
        ),
        timeout=PROVIDER_TIMEOUT,
    )
    content = resp.choices[0].message.content
    return str(content) if content is not None else ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def complete(messages: list[Message], **opts: Any) -> str:
    """Return the first successful LLM completion, falling back across providers.

    Provider list is resolved at call time so mocker.patch.object works in tests.
    """
    # Resolved at call time → patches applied to module attrs are respected
    providers: list[tuple[str, Callable[..., Awaitable[str]]]] = [
        ("gemini", _try_gemini),
        ("groq", _try_groq),
        ("openrouter", _try_openrouter),
        ("deepseek", _try_deepseek),
        ("ollama", _try_ollama),
    ]
    last_error: Exception | None = None

    for name, fn in providers:
        try:
            result = await fn(messages, **opts)
            logger.info("llm.served_by=%s", name)
            return result
        except _ProviderSkippedError:
            continue
        except Exception as exc:
            logger.warning("llm.provider_failed provider=%s error=%s", name, exc)
            last_error = exc
            await asyncio.sleep(BACKOFF_S)

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")
