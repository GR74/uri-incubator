"""Real synthetic HTTP/process smoke, restricted to URI_TEST_DATABASE_URL."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg

BACKEND = Path(__file__).resolve().parents[1]


def stop_tree(process):
    if process is None or process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=True,
            capture_output=True,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=10)


def launch(script, environment):
    return subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        if sys.platform == "win32"
        else 0,
    )


def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Synthetic smoke condition timed out")


def main():
    database = os.environ["URI_TEST_DATABASE_URL"]
    assert database.startswith("postgresql+psycopg://")
    with tempfile.TemporaryDirectory(prefix="uri-final-smoke-") as temporary:
        root = Path(temporary)
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("URI_")
        }
        environment.update(
            {
                "URI_DATABASE_URL": database,
                "URI_TEST_DATABASE_URL": database,
                "URI_ARTIFACT_ROOT": str(root / "artifacts"),
                "URI_STAGING_ROOT": str(root / "staging"),
                "URI_PILOT_MODE": "true",
                "URI_JOB_LEASE_SECONDS": "1",
                "URI_JOB_HEARTBEAT_INTERVAL_SECONDS": ".1",
                "URI_JOB_POLL_INTERVAL_SECONDS": ".05",
                "SMOKE_STARTED": str(root / "started"),
            }
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        api_script = f"import uvicorn; original = uvicorn.run; uvicorn.run = lambda *a, **kw: original(*a, **{{**kw, 'port': {port}}}); from uri_backend.api import main; main()"
        slow_worker = """
import os, signal, threading, time
from pathlib import Path
from uri_backend.ingestion.adapters.documents import DocumentAdapter
original = DocumentAdapter.normalize
def slow(self, context):
    Path(os.environ['SMOKE_STARTED']).touch()
    if os.environ.get('SMOKE_SHUTDOWN') == '1':
        threading.Timer(.2, lambda: signal.raise_signal(signal.SIGTERM)).start()
    time.sleep(3)
    return original(self, context)
DocumentAdapter.normalize = slow
from uri_backend.ingestion.worker import main
main()
"""
        api = worker = None
        try:
            name = f"Synthetic final smoke {uuid4()}"
            subprocess.run(
                [
                    sys.executable,
                    "scripts/seed_clearermind_pilot.py",
                    "--repository",
                    "synthetic://smoke",
                    "--ref",
                    "synthetic-main",
                    "--start-commit",
                    "aaaaaaa",
                    "--end-commit",
                    "bbbbbbb",
                    "--conversation-id",
                    "synthetic-conversation",
                    "--project-name",
                    name,
                ],
                cwd=BACKEND,
                env=environment,
                capture_output=True,
                check=True,
                timeout=15,
            )
            with psycopg.connect(
                database.replace("postgresql+psycopg://", "postgresql://"),
                autocommit=True,
            ) as connection:
                assert connection.info.server_version // 10000 == 16
                assert connection.execute(
                    "SELECT extname FROM pg_extension WHERE extname='vector'"
                ).fetchone() == ("vector",)
                (actor,) = connection.execute(
                    "SELECT m.user_id FROM project_memberships m JOIN projects p ON p.id=m.project_id WHERE p.name=%s",
                    (name,),
                ).fetchone()
                api = launch(api_script, environment)
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", timeout=5
                ) as client:

                    def ready():
                        try:
                            return client.get("/api/ready").status_code == 200
                        except httpx.TransportError:
                            return False

                    wait_until(ready)
                    assert str(actor) in {
                        item["id"] for item in client.get("/api/pilot/actors").json()
                    }
                    headers = {"X-URI-User-ID": str(actor)}
                    project = client.post(
                        "/api/projects", headers=headers, json={"name": name + " HTTP"}
                    ).json()["id"]
                    upload_url = f"/api/projects/{project}/sources/uploads"
                    params = {
                        "family": "document",
                        "external_id": "synthetic.md",
                        "native_version": "v1",
                        "media_type": "text/markdown",
                    }
                    payload = (
                        b"# Synthetic method\n\nUse the reviewed synthetic pipeline."
                    )
                    created = client.post(
                        upload_url, headers=headers, params=params, content=payload
                    )
                    assert created.status_code == 202
                    version, status_url = (
                        created.json()["id"],
                        created.json()["status_url"],
                    )
                    worker = launch(slow_worker, {**environment, "SMOKE_SHUTDOWN": "1"})
                    wait_until(lambda: (root / "started").exists())
                    worker.wait(timeout=10)
                    assert worker.returncode == 0
                    assert (
                        client.get(status_url, headers=headers).json()["status"]
                        == "queued"
                    )
                    (root / "started").unlink()
                    worker = launch(slow_worker, environment)
                    wait_until(lambda: (root / "started").exists())
                    time.sleep(1.5)
                    running = connection.execute(
                        "SELECT j.status,j.attempt,j.lease_expires_at > clock_timestamp(),j.heartbeat_at > j.created_at FROM ingestion_jobs j JOIN ingestion_runs r ON r.id=j.run_id WHERE r.source_version_id=%s",
                        (version,),
                    ).fetchone()
                    assert running == ("running", 2, True, True), running

                    def completed():
                        response = client.get(status_url, headers=headers).json()
                        return response if response["status"] == "succeeded" else None

                    status = wait_until(completed)
                    assert status["part_count"] == 2
                    assert len(status["quality"]["dimensions"]) == 7
                    assert status["quality"]["normalization"]["status"] == "normalized"
                    stop_tree(worker)
                    worker = None
                    stop_tree(api)
                    api = launch(api_script, environment)
                    wait_until(ready)
                    repeated = client.post(
                        upload_url, headers=headers, params=params, content=payload
                    )
                    assert repeated.json()["id"] == version
                    assert (
                        client.get(status_url, headers=headers).json()["part_count"]
                        == 2
                    )
                    counts = connection.execute(
                        "SELECT (SELECT count(*) FROM content_parts WHERE source_version_id=%s),(SELECT count(*) FROM source_quality_assessments WHERE source_version_id=%s)",
                        (version, version),
                    ).fetchone()
                    assert counts == (2, 1)
                    print(
                        json.dumps(
                            {
                                "postgres_major": 16,
                                "pgvector": True,
                                "project_id": project,
                                "version_id": version,
                                "shutdown": "queued",
                                "restarted_attempt": 2,
                                "long_job_seconds": 3,
                                "lease_seconds": 1,
                                "heartbeat_renewed": True,
                                "status": status["status"],
                                "parts": counts[0],
                                "quality_rows": counts[1],
                                "api_restart_idempotent": True,
                            }
                        )
                    )
        finally:
            stop_tree(worker)
            stop_tree(api)


if __name__ == "__main__":
    main()
