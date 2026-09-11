import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from uri_backend.api import create_app
from uri_backend.config import Settings


def test_health_identifies_the_backend() -> None:
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "uri-backend"}


def test_ready_reports_database_unavailability() -> None:
    app = create_app(Settings(database_url="postgresql+psycopg://uri:uri@127.0.0.1:55441/uri_test"))
    with TestClient(app) as client:
        response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "service": "uri-backend"}


def test_api_launcher_sets_windows_selector_policy_before_starting_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting Uvicorn first would recreate the PostgreSQL-incompatible Proactor loop."""
    from uri_backend import api

    calls: list[str] = []
    monkeypatch.setattr(api.sys, "platform", "win32")
    monkeypatch.setattr(
        api.asyncio, "set_event_loop_policy", lambda _: calls.append("policy")
    )
    def run(*_: object, **kwargs: object) -> None:
        assert kwargs["loop"] == "none"
        calls.append("server")

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))

    api.main()

    assert calls == ["policy", "server"]
