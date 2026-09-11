from fastapi.testclient import TestClient

from uri_backend.api import create_app


def test_health_identifies_the_backend() -> None:
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "uri-backend"}
