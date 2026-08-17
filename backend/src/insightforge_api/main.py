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
              enterprise.router, catalog.router, mlops.router):
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
