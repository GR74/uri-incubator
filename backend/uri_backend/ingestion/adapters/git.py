"""Bounded, read-only Git object ingestion."""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from uri_backend.ingestion.contracts import (
    AdapterInput,
    NormalizationResult,
    NormalizationWarning,
    NormalizedPart,
)
from uri_backend.sources.schemas import GitSourceCommand

GIT_MANIFEST_MEDIA_TYPE = "application/vnd.uri.git-manifest+json"
MAX_GIT_BLOB_BYTES = 1_000_000
_OBJECT_ID = re.compile(r"^[0-9a-fA-F]{7,64}$")
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:")
_SECRET_PATH = re.compile(
    r"(?:^|/)(?:\.?env(?:\.[^/]*)?|\.npmrc|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.[^/]*)?|"
    r"[^/]*\.(?:pem|key|p12|pfx|crt|cer|der|jks|keystore)|"
    r"(?:[^/]*[._-])?(?:secrets?|credentials?|passwords?|tokens?|private[_-]?key)(?:[._-][^/]*)?)(?:$|/)",
    re.IGNORECASE,
)


class UnsafeSourcePath(ValueError):
    pass


class InvalidGitRange(ValueError):
    pass


@dataclass(frozen=True)
class GitCommit:
    sha: str
    parents: list[str]
    author_name: str
    author_email: str
    authored_at: str
    subject: str


@dataclass(frozen=True)
class GitFile:
    path: str
    sha: str
    byte_size: int
    text: str


@dataclass(frozen=True)
class GitInventory:
    repository_root: Path
    git_directory: Path
    resolved_head_sha: str
    commits: list[GitCommit]
    files: list[GitFile]
    exclusions: list[dict[str, str]]
    range_metadata: dict[str, str]

    @property
    def total_allowed_bytes(self) -> int:
        return sum(item.byte_size for item in self.files)

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "range": self.range_metadata,
            "resolved_head_sha": self.resolved_head_sha,
            "commits": [
                {
                    "sha": x.sha,
                    "parents": x.parents,
                    "author_name": x.author_name,
                    "author_email": x.author_email,
                    "authored_at": x.authored_at,
                    "subject": x.subject,
                }
                for x in self.commits
            ],
            "files": [
                {"path": x.path, "sha": x.sha, "byte_size": x.byte_size, "text": x.text}
                for x in self.files
            ],
            "exclusions": self.exclusions,
        }


class GitAdapter:
    name = "git"
    version = "normalization-v1"

    def __init__(self, *, max_blob_bytes: int = MAX_GIT_BLOB_BYTES) -> None:
        self.max_blob_bytes = max_blob_bytes

    def supports(self, context: AdapterInput) -> bool:
        return context.family == "git" and context.media_type == GIT_MANIFEST_MEDIA_TYPE

    def inventory(self, command: GitSourceCommand) -> GitInventory:
        root = self._repository_root(command.repository_root)
        self._validate_paths(command.include_paths)
        self._validate_ref(command.ref_name)
        git_directory = Path(
            self._git(root, "rev-parse", "--absolute-git-dir")
        ).resolve(strict=True)
        head, start, end = (
            self._resolve(root, value)
            for value in (command.ref_name, command.start_commit, command.end_commit)
        )
        if not self._ancestor(root, start, end) or not self._ancestor(root, end, head):
            raise InvalidGitRange("Commits are not a connected range on the named ref.")
        commits = self._commits(root, start, end)
        files, exclusions = self._files(root, end, command.include_paths)
        return GitInventory(
            root,
            git_directory,
            head,
            commits,
            files,
            exclusions,
            {
                "ref_name": command.ref_name,
                "resolved_ref_sha": head,
                "requested_start": command.start_commit,
                "requested_end": command.end_commit,
                "resolved_start_sha": start,
                "resolved_end_sha": end,
                "policy": "inclusive_start_exclude_start_ancestors",
            },
        )

    def manifest_bytes(self, inventory: GitInventory) -> bytes:
        return json.dumps(
            inventory.manifest(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

    def normalize(self, context: AdapterInput) -> NormalizationResult:
        if not self.supports(context):
            return self._result(
                "unsupported",
                [],
                [
                    NormalizationWarning(
                        code="unsupported_git", message="Unsupported Git source."
                    )
                ],
                0.0,
            )
        try:
            command = context.metadata.get("git_command")
            manifest = (
                self.inventory(GitSourceCommand.model_validate(command)).manifest()
                if isinstance(command, dict)
                else json.loads(context.artifact_path.read_text(encoding="ascii"))
            )
            return self._normalize_manifest(manifest)
        except (UnsafeSourcePath, InvalidGitRange):
            raise
        except Exception:  # noqa: BLE001
            return self._result(
                "failed",
                [],
                [
                    NormalizationWarning(
                        code="git_parse_error",
                        message="Git manifest could not be normalized.",
                    )
                ],
                0.0,
            )

    def _normalize_manifest(self, manifest: dict[str, Any]) -> NormalizationResult:
        parts: list[NormalizedPart] = []
        for item in manifest["commits"]:
            parts.append(
                NormalizedPart(
                    ordinal=len(parts) + 1,
                    kind="commit",
                    text=item["subject"],
                    locator={"commit_sha": item["sha"]},
                    author_label=item["author_name"],
                    source_time=datetime.fromisoformat(item["authored_at"]),
                    metadata={
                        "commit_sha": item["sha"],
                        "parents": item["parents"],
                        "author_email": item["author_email"],
                    },
                )
            )
        for item in manifest["files"]:
            parts.append(
                NormalizedPart(
                    ordinal=len(parts) + 1,
                    kind="file",
                    text=item["text"],
                    locator={"path": item["path"], "blob_sha": item["sha"]},
                    metadata={
                        "path": item["path"],
                        "blob_sha": item["sha"],
                        "byte_size": item["byte_size"],
                    },
                )
            )
        warnings = (
            [
                NormalizationWarning(
                    code="git_exclusions",
                    message=f"Excluded {len(manifest.get('exclusions', []))} paths.",
                )
            ]
            if manifest.get("exclusions")
            else []
        )
        return self._result("normalized", parts, warnings, 1.0)

    def _repository_root(self, requested: Path) -> Path:
        if not requested.is_absolute():
            raise UnsafeSourcePath("Repository root must be absolute.")
        try:
            root = requested.resolve(strict=True)
        except OSError as error:
            raise UnsafeSourcePath("Repository root does not exist.") from error
        if requested != root or root.is_symlink():
            raise UnsafeSourcePath(
                "Repository root must be its approved canonical path."
            )
        try:
            top = Path(self._git(root, "rev-parse", "--show-toplevel")).resolve(
                strict=True
            )
        except InvalidGitRange as error:
            raise UnsafeSourcePath("Repository root is not a Git worktree.") from error
        if top != root:
            raise UnsafeSourcePath("Repository root must equal Git top-level.")
        return root

    def _validate_paths(self, paths: list[str]) -> None:
        for path in paths:
            pure = PurePosixPath(path)
            if (
                not path
                or path.startswith(("/", "\\"))
                or _WINDOWS_DRIVE_PATH.match(path)
                or pure.is_absolute()
                or ".." in pure.parts
                or "\\" in path
            ):
                raise UnsafeSourcePath("Include paths must be relative POSIX paths.")

    def _validate_ref(self, ref: str) -> None:
        if (
            not ref.startswith("refs/")
            or ref.startswith("-")
            or ".." in ref
            or any(c.isspace() for c in ref)
        ):
            raise InvalidGitRange("A fully-qualified named ref is required.")

    def _resolve(self, root: Path, value: str) -> str:
        if (
            value != value.strip()
            or value.startswith("-")
            or (not value.startswith("refs/") and _OBJECT_ID.fullmatch(value) is None)
        ):
            raise InvalidGitRange("Invalid Git revision.")
        return self._git(root, "rev-parse", "--verify", f"{value}^{{commit}}")

    def _ancestor(self, root: Path, older: str, newer: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
            capture_output=True,
            check=False,
        )
        if result.returncode not in (0, 1):
            raise InvalidGitRange("Git could not verify range.")
        return result.returncode == 0

    def _commits(self, root: Path, start: str, end: str) -> list[GitCommit]:
        # Reach(end) minus Reach(parents(start)); deliberately retain start.
        # Topological traversal is stable even with skewed commit timestamps.
        parents = self._git(root, "show", "-s", "--format=%P", start).split()
        shas = self._git(
            root, "rev-list", "--topo-order", "--reverse", end, "--not", *parents
        ).splitlines()
        result: list[GitCommit] = []
        for sha in shas:
            fields = self._git(
                root, "show", "-s", "--format=%H%x00%P%x00%an%x00%ae%x00%aI%x00%s", sha
            ).split("\x00")
            if len(fields) != 6:
                raise InvalidGitRange("Commit metadata could not be read.")
            result.append(
                GitCommit(
                    fields[0],
                    fields[1].split() if fields[1] else [],
                    fields[2],
                    fields[3],
                    fields[4],
                    fields[5],
                )
            )
        return result

    def _files(
        self, root: Path, end: str, includes: list[str]
    ) -> tuple[list[GitFile], list[dict[str, str]]]:
        files: list[GitFile] = []
        exclusions: list[dict[str, str]] = []
        for record in self._git_bytes(root, "ls-tree", "-r", "-z", "-l", end).split(
            b"\0"
        ):
            if not record:
                continue
            try:
                header, raw_path = record.split(b"\t", 1)
                mode, typ, sha, size = header.decode("ascii").split(maxsplit=3)
                path = raw_path.decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                exclusions.append({"path": "<invalid>", "reason": "invalid_path"})
                continue
            reason = self._reason(path, mode, typ, size, includes)
            if reason:
                exclusions.append({"path": path, "reason": reason})
                continue
            payload = self._git_bytes(root, "cat-file", "blob", sha)
            if b"\0" in payload:
                exclusions.append({"path": path, "reason": "binary_blob"})
                continue
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                exclusions.append({"path": path, "reason": "non_utf8_blob"})
                continue
            files.append(GitFile(path, sha, int(size), text))
        return files, exclusions

    def _reason(
        self, path: str, mode: str, typ: str, size: str, includes: list[str]
    ) -> str | None:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts:
            return "unsafe_tree_path"
        if mode == "120000":
            return "symlink"
        if mode == "160000" or typ == "commit":
            return "submodule"
        if typ != "blob":
            return "unsupported_object"
        if _SECRET_PATH.search(path):
            return "secret_like_filename"
        if not any(fnmatch.fnmatchcase(path, item) for item in includes):
            return "outside_include_paths"
        if int(size) > self.max_blob_bytes:
            return "oversize_blob"
        return None

    def _git(self, root: Path, *args: str) -> str:
        return self._git_bytes(root, *args).decode("utf-8").strip()

    def _git_bytes(self, root: Path, *args: str) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=False
        )
        if result.returncode:
            raise InvalidGitRange("Git object read failed.")
        return result.stdout

    def _result(
        self,
        status: str,
        parts: list[NormalizedPart],
        warnings: list[NormalizationWarning],
        coverage: float,
    ) -> NormalizationResult:
        return NormalizationResult(
            adapter=self.name,
            adapter_version=self.version,
            status=status,
            parts=parts,
            warnings=warnings,
            parse_coverage=coverage,
        )
