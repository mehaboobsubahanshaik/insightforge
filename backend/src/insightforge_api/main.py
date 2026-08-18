"""Application entrypoint: /api/v1 routers, RFC 9457 handlers, correlation
IDs, request-size guard, health/readiness, static UI, background scheduler."""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .db import session_factory
from .problems import problem, register_problem_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("insightforge")
MAX_BODY_BYTES = 20 * 1024 * 1024
# The frontend lives in its own top-level folder. In production the
# insightforge-web (nginx) container serves it; for single-process dev the
# API serves it too when the folder is present. Override with STATIC_DIR.
_static_env = os.environ.get("STATIC_DIR")
STATIC_DIR = (Path(_static_env) if _static_env
              else Path(__file__).resolve().parents[3] / "frontend" / "src")


def create_app(with_scheduler: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if with_scheduler and os.environ.get("DISABLE_SCHEDULER") != "1":
            import asyncio

            from .scheduler import scheduler_loop

            task = asyncio.create_task(scheduler_loop())
        yield
        if task:
            task.cancel()

    app = FastAPI(
        title="InsightForge API",
        version="1.0.0",
        description="AI-first, multi-tenant BI for SMBs — MVP 2 "
                    "(self-service BI and operational collaboration).",
        lifespan=lifespan,
    )
    register_problem_handlers(app)

    import hashlib as _hl
    import os as _os
    import time as _time

    _rate: dict = {}
    _idem: dict = {}

    @app.middleware("http")
    async def rate_limit_and_idempotency(request, call_next):
        """R7 API hardening. Rate limit: per bearer token (or IP),
        RATE_LIMIT_PER_MIN (default 300), honest 429 + Retry-After.
        Idempotency: POSTs with an Idempotency-Key replay the first
        response for the same key+path+body (per-process cache — a shared
        store is the multi-instance deployment step)."""
        if request.url.path.startswith("/api/"):
            ident = request.headers.get("Authorization",
                                        request.client.host if request.client
                                        else "anon")[:80]
            limit = int(_os.environ.get("RATE_LIMIT_PER_MIN", "300"))
            now = int(_time.time() // 60)
            win, count = _rate.get(ident, (now, 0))
            if win != now:
                win, count = now, 0
            if count >= limit:
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "Rate limit exceeded "
                                     f"({limit}/min). Retry shortly."},
                                    status_code=429,
                                    headers={"Retry-After": "60"})
            _rate[ident] = (win, count + 1)
            if len(_rate) > 10000:
                _rate.clear()
            ikey = request.headers.get("Idempotency-Key")
            if ikey and request.method == "POST":
                body = await request.body()
                sig = _hl.sha256(
                    f"{ident}|{ikey}|{request.url.path}".encode()
                    + body).hexdigest()
                if sig in _idem:
                    from fastapi.responses import Response as _Resp

                    status, media, payload = _idem[sig]
                    return _Resp(content=payload, status_code=status,
                                 media_type=media,
                                 headers={"Idempotency-Replayed": "true"})
                response = await call_next(request)
                if response.status_code < 500:
                    chunks = [c async for c in response.body_iterator]
                    payload = b"".join(chunks)
                    if len(_idem) > 1000:
                        _idem.clear()
                    _idem[sig] = (response.status_code,
                                  response.media_type, payload)
                    from fastapi.responses import Response as _Resp

                    return _Resp(content=payload,
                                 status_code=response.status_code,
                                 media_type=response.media_type,
                                 headers=dict(response.headers))
                return response
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request, call_next):
        """R1 security headers: API is JSON-only -> deny framing/sniffing;
        embed viewer framing is the web container's concern (nginx serves it)."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response


    @app.middleware("http")
    async def correlation_and_limits(request: Request, call_next):
        request.state.correlation_id = request.headers.get(
            "X-Correlation-Id", uuid.uuid4().hex)
        length = request.headers.get("content-length")
        if length and int(length) > MAX_BODY_BYTES:
            return problem(request, 413, "Request too large",
                           "Request bodies are limited to 20 MB")
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = request.state.correlation_id
        return response

    from .routers import (
        agents,
        ai,
        auth,
        catalog,
        connections,
        dashboards,
        datasets,
        embed,
        enterprise,
        mlops,
        partner,
        platform,
        public_api,
        tenants,
        webhooks,
        workspaces,
    )

    for r in (auth.router, tenants.router, workspaces.router, datasets.router,
              connections.router, dashboards.router, platform.router, ai.router,
              webhooks.router, public_api.router, embed.router, partner.router,
              enterprise.router, catalog.router, mlops.router, agents.router):
        app.include_router(r)

    @app.get("/api/v1/health", tags=["ops"])
    async def health():
        return {"status": "ok", "service": "insightforge-api", "version": "1.0.0"}

    @app.get("/api/v1/ready", tags=["ops"])
    async def ready():
        async with session_factory()() as s:
            await s.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}

    if STATIC_DIR.exists():
        # Single-process dev convenience: serve the frontend folder directly.
        # In the Docker stack the insightforge-web (nginx) container does this.
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")

    return app


app = create_app()
