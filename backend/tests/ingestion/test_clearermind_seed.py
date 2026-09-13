from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def test_metadata_only_seed_runs_with_explicit_synthetic_selection(
    cli_environment,
) -> None:
    """A Windows event-loop mismatch must not prevent the no-import pilot guard from running."""
    result = subprocess.run(
        [
            sys.executable,
            "scripts/seed_clearermind_pilot.py",
            "--repository",
            "synthetic://local/clearermind",
            "--ref",
            "synthetic-main",
            "--start-commit",
            "aaaaaaa",
            "--end-commit",
            "bbbbbbb",
            "--conversation-id",
            "synthetic-conversation-1",
        ],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=cli_environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "no evidence was imported" in result.stdout


def test_worker_cli_starts_against_postgresql_on_windows(cli_environment) -> None:
    """The worker must not exit from the unsupported Proactor loop before it can claim work."""
    worker = subprocess.Popen(
        [sys.executable, "-c", "from uri_backend.ingestion.worker import main; main()"],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=cli_environment,
        start_new_session=sys.platform != "win32",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        if sys.platform == "win32"
        else 0,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(3)
        assert worker.poll() is None, worker.stderr.read()
    finally:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(worker.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(worker.pid, signal.SIGTERM)
        worker.wait(timeout=5)


def test_child_environment_never_inherits_development_database(cli_environment):
    """A configured development URL must be replaced before any seed/worker child starts."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; from pathlib import Path; assert os.environ['URI_DATABASE_URL'] == os.environ['URI_TEST_DATABASE_URL']; assert 'development-must-not-be-used' not in str(dict(os.environ)); assert Path(os.environ['URI_ARTIFACT_ROOT']).is_absolute(); assert Path(os.environ['URI_STAGING_ROOT']).is_absolute(); print('isolated')",
        ],
        env=cli_environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated"
