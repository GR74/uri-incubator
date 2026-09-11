from __future__ import annotations

import os
import subprocess
import time


def test_metadata_only_seed_runs_with_explicit_synthetic_selection() -> None:
    """A Windows event-loop mismatch must not prevent the no-import pilot guard from running."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
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
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "no evidence was imported" in result.stdout


def test_worker_cli_starts_against_postgresql_on_windows() -> None:
    """The worker must not exit from the unsupported Proactor loop before it can claim work."""
    worker = subprocess.Popen(
        ["uv", "run", "uri-worker"],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(3)
        assert worker.poll() is None, worker.stderr.read()
    finally:
        worker.terminate()
        worker.wait(timeout=5)
