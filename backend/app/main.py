"""
Application factory.

`create_app()` wires everything together:
  - lifespan (startup / shutdown)
  - exception handlers
  - route registration
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError
from app.core.lifespan import lifespan
from backend.app.api.routes import agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="cat-brain",
        description="Backend for the AI cat companion — FastAPI + LangGraph",
        version="0.2.0",
        lifespan=lifespan,
    )

    # ── Global exception handler ──────────────────────────────
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    # ── Register routers ──────────────────────────────────────
    from app.api.routes import assets, micrologs

    app.include_router(micrologs.router, prefix="/api/v1")
    app.include_router(assets.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")

    # ── Health check ──────────────────────────────────────────
    @app.get("/health", tags=["infra"])
    async def health():
        return {"status": "ok"}

    return app


app = create_app()