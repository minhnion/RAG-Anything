from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import router
from app.dependencies import get_job_manager
from app.errors import ServiceError, service_error_handler, unhandled_error_handler
from app.logging_config import configure_logging


def create_app() -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await get_job_manager().shutdown()

    app = FastAPI(
        title="RAG Core Service",
        version=__version__,
        description="Standalone RAGAnything core API for Canvus workspaces.",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    return app


app = create_app()

