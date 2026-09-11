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
