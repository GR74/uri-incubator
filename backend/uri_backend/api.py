from fastapi import FastAPI

from uri_backend.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    app = FastAPI(title="URI Research Backend", version="0.1.0")
    app.state.settings = resolved

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "uri-backend"}

    return app


app = create_app()
