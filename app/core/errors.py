from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    """Raise this anywhere in service/endpoint code to return a contract-shaped error."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={"error": {"code": self.code, "message": self.message}},
        )


# ---------------------------------------------------------------------------
# FastAPI exception handlers — wired in main.py
# ---------------------------------------------------------------------------

async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, APIError):
        return exc.to_response()
    # fallback (shouldn't reach here)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code_map: dict[int, str] = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
    }
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": str(exc.detail)}},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errs = exc.errors()
    parts = [f"{' → '.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errs]
    message = "; ".join(parts)
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": message}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
    )
