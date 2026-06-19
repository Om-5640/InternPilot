"""Generic structured-data extractor using the LLM fallback router.

Usage:
    from app.llm.extract import extract_structured
    from app.schemas.profile import ResumeExtract

    result = await extract_structured(
        text=resume_text,
        schema=ResumeExtract,
        instructions="Extract the candidate's professional information.",
    )
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ValidationError

from app.core.errors import APIError
from app.llm.router import complete

logger = logging.getLogger(__name__)


def _strip_fences(raw: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences from LLM output."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        # Split on the opening fence
        rest = stripped[3:]
        if rest.startswith("json"):
            rest = rest[4:]
        # Find the closing fence
        close = rest.rfind("```")
        if close != -1:
            rest = rest[:close]
        return rest.strip()
    return stripped


def _parse_output[T: BaseModel](raw: str, schema: type[T]) -> T:
    cleaned = _strip_fences(raw)
    data: dict[str, object] = json.loads(cleaned)
    return schema(**data)


async def extract_structured[T: BaseModel](
    text: str,
    schema: type[T],
    instructions: str,
) -> T:
    """Extract structured data from *text* into *schema* via the LLM router.

    Retries once if the first response is not valid JSON or fails Pydantic
    validation.  Raises APIError(422, 'extraction_failed') on second failure.
    """
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    system_msg: dict[str, str] = {
        "role": "system",
        "content": (
            "You are a structured data extractor. "
            "You ONLY return valid JSON objects — no markdown fences, no prose."
        ),
    }
    user_msg: dict[str, str] = {
        "role": "user",
        "content": (
            f"{instructions}\n\n"
            f"Text to extract from:\n{text}\n\n"
            f"Return a JSON object matching this schema:\n{schema_json}\n\n"
            "Return ONLY a valid JSON object, no markdown, no prose."
        ),
    }
    messages: list[dict[str, str]] = [system_msg, user_msg]

    first_raw = await complete(messages)
    try:
        return _parse_output(first_raw, schema)
    except (json.JSONDecodeError, ValidationError, TypeError) as first_err:
        logger.warning("extract_first_attempt_failed schema=%s err=%s", schema.__name__, first_err)

    retry_messages = messages + [
        {"role": "assistant", "content": first_raw},
        {
            "role": "user",
            "content": (
                "Your last output was not valid JSON. "
                "Return ONLY a raw JSON object — no backticks, no markdown fences, no prose. "
                "Start with { and end with }."
            ),
        },
    ]
    second_raw = await complete(retry_messages)
    try:
        return _parse_output(second_raw, schema)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.error(
            "extract_both_attempts_failed schema=%s first_err=%s second_err=%s",
            schema.__name__, first_err if "first_err" in dir() else "unknown", exc,
        )
        if isinstance(exc, json.JSONDecodeError):
            raise APIError(
                422, "extraction_failed",
                "The résumé text could not be parsed into structured data. "
                "Try a text-based PDF (not a scanned image) or a DOCX file."
            ) from exc
        raise APIError(
            422, "extraction_failed",
            "Could not extract structured data from the résumé. "
            "Ensure it contains text-based content (not a scanned image)."
        ) from exc
