import asyncio
import sys
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from uri_backend.config import Settings
from uri_backend.database import create_engine
from uri_backend.errors import URIBackendError
from uri_backend.ingestion.adapters.conversations import (
    purge_expired_conversation_stages,
)
from uri_backend.projects.router import router as projects_router
from uri_backend.projects.service import CapabilityDenied, UnknownActor
from uri_backend.sources.router import router as sources_router

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database_engine = (
            create_engine(resolved) if resolved.database_url is not None else None
        )
        async def janitor() -> None:
            while True:
                result = await asyncio.to_thread(
                    purge_expired_conversation_stages,
                    resolved.staging_root / "conversation-exports",
                )
                if result.failures:
                    app.state.conversation_stage_cleanup_failures = result.failures
                await asyncio.sleep(max(1, resolved.conversation_stage_cleanup_seconds))

        app.state.conversation_stage_cleanup_failures = []
        app.state.conversation_stage_janitor_task = asyncio.create_task(janitor())
        try:
            yield
        finally:
            app.state.conversation_stage_janitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await app.state.conversation_stage_janitor_task
            if app.state.database_engine is not None:
                await app.state.database_engine.dispose()

    app = FastAPI(title="URI Research Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    app.include_router(projects_router)
    app.include_router(sources_router)

    @app.exception_handler(UnknownActor)
    async def unknown_actor_handler(_: Request, __: UnknownActor) -> JSONResponse:
        return JSONResponse(
            status_code=401, content={"error": {"code": "unknown_actor"}}
        )

    @app.exception_handler(CapabilityDenied)
    async def capability_denied_handler(
        _: Request, __: CapabilityDenied
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403, content={"error": {"code": "capability_denied"}}
        )

    @app.exception_handler(URIBackendError)
    async def backend_error_handler(_: Request, __: URIBackendError) -> JSONResponse:
        return JSONResponse(
            status_code=400, content={"error": {"code": "backend_error"}}
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "uri-backend"}

    @app.get("/api/operations/conversation-stages")
    async def conversation_stage_operations() -> dict[str, object]:
        task = app.state.conversation_stage_janitor_task
        return {
            "status": "healthy" if not task.done() else "degraded",
            "cleanup_failures": app.state.conversation_stage_cleanup_failures,
        }

    @app.get("/api/ready", response_model=None)
    async def ready():
        unavailable = {"status": "unavailable", "service": "uri-backend"}
        engine = app.state.database_engine
        if engine is None:
            return JSONResponse(status_code=503, content=unavailable)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError):
            return JSONResponse(status_code=503, content=unavailable)
        return {"status": "ready", "service": "uri-backend"}

    return app


app = create_app()
