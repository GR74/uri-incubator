from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from uri_backend.ingestion.adapters.git import GitAdapter, UnsafeSourcePath
from uri_backend.ingestion.contracts import AdapterInput
from uri_backend.sources.schemas import GitSourceCommand


@dataclass(frozen=True)
class GitFixtureRepository:
    root: Path
    first_sha: str
    last_sha: str

    def command(self, **changes: object) -> GitSourceCommand:
        values: dict[str, object] = {
            "repository_root": self.root,
            "ref_name": "refs/heads/pilot",
            "start_commit": self.first_sha,
            "end_commit": self.last_sha,
            "include_paths": ["analysis/**", "methods.md"],
        }
        values.update(changes)
        return GitSourceCommand(**values)

    def context(self, command: GitSourceCommand) -> AdapterInput:
        return AdapterInput(
            artifact_path=self.root / "unused-manifest.json",
            family="git",
            media_type="application/vnd.uri.git-manifest+json",
            metadata={"git_command": command.model_dump(mode="json")},
        )


@pytest.fixture
def git_fixture_repo(tmp_path: Path) -> GitFixtureRepository:
    root = tmp_path / "synthetic-repository"
    root.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, text=True, capture_output=True
        ).stdout.strip()

    git("init", "--initial-branch=pilot")
    git("config", "user.name", "Synthetic Researcher")
    git("config", "user.email", "synthetic@example.test")
    (root / "analysis").mkdir()
    (root / "private").mkdir()
    (root / "analysis" / "run.py").write_text(
        "print('safe analysis')\n", encoding="utf-8"
    )
    (root / "methods.md").write_text("# Methods\n", encoding="utf-8")
    (root / "private" / "raw_subject.csv").write_text(
        "synthetic,not-a-participant\n", encoding="utf-8"
    )
    git("add", ".")
    git("commit", "-m", "Add synthetic study files")
    first = git("rev-parse", "HEAD")
    (root / "analysis" / "run.py").write_text(
        "print('safe analysis v2')\n", encoding="utf-8"
    )
    git("add", "analysis/run.py")
    git("commit", "-m", "Refine analysis")
    return GitFixtureRepository(root.resolve(), first, git("rev-parse", "HEAD"))


def test_git_import_is_limited_to_ref_range_and_paths(
    git_fixture_repo: GitFixtureRepository,
) -> None:
    command = git_fixture_repo.command()
    before = subprocess.run(
        ["git", "-C", str(git_fixture_repo.root), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    ).stdout

    result = GitAdapter().normalize(git_fixture_repo.context(command))

    after = subprocess.run(
        ["git", "-C", str(git_fixture_repo.root), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    ).stdout
    paths = {part.metadata.get("path") for part in result.parts}
    assert "analysis/run.py" in paths
    assert "private/raw_subject.csv" not in paths
    assert {
        part.metadata["commit_sha"] for part in result.parts if part.kind == "commit"
    } == {
        git_fixture_repo.first_sha,
        git_fixture_repo.last_sha,
    }
    assert before == after == b""


def test_git_import_rejects_repository_escape(
    git_fixture_repo: GitFixtureRepository, tmp_path: Path
) -> None:
    command = git_fixture_repo.command(repository_root=tmp_path / "..")
    with pytest.raises(UnsafeSourcePath):
        GitAdapter().inventory(command)
