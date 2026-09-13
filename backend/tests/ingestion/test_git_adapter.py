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


def test_git_import_rejects_windows_drive_qualified_include_path(
    git_fixture_repo: GitFixtureRepository,
) -> None:
    with pytest.raises(UnsafeSourcePath):
        GitAdapter().inventory(
            git_fixture_repo.command(include_paths=["C:/sensitive/**"])
        )


def test_broad_git_inventory_excludes_secret_material(git_fixture_repo):
    """Broad include patterns must never capture env variants, private keys, or credentials."""
    root = git_fixture_repo.root
    names = [
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_ed25519",
        "server.pem",
        "client.p12",
        "service.pfx",
        "signing.key",
        "server.crt",
        "credentials.json",
        "api-token.txt",
    ]
    for name in names:
        (root / name).write_text("EXCLUDED_SECRET_MARKER", encoding="utf-8")
    (root / "tokenization_research.md").write_text(
        "Ordinary research", encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(root), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "Add synthetic exclusion fixtures"],
        check=True,
        capture_output=True,
    )
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    adapter = GitAdapter()
    inventory = adapter.inventory(
        git_fixture_repo.command(end_commit=head, include_paths=["**"])
    )
    assert "EXCLUDED_SECRET_MARKER" not in adapter.manifest_bytes(inventory).decode()
    assert "tokenization_research.md" in {item.path for item in inventory.files}
    assert set(names) <= {item["path"] for item in inventory.exclusions}


def test_inclusive_range_uses_reachability_across_skewed_merge_history(
    git_fixture_repo,
):
    """Date-position slicing drops merged ancestors that precede the selected start in output."""
    import os

    root = git_fixture_repo.root

    def git(*args, date="2024-01-01T00:00:00+00:00"):
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            text=True,
            env={**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
        ).strip()

    git("checkout", "-b", "merged", git_fixture_repo.first_sha)
    merged = git(
        "commit-tree",
        f"{git_fixture_repo.first_sha}^{{tree}}",
        "-p",
        git_fixture_repo.first_sha,
        "-m",
        "Reachable side change",
        date="2000-01-01T00:00:00+00:00",
    )
    git("update-ref", "refs/heads/merged", merged)
    unrelated = git(
        "commit-tree",
        f"{git_fixture_repo.first_sha}^{{tree}}",
        "-m",
        "Unrelated history",
    )
    git("update-ref", "refs/heads/unrelated", unrelated)
    git("checkout", "pilot")
    end = git(
        "commit-tree",
        f"{git_fixture_repo.last_sha}^{{tree}}",
        "-p",
        git_fixture_repo.last_sha,
        "-p",
        merged,
        "-m",
        "Merge history",
        date="1990-01-01T00:00:00+00:00",
    )
    git("update-ref", "refs/heads/pilot", end)
    adapter = GitAdapter()
    inventory = adapter.inventory(
        git_fixture_repo.command(start_commit=git_fixture_repo.last_sha, end_commit=end)
    )
    shas = [commit.sha for commit in inventory.commits]
    assert set(shas) == {git_fixture_repo.last_sha, merged, end}
    assert shas.index(end) > shas.index(merged)
    assert shas.index(end) > shas.index(git_fixture_repo.last_sha)
    manifest = inventory.manifest()
    assert manifest["range"] == {
        "ref_name": "refs/heads/pilot",
        "resolved_ref_sha": end,
        "requested_start": git_fixture_repo.last_sha,
        "requested_end": end,
        "resolved_start_sha": git_fixture_repo.last_sha,
        "resolved_end_sha": end,
        "policy": "inclusive_start_exclude_start_ancestors",
    }
    assert adapter.manifest_bytes(inventory) == adapter.manifest_bytes(
        adapter.inventory(
            git_fixture_repo.command(
                start_commit=git_fixture_repo.last_sha, end_commit=end
            )
        )
    )
