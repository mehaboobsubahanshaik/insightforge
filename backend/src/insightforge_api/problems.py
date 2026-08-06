"""RFC 9457 problem details for every error path. Correlation ids tie client
errors to server logs; SQL/tracebacks never leak to clients."""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("insightforge.problems")


def problem(request: Request, status: int, title: str, detail: str = "") -> JSONResponse:
    cid = getattr(request.state, "correlation_id", uuid.uuid4().hex)
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank", "title": title, "status": status,
            "detail": detail or title, "instance": str(request.url.path),
            "correlation_id": cid,
        },
        media_type="application/problem+json",
    )


def register_problem_handlers(app: FastAPI) -> None:
    from sqlalchemy.exc import IntegrityError

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        msg = str(exc.detail) if exc.detail else "Error"
        return problem(request, exc.status_code, msg, msg)

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return problem(request, 422, "Validation failed", f"{loc}: {first.get('msg', 'invalid')}")

    @app.exception_handler(IntegrityError)
    async def integrity_exc(request: Request, exc: IntegrityError):
        # Unique-constraint safety net: friendly 409, details only in logs.
        log.warning("integrity error: %s", exc.orig)
        return problem(
            request, 409, "Conflict", "A resource with these unique values already exists"
        )

    @app.exception_handler(Exception)
    async def unhandled_exc(request: Request, exc: Exception):
        log.exception("unhandled error")
        return problem(request, 500, "Internal error", "An unexpected error occurred")
