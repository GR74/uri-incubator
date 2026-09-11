from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from uri_backend.config import Settings
from uri_backend.database import create_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database_engine = (
            create_engine(resolved) if resolved.database_url is not None else None
        )
        try:
            yield
        finally:
            if app.state.database_engine is not None:
                await app.state.database_engine.dispose()

    app = FastAPI(title="URI Research Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "uri-backend"}

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
