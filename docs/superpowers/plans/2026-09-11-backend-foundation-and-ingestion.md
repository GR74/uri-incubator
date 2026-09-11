# Backend Foundation and Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable FastAPI and PostgreSQL 16 foundation that can register a ClearerMind project, enforce project capabilities, preserve immutable artifacts, and ingest all six approved source families into normalized, source-addressable content parts.

**Architecture:** Add a Python modular monolith under `backend/` while leaving the current static React build operational. PostgreSQL plus pgvector is the only database; a durable database job queue drives a separate worker, and immutable artifacts live behind a local content-addressed storage interface. This increment ends at normalized source content and quality reports; reviewed AI extraction and dashboard integration are separate plans built on these contracts.

**Tech Stack:** Python 3.11+, uv, FastAPI, Pydantic 2, SQLAlchemy 2 async, psycopg 3, Alembic, PostgreSQL 16, pgvector, pytest, HTTPX, GitPython, python-docx, pypdf, nbformat, PyYAML, Beautiful Soup 4

**Spec:** `docs/superpowers/specs/2026-09-11-local-postgres-research-backend-design.md`

## Global Constraints

- Use PostgreSQL 16 with pgvector from the first migration; never add a SQLite fallback.
- Keep the current static prototype build and `node --test tests/*.test.cjs` working throughout this increment.
- Store original evidence immutably by SHA-256 and retain exact source-native locations for normalized content.
- Do not ingest raw participant-level EEG, imaging, behavioral, or identifiable research data.
- Only explicitly selected ChatGPT conversations may leave temporary staging and become project artifacts.
- Git import is read-only and limited to an explicit repository root, named ref, commit range, and path allowlist.
- AI extraction, embeddings, GraphRAG answers, and frontend data replacement are outside this increment.
- Do not add secrets, credentials, real participant data, or a committed `.env` file.
- Use two-space indentation for existing frontend files; use Ruff defaults for new Python files.
- Every behavior-changing task follows red-green-refactor and ends in a focused commit.

---

## Planned file structure

```text
backend/
  pyproject.toml                 Python metadata, dependencies, pytest and Ruff settings
  uv.lock                        Reproducible dependency resolution
  alembic.ini                    Migration configuration
  migrations/
    env.py                       Async SQLAlchemy Alembic environment
    versions/                    Ordered PostgreSQL migrations
  uri_backend/
    __init__.py
    api.py                       FastAPI application factory and router assembly
    config.py                    Environment-backed settings
    database.py                  Async engine, sessions, transaction helpers
    errors.py                    Stable application error types and API mapping
    projects/
      models.py                  Project, user, membership and capability ORM models
      schemas.py                 Project and membership API contracts
      service.py                 Project commands and authorization checks
      router.py                  Project and member HTTP routes
    sources/
      models.py                  Source, version, artifact, part and quality ORM models
      schemas.py                 Source registration and response contracts
      artifacts.py               Local content-addressed artifact store
      service.py                 Source/version registration and quality orchestration
      router.py                  Upload, registration, preview and content routes
    ingestion/
      models.py                  Ingestion run and durable job ORM models
      contracts.py               Normalized content and adapter protocols
      queue.py                   PostgreSQL job claim, heartbeat, retry and completion
      worker.py                  Worker entry point and adapter dispatch
      quality.py                 Deterministic multidimensional source assessment
      adapters/
        base.py                  Adapter registry and common helpers
        documents.py             TXT, Markdown, DOCX and text-bearing PDF
        git.py                   Read-only ref/range/path Git ingestion
        conversations.py         ChatGPT inventory, selection and normalization
        notebooks.py             IPYNB and structured analysis-run files
        manifests.py             Dataset, DOI, accession, BibTeX and RIS manifests
        lab_notebooks.py         Generic ELN, notebook and protocol exports
  tests/
    conftest.py                  PostgreSQL integration fixtures and app client
    fixtures/                    Synthetic, participant-free source samples
    test_health.py
    test_migrations.py
    projects/
    sources/
    ingestion/
compose.yaml                     Local pgvector development and test databases
.env.example                     Non-secret configuration contract
```

Files remain grouped by product responsibility. Adapters return one normalized contract and never write directly to PostgreSQL. Services own transactions; routers contain no domain decisions.

### Task 1: Runnable Python service shell

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/uri_backend/__init__.py`
- Create: `backend/uri_backend/config.py`
- Create: `backend/uri_backend/api.py`
- Create: `backend/uri_backend/errors.py`
- Create: `backend/tests/test_health.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `uri_backend.api.create_app(settings: Settings | None = None) -> FastAPI`
- Produces: `uri_backend.config.Settings` with `database_url`, `artifact_root`, `staging_root`, and job timing fields.
- Produces: `GET /api/health -> {"status":"ok","service":"uri-backend"}` without requiring a database connection.

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient

from uri_backend.api import create_app


def test_health_identifies_the_backend() -> None:
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "uri-backend"}
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd backend; uv run pytest tests/test_health.py -q`

Expected: FAIL because `uri_backend.api` does not exist.

- [ ] **Step 3: Add the package and application factory**

Use this application boundary in `uri_backend/api.py`:

```python
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
```

Define `Settings` with `pydantic-settings`, default only filesystem paths to `backend/.local/`, require `DATABASE_URL` only when database services start, and use the `URI_` environment prefix. Add `.env`, `.local/`, `.pytest_cache/`, `.ruff_cache/`, and Python bytecode under `backend/` to `.gitignore` without changing the existing broad root exclusions.

- [ ] **Step 4: Install the locked environment and run checks**

Run: `cd backend; uv lock; uv run pytest tests/test_health.py -q; uv run ruff check uri_backend tests`

Expected: one passing test and no Ruff findings.

- [ ] **Step 5: Commit the service shell**

```bash
git add .gitignore backend/pyproject.toml backend/uv.lock backend/uri_backend backend/tests/test_health.py
git commit -m "Add the backend service shell"
```

### Task 2: PostgreSQL and migration foundation

**Files:**
- Create: `compose.yaml`
- Create: `.env.example`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/script.py.mako`
- Create: `backend/migrations/versions/20260911_0001_postgres_foundation.py`
- Create: `backend/uri_backend/database.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_migrations.py`
- Modify: `backend/uri_backend/api.py`

**Interfaces:**
- Consumes: `Settings.database_url` from Task 1.
- Produces: `create_engine(settings) -> AsyncEngine`, `session_factory(engine) -> async_sessionmaker[AsyncSession]`, and `session_scope(factory)`.
- Produces: PostgreSQL extensions `vector` and `pgcrypto`, plus an Alembic-managed schema at head.
- Produces: `GET /api/ready` that checks `SELECT 1` and returns 503 when PostgreSQL is unavailable.

- [ ] **Step 1: Write the failing PostgreSQL migration test**

```python
import sqlalchemy as sa


async def test_first_migration_enables_postgres_extensions(db_engine) -> None:
    async with db_engine.connect() as connection:
        names = set((await connection.execute(sa.text(
            "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pgcrypto')"
        ))).scalars())
    assert names == {"vector", "pgcrypto"}
```

The database fixture must read `URI_TEST_DATABASE_URL`, run `uv run alembic upgrade head`, and fail with a clear message when the URL is absent. It must never substitute SQLite.

- [ ] **Step 2: Start the isolated test database and verify RED**

Run: `docker compose --profile test up -d test-db`

Run: `$env:URI_TEST_DATABASE_URL='postgresql+psycopg://uri:uri_test_local@127.0.0.1:55441/uri_test'; cd backend; uv run pytest tests/test_migrations.py -q`

Expected: FAIL because the Alembic configuration and extension migration do not exist. If Windows has no `docker` command, run the same Compose command through the configured WSL Docker installation and keep the database bound to `127.0.0.1:55441`.

- [ ] **Step 3: Add local PostgreSQL services and the first migration**

Define `db` on `127.0.0.1:55440` and profile-gated `test-db` on `127.0.0.1:55441`, both using `pgvector/pgvector:pg16`, `pg_isready` health checks, distinct databases, and no exposed network beyond loopback. The test service uses `tmpfs`; the development service uses a named volume. `.env.example` contains URLs and explicitly labels its sample passwords local-only.

The first migration executes:

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
```

Create the async engine with `pool_pre_ping=True`; dispose it during application shutdown. `/api/ready` must open a connection and execute `SELECT 1` rather than reporting readiness from configuration alone.

- [ ] **Step 4: Verify migrations and readiness**

Run: `$env:URI_TEST_DATABASE_URL='postgresql+psycopg://uri:uri_test_local@127.0.0.1:55441/uri_test'; cd backend; uv run alembic upgrade head; uv run pytest tests/test_migrations.py tests/test_health.py -q`

Expected: all tests pass; `alembic current` reports `20260911_0001`.

- [ ] **Step 5: Commit the PostgreSQL foundation**

```bash
git add compose.yaml .env.example backend/alembic.ini backend/migrations backend/uri_backend/database.py backend/uri_backend/api.py backend/tests
git commit -m "Add the PostgreSQL foundation"
```

### Task 3: Projects, memberships, and server-side capabilities

**Files:**
- Create: `backend/uri_backend/projects/__init__.py`
- Create: `backend/uri_backend/projects/models.py`
- Create: `backend/uri_backend/projects/schemas.py`
- Create: `backend/uri_backend/projects/service.py`
- Create: `backend/uri_backend/projects/router.py`
- Create: `backend/migrations/versions/20260911_0002_projects_and_memberships.py`
- Create: `backend/tests/projects/test_project_access.py`
- Modify: `backend/uri_backend/api.py`
- Modify: `backend/migrations/env.py`

**Interfaces:**
- Produces: `User`, `Lab`, `Project`, `ProjectMembership`, and `MembershipCapability` ORM models with UUID primary keys.
- Produces: append-only `AuditEvent` rows with actor, project, action, target type/ID, timestamp, and non-sensitive metadata.
- Produces: `Capability` string enum and `require_capability(session, user_id, project_id, capability) -> ProjectMembership`.
- Produces: `POST /api/projects`, `GET /api/projects`, `GET /api/projects/{project_id}`, and member-management routes.
- Produces: local-pilot actor resolution from required `X-URI-User-ID`, plus `GET /api/pilot/actors`; unknown users receive 401.

- [ ] **Step 1: Write failing capability tests**

```python
async def test_contributor_cannot_manage_project_members(client, seeded_project) -> None:
    response = await client.post(
        f"/api/projects/{seeded_project.id}/members",
        headers={"X-URI-User-ID": str(seeded_project.contributor_id)},
        json={"user_id": str(seeded_project.reviewer_id), "role": "reviewer"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "capability_denied"


async def test_owner_can_manage_project_members(client, seeded_project) -> None:
    response = await client.post(
        f"/api/projects/{seeded_project.id}/members",
        headers={"X-URI-User-ID": str(seeded_project.owner_id)},
        json={"user_id": str(seeded_project.reviewer_id), "role": "reviewer"},
    )
    assert response.status_code == 201
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/projects/test_project_access.py -q`

Expected: FAIL because project tables and routes do not exist.

- [ ] **Step 3: Implement role defaults and explicit overrides**

Use these capability names in `projects/service.py`:

```python
class Capability(StrEnum):
    READ_PROJECT = "read_project"
    INGEST_SOURCE = "ingest_source"
    AUTHOR_DRAFT = "author_draft"
    REVIEW_DRAFT = "review_draft"
    PUBLISH_RECORD = "publish_record"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_LIFECYCLE = "manage_lifecycle"
    EXPORT_PROJECT = "export_project"
```

Default roles are `owner`, `student_lead`, `contributor`, `reviewer`, and `guest`. Store explicit allow/deny capability rows and resolve deny before allow. Create one project, its owner membership, and its audit event in one transaction. List only projects with an active readable membership. The pilot actor route returns only seeded local users and is disabled unless `URI_PILOT_MODE=true`.

- [ ] **Step 4: Verify access boundaries and migration rollback**

Run: `cd backend; uv run pytest tests/projects/test_project_access.py tests/test_migrations.py -q`

Expected: all tests pass, including unknown actor, inaccessible project, explicit deny, owner creation, and rollback/re-upgrade cases.

- [ ] **Step 5: Commit project authorization**

```bash
git add backend/uri_backend/projects backend/migrations backend/tests/projects backend/uri_backend/api.py
git commit -m "Add project capability enforcement"
```

### Task 4: Immutable artifact and source-version registry

**Files:**
- Create: `backend/uri_backend/sources/__init__.py`
- Create: `backend/uri_backend/sources/models.py`
- Create: `backend/uri_backend/sources/schemas.py`
- Create: `backend/uri_backend/sources/artifacts.py`
- Create: `backend/uri_backend/sources/service.py`
- Create: `backend/uri_backend/sources/router.py`
- Create: `backend/migrations/versions/20260911_0003_sources_and_artifacts.py`
- Create: `backend/tests/sources/test_artifact_store.py`
- Create: `backend/tests/sources/test_source_registry.py`
- Modify: `backend/uri_backend/api.py`
- Modify: `backend/migrations/env.py`

**Interfaces:**
- Produces: `ArtifactStore.put(stream: BinaryIO) -> StoredArtifact` and `ArtifactStore.open(sha256: str) -> BinaryIO`.
- Produces: `LocalArtifactStore(root: Path, staging_root: Path)` as the pilot implementation of `ArtifactStore`.
- Produces: `register_source_version(session, actor, command, artifact) -> SourceVersion`.
- Produces: `POST /api/projects/{project_id}/sources/uploads` and read-only source/version/content endpoints.
- Produces: immutable `Source`, `SourceVersion`, `Artifact`, `ContentPart`, and `SourceQualityAssessment` tables.

- [ ] **Step 1: Write failing immutability and deduplication tests**

```python
def test_identical_bytes_reuse_one_content_address(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    first = store.put(io.BytesIO(b"same evidence"))
    second = store.put(io.BytesIO(b"same evidence"))
    assert first.sha256 == second.sha256
    assert first.storage_key == second.storage_key
    assert store.open(first.sha256).read() == b"same evidence"


async def test_same_source_version_is_idempotent(source_service, project, actor, artifact) -> None:
    command = RegisterSourceVersion(
        project_id=project.id,
        family="document",
        external_id="methods.md",
        native_version="git:abc123",
        media_type="text/markdown",
    )
    first = await source_service.register(actor, command, artifact)
    second = await source_service.register(actor, command, artifact)
    assert first.id == second.id
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/sources/test_artifact_store.py tests/sources/test_source_registry.py -q`

Expected: FAIL because artifact storage and source models do not exist.

- [ ] **Step 3: Implement content addressing and source constraints**

Write incoming bytes to a temporary file under `staging_root`, compute SHA-256 while streaming, fsync, and atomically rename to `<artifact_root>/<first-two>/<remaining-hash>`. Never construct a storage path from the uploaded filename. On database registration, enforce `INGEST_SOURCE`, reject a stashed project, and use a uniqueness constraint over `(project_id, family, external_id, native_version, artifact_id)`.

Create content parts with this stable locator contract:

```python
class NormalizedPart(BaseModel):
    ordinal: int
    kind: str
    text: str
    locator: dict[str, str | int]
    author_label: str | None = None
    source_time: datetime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
```

- [ ] **Step 4: Verify cross-project access and failed writes**

Run: `cd backend; uv run pytest tests/sources -q`

Expected: all tests pass, including duplicate bytes, interrupted temporary writes, path traversal filenames, unauthorized reads, read-only stashed projects, and idempotent registration.

- [ ] **Step 5: Commit immutable source storage**

```bash
git add backend/uri_backend/sources backend/migrations backend/tests/sources backend/uri_backend/api.py
git commit -m "Add immutable research sources"
```

### Task 5: Durable PostgreSQL ingestion queue

**Files:**
- Create: `backend/uri_backend/ingestion/__init__.py`
- Create: `backend/uri_backend/ingestion/models.py`
- Create: `backend/uri_backend/ingestion/queue.py`
- Create: `backend/uri_backend/ingestion/worker.py`
- Create: `backend/migrations/versions/20260911_0004_ingestion_jobs.py`
- Create: `backend/tests/ingestion/test_job_queue.py`
- Modify: `backend/uri_backend/sources/service.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/migrations/env.py`

**Interfaces:**
- Produces: `enqueue_ingestion(session, source_version_id, idempotency_key) -> IngestionRun`.
- Produces: `claim_next_job(session, worker_id, lease_seconds) -> ClaimedJob | None` using `FOR UPDATE SKIP LOCKED`.
- Produces: `heartbeat_job`, `complete_job`, and `fail_job` with attempt history.
- Produces: console command `uri-worker` that polls, dispatches, and shuts down cleanly.

- [ ] **Step 1: Write failing concurrency and retry tests**

```python
async def test_two_workers_cannot_claim_the_same_job(job_queue, queued_job) -> None:
    first, second = await asyncio.gather(
        job_queue.claim("worker-a", lease_seconds=30),
        job_queue.claim("worker-b", lease_seconds=30),
    )
    claimed = [job for job in (first, second) if job is not None]
    assert [job.id for job in claimed] == [queued_job.id]


async def test_expired_lease_is_retryable(job_queue, expired_job) -> None:
    claimed = await job_queue.claim("worker-b", lease_seconds=30)
    assert claimed.id == expired_job.id
    assert claimed.attempt == 2
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/ingestion/test_job_queue.py -q`

Expected: FAIL because ingestion job persistence does not exist.

- [ ] **Step 3: Implement durable job transitions**

States are `queued`, `running`, `succeeded`, `failed`, and `cancelled`. Store `available_at`, `lease_expires_at`, `worker_id`, `attempt`, `max_attempts`, heartbeat, structured error code, and bounded error detail. Claim only queued jobs whose `available_at` has passed or running jobs with expired leases. Completion must verify the worker still owns the lease. Use a unique idempotency key per source version and pipeline version.

The worker dispatch loop must call one job handler, commit its outcome, and then claim again; cancellation and shutdown finish the current database transition but do not abandon it half-written.

- [ ] **Step 4: Verify queue behavior against PostgreSQL**

Run: `cd backend; uv run pytest tests/ingestion/test_job_queue.py -q`

Expected: all tests pass for concurrent claims, lease expiry, heartbeat ownership, bounded retries, idempotent enqueue, cancellation, and terminal failure.

- [ ] **Step 5: Commit the ingestion queue**

```bash
git add backend/uri_backend/ingestion backend/uri_backend/sources/service.py backend/migrations backend/tests/ingestion backend/pyproject.toml backend/uv.lock
git commit -m "Add durable ingestion jobs"
```

### Task 6: Normalization contract and document adapter

**Files:**
- Create: `backend/uri_backend/ingestion/contracts.py`
- Create: `backend/uri_backend/ingestion/adapters/__init__.py`
- Create: `backend/uri_backend/ingestion/adapters/base.py`
- Create: `backend/uri_backend/ingestion/adapters/documents.py`
- Create: `backend/tests/fixtures/document/sample.md`
- Create: `backend/tests/fixtures/document/sample.docx`
- Create: `backend/tests/fixtures/document/text.pdf`
- Create: `backend/tests/fixtures/document/scanned.pdf`
- Create: `backend/tests/ingestion/test_document_adapter.py`
- Modify: `backend/uri_backend/ingestion/worker.py`

**Interfaces:**
- Produces: `AdapterInput(artifact_path, media_type, family, metadata)`, `NormalizationWarning`, `NormalizedPart`, and `NormalizationResult` Pydantic contracts.
- Produces: `SourceAdapter.supports(context: AdapterInput) -> bool` and `SourceAdapter.normalize(context: AdapterInput) -> NormalizationResult`.
- Produces: `AdapterRegistry.resolve(family, media_type) -> SourceAdapter`.
- Produces: Markdown, text, DOCX, and text-bearing PDF normalization with stable locators.

- [ ] **Step 1: Write failing adapter contract tests**

```python
from pathlib import Path


DOCUMENT_FIXTURES = Path(__file__).parents[1] / "fixtures" / "document"
MEDIA_TYPES = {
    "sample.md": "text/markdown",
    "sample.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text.pdf": "application/pdf",
}


@pytest.mark.parametrize(
    ("fixture_name", "expected_kind", "locator_key"),
    [
        ("sample.md", "paragraph", "line_start"),
        ("sample.docx", "paragraph", "paragraph"),
        ("text.pdf", "page", "page"),
    ],
)
def test_documents_have_addressable_parts(fixture_name, expected_kind, locator_key) -> None:
    source = AdapterInput(
        artifact_path=DOCUMENT_FIXTURES / fixture_name,
        media_type=MEDIA_TYPES[fixture_name],
        family="document",
    )
    result = DocumentAdapter().normalize(source)
    assert result.status == "normalized"
    assert result.parts[0].kind == expected_kind
    assert locator_key in result.parts[0].locator


def test_scanned_pdf_requests_ocr_without_inventing_text() -> None:
    result = DocumentAdapter().normalize(AdapterInput(
        artifact_path=DOCUMENT_FIXTURES / "scanned.pdf",
        media_type="application/pdf",
        family="document",
    ))
    assert result.status == "needs_ocr"
    assert result.parts == []
    assert result.warnings[0].code == "no_extractable_text"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/ingestion/test_document_adapter.py -q`

Expected: FAIL because adapters are not implemented.

- [ ] **Step 3: Implement deterministic document normalization**

Decode TXT and Markdown strictly as UTF-8 with a visible encoding error. Split Markdown on blank-line paragraph boundaries while retaining one-based line spans. Use `python-docx` paragraphs and tables with one-based paragraph/table/row locators. Use `pypdf` page extraction with one-based pages; if normalized extracted characters are below the configured threshold, return `needs_ocr` and no parts.

Use these exact shared contracts in `contracts.py`:

```python
class AdapterInput(BaseModel):
    artifact_path: Path
    media_type: str
    family: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class NormalizationWarning(BaseModel):
    code: str
    message: str


class NormalizationResult(BaseModel):
    adapter: str
    adapter_version: str
    status: Literal["normalized", "needs_ocr", "unsupported", "failed"]
    parts: list[NormalizedPart]
    warnings: list[NormalizationWarning] = Field(default_factory=list)
    parse_coverage: float
```

Every result contains ordered parts and parse coverage between `0.0` and `1.0`. The worker deletes old unpublished parts for the same ingestion run and inserts all new parts in one transaction; it never rewrites parts belonging to a successful earlier run.

- [ ] **Step 4: Verify document parsing and worker persistence**

Run: `cd backend; uv run pytest tests/ingestion/test_document_adapter.py -q`

Expected: all tests pass for headings, paragraphs, DOCX tables, PDF pages, empty files, malformed files, Unicode text, and OCR-required PDFs.

- [ ] **Step 5: Commit document normalization**

```bash
git add backend/uri_backend/ingestion backend/tests/fixtures/document backend/tests/ingestion/test_document_adapter.py
git commit -m "Normalize research documents"
```

### Task 7: Read-only Git source adapter

**Files:**
- Create: `backend/uri_backend/ingestion/adapters/git.py`
- Create: `backend/tests/ingestion/test_git_adapter.py`
- Modify: `backend/uri_backend/sources/schemas.py`
- Modify: `backend/uri_backend/sources/router.py`
- Modify: `backend/uri_backend/ingestion/adapters/__init__.py`

**Interfaces:**
- Produces: `GitSourceCommand(repository_root, ref_name, start_commit, end_commit, include_paths)`.
- Produces: `GitAdapter.inventory(command) -> GitInventory` and `GitAdapter.normalize(context) -> NormalizationResult`.
- Produces: `POST /api/projects/{project_id}/sources/git/preview` and `/sources/git`.

- [ ] **Step 1: Write failing Git boundary tests**

```python
def test_git_import_is_limited_to_ref_range_and_paths(git_fixture_repo) -> None:
    command = GitSourceCommand(
        repository_root=git_fixture_repo.root,
        ref_name="refs/heads/pilot",
        start_commit=git_fixture_repo.first_sha,
        end_commit=git_fixture_repo.last_sha,
        include_paths=["analysis/**", "methods.md"],
    )
    result = GitAdapter().normalize(git_fixture_repo.context(command))
    paths = {part.metadata.get("path") for part in result.parts}
    assert "analysis/run.py" in paths
    assert "private/raw_subject.csv" not in paths
    assert {part.metadata["commit_sha"] for part in result.parts if part.kind == "commit"} == {
        git_fixture_repo.first_sha,
        git_fixture_repo.last_sha,
    }


def test_git_import_rejects_repository_escape(git_fixture_repo, tmp_path) -> None:
    command = git_fixture_repo.command(repository_root=tmp_path / "..")
    with pytest.raises(UnsafeSourcePath):
        GitAdapter().inventory(command)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/ingestion/test_git_adapter.py -q`

Expected: FAIL because the Git adapter and routes do not exist.

- [ ] **Step 3: Implement preview and immutable Git capture**

Resolve the repository and Git directory to absolute paths, require the repository root to equal the approved path, resolve the named ref to a commit, and verify the commit range is connected. Use Git object reads, never checkout, reset, clean, stash, or branch mutation. Inventory commit IDs, parents, author metadata, commit times, allowed paths, byte sizes, and excluded reasons.

Reject absolute include paths, parent traversal, symlinks escaping the repository, submodules, secret-like filenames, binary blobs, and configured size limits. The preview response reports the resolved head SHA and counts. Registration stores a deterministic JSON Git manifest as the source artifact so a later repository change cannot alter the ingested version.

- [ ] **Step 4: Verify repository integrity**

Run: `cd backend; uv run pytest tests/ingestion/test_git_adapter.py -q`

Expected: all tests pass and `git status --porcelain` for the synthetic fixture repository is byte-for-byte unchanged before and after import.

- [ ] **Step 5: Commit the Git adapter**

```bash
git add backend/uri_backend/ingestion/adapters/git.py backend/uri_backend/ingestion/adapters/__init__.py backend/uri_backend/sources backend/tests/ingestion/test_git_adapter.py
git commit -m "Add scoped Git ingestion"
```

### Task 8: Selected ChatGPT conversation staging

**Files:**
- Create: `backend/uri_backend/ingestion/adapters/conversations.py`
- Create: `backend/tests/fixtures/conversations/export.json`
- Create: `backend/tests/ingestion/test_conversation_adapter.py`
- Modify: `backend/uri_backend/sources/schemas.py`
- Modify: `backend/uri_backend/sources/router.py`
- Modify: `backend/uri_backend/ingestion/adapters/__init__.py`

**Interfaces:**
- Produces: `stage_conversation_export(stream, staging_root, ttl) -> StagedConversationInventory`.
- Produces: `promote_selected_conversations(stage_id, conversation_ids, actor, project) -> list[SourceVersion]`.
- Produces: preview, selection, and purge endpoints under `/api/projects/{project_id}/sources/conversations`.

- [ ] **Step 1: Write failing privacy-selection tests**

```python
async def test_only_selected_conversations_are_promoted(conversation_service, staged_export) -> None:
    inventory = await conversation_service.inventory(staged_export)
    promoted = await conversation_service.promote(inventory.stage_id, ["conv-clearermind"])
    assert [item.external_id for item in promoted] == ["conv-clearermind"]
    assert await conversation_service.find_source("conv-unrelated") is None
    assert not inventory.staging_path.exists()


async def test_expired_stage_cannot_be_promoted(conversation_service, expired_stage) -> None:
    with pytest.raises(StageExpired):
        await conversation_service.promote(expired_stage.id, ["conv-clearermind"])
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/ingestion/test_conversation_adapter.py -q`

Expected: FAIL because conversation staging does not exist.

- [ ] **Step 3: Implement inventory, selection, and purge**

Stream the export into an owner-only random staging directory. Parse only supported ChatGPT export shapes with bounded nesting, byte, conversation, and message limits. The inventory returns ID, title, created/updated times, and message count but no message bodies. Promotion creates one canonical JSON artifact per selected conversation, preserving message role, available author label, timestamp, message ID, parent ID, and ordinal.

Purge the whole staging directory after successful promotion, explicit cancellation, parse failure, or TTL expiry. Never store unselected bodies in PostgreSQL, logs, errors, quality previews, or artifact storage. Record selection IDs and a hash of the source export as an audit event without retaining the export.

- [ ] **Step 4: Verify privacy and malformed-export handling**

Run: `cd backend; uv run pytest tests/ingestion/test_conversation_adapter.py -q`

Expected: all tests pass for explicit selection, zero selection, expired staging, malformed JSON, oversized exports, branched conversations, missing timestamps, purge failure reporting, and absence of unselected marker text across PostgreSQL and artifact storage.

- [ ] **Step 5: Commit selected conversation ingestion**

```bash
git add backend/uri_backend/ingestion/adapters/conversations.py backend/uri_backend/ingestion/adapters/__init__.py backend/uri_backend/sources backend/tests/fixtures/conversations backend/tests/ingestion/test_conversation_adapter.py
git commit -m "Add selected conversation ingestion"
```

### Task 9: Notebook, run, manifest, and lab-record adapters

**Files:**
- Create: `backend/uri_backend/ingestion/adapters/notebooks.py`
- Create: `backend/uri_backend/ingestion/adapters/manifests.py`
- Create: `backend/uri_backend/ingestion/adapters/lab_notebooks.py`
- Create: `backend/tests/fixtures/notebooks/analysis.ipynb`
- Create: `backend/tests/fixtures/notebooks/run.json`
- Create: `backend/tests/fixtures/manifests/dataset.yaml`
- Create: `backend/tests/fixtures/manifests/references.bib`
- Create: `backend/tests/fixtures/lab_notebooks/entry.json`
- Create: `backend/tests/fixtures/lab_notebooks/protocol.html`
- Create: `backend/tests/ingestion/test_research_adapters.py`
- Modify: `backend/uri_backend/ingestion/adapters/__init__.py`

**Interfaces:**
- Produces: registered adapters for `notebook_run`, `reference_manifest`, and `lab_notebook` source families.
- Produces: stable cell, result-row, accession, citation-key, entry-section, and protocol-step locators.

- [ ] **Step 1: Write failing cross-format normalization tests**

```python
def test_notebook_preserves_cell_order_and_execution_metadata(fixtures) -> None:
    result = NotebookAdapter().normalize(fixtures.notebook("analysis.ipynb"))
    assert [part.locator["cell"] for part in result.parts] == [1, 2, 3]
    assert result.parts[1].metadata["execution_count"] == 1


def test_dataset_manifest_contains_reference_not_raw_rows(fixtures) -> None:
    result = ManifestAdapter().normalize(fixtures.manifest("dataset.yaml"))
    assert result.parts[0].metadata["accession"] == "synthetic-accession"
    assert all("participant_id" not in part.text for part in result.parts)


def test_protocol_steps_are_individually_addressable(fixtures) -> None:
    result = LabNotebookAdapter().normalize(fixtures.lab_record("protocol.html"))
    assert [part.locator["step"] for part in result.parts if part.kind == "protocol_step"] == [1, 2]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/ingestion/test_research_adapters.py -q`

Expected: FAIL because the three adapters do not exist.

- [ ] **Step 3: Implement format-specific, source-faithful parsing**

Use `nbformat` for IPYNB and retain cell type, source, execution count, selected textual outputs, and notebook metadata; skip rich binary payloads with warnings. Parse run JSON/CSV into parameters, environment, code revision, dataset references, metrics, and artifact references without assuming ML-specific field names.

Parse YAML/JSON manifests with a strict allowlist for accession, DOI, version, cohort summary, license, loader, checksum, restrictions, and local availability. Parse BibTeX/RIS as bibliographic references. Reject structures that resemble participant-row tables and report `participant_data_disallowed`.

Parse generic ELN JSON/CSV, Markdown, HTML, and PDF exports into entry metadata, ordered sections, observations, attachments, deviations, and protocol steps. Preserve signatures as reported metadata without asserting cryptographic validity.

- [ ] **Step 4: Verify all research adapters**

Run: `cd backend; uv run pytest tests/ingestion/test_research_adapters.py -q`

Expected: all tests pass for notebook ordering, stripped binary output, zero and negative metrics, manifest validation, DOI/BibTeX/RIS references, ELN sections, protocol steps, malformed files, and participant-data rejection.

- [ ] **Step 5: Commit remaining source adapters**

```bash
git add backend/uri_backend/ingestion/adapters backend/tests/fixtures/notebooks backend/tests/fixtures/manifests backend/tests/fixtures/lab_notebooks backend/tests/ingestion/test_research_adapters.py
git commit -m "Add research source adapters"
```

### Task 10: Source-quality preview and end-to-end ingestion slice

**Files:**
- Create: `backend/uri_backend/ingestion/quality.py`
- Create: `backend/tests/ingestion/test_source_quality.py`
- Create: `backend/tests/ingestion/test_ingestion_api.py`
- Create: `backend/scripts/seed_clearermind_pilot.py`
- Modify: `backend/uri_backend/ingestion/worker.py`
- Modify: `backend/uri_backend/sources/service.py`
- Modify: `backend/uri_backend/sources/router.py`
- Modify: `README.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Produces: `assess_source(context, normalization) -> SourceQualityReport` with seven independent dimensions.
- Produces: `SourceContext(family, has_author, has_source_time, has_native_version, has_reproducibility_links)` for deterministic quality signals.
- Produces: source preview and ingestion-run status responses used by the later frontend plan.
- Produces: safe, explicit ClearerMind pilot setup command that registers project metadata but imports no source until paths and selections are supplied.

- [ ] **Step 1: Write failing quality and end-to-end tests**

```python
class SourceContext(BaseModel):
    family: str
    has_author: bool = False
    has_source_time: bool = False
    has_native_version: bool = False
    has_reproducibility_links: bool = False


def test_quality_dimensions_are_separate() -> None:
    report = assess_source(
        SourceContext(family="conversation", has_author=False, has_source_time=True),
        NormalizationResult(
            adapter="conversations",
            adapter_version="1",
            status="normalized",
            parts=[NormalizedPart(
                ordinal=0,
                kind="message",
                text="A decision because evidence changed.",
                locator={"conversation_id": "c1", "message": 1},
            )],
            parse_coverage=1.0,
        ),
    )
    assert set(report.dimensions) == {
        "provenance",
        "temporal_fidelity",
        "decision_density",
        "reproducibility_support",
        "parse_completeness",
        "citation_addressability",
        "extraction_confidence",
    }
    assert report.dimensions["provenance"].level == "warning"
    assert report.overall_score is None


async def test_uploaded_markdown_reaches_normalized_terminal_state(client, pilot_owner, pilot_project) -> None:
    created = await client.post(
        f"/api/projects/{pilot_project.id}/sources/uploads",
        headers={"X-URI-User-ID": str(pilot_owner.id), "Idempotency-Key": "methods-v1"},
        files={"file": ("methods.md", b"# Method\n\nUse the reviewed pipeline.", "text/markdown")},
        data={"family": "document", "external_id": "methods.md", "native_version": "pilot-v1"},
    )
    assert created.status_code == 202
    await run_one_worker_job()
    status = await client.get(created.json()["status_url"], headers={"X-URI-User-ID": str(pilot_owner.id)})
    assert status.json()["status"] == "succeeded"
    assert status.json()["part_count"] == 2
    assert status.json()["quality"]["overall_score"] is None
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/ingestion/test_source_quality.py tests/ingestion/test_ingestion_api.py -q`

Expected: FAIL because quality assessment and completed API orchestration are missing.

- [ ] **Step 3: Implement the quality report and vertical slice**

Each quality dimension returns `level` (`strong`, `partial`, `warning`, or `unknown`), a concise explanation, and the exact signals used. Add privacy and licensing warnings beside, not inside, the quality dimensions. Never calculate or expose a single overall source score.

Complete worker dispatch so a registered version moves through `queued -> running -> succeeded`, persists normalized parts and quality assessment transactionally, and exposes progress plus errors through the source and ingestion-run APIs. The ClearerMind script creates only fictional/local project users, roles, and project metadata; it requires explicit `--repository`, `--ref`, `--start-commit`, `--end-commit`, and conversation selection inputs before registering evidence.

- [ ] **Step 4: Run backend and existing frontend verification**

Run: `cd backend; uv run pytest -q; uv run ruff check uri_backend tests scripts`

Run: `node --test tests/*.test.cjs; node build/build.js; git diff --check`

Expected: backend tests and all existing Node tests pass, the generated `index.html` rebuilds, and there are no whitespace errors. The untracked executive-summary PDF remains untouched and uncommitted.

- [ ] **Step 5: Perform a local API smoke test**

Run the development database, apply migrations, start `uv run uvicorn uri_backend.api:app --reload`, and start `uv run uri-worker`. Create a synthetic project, upload the synthetic Markdown fixture, and verify `/api/ready`, ingestion status, source version, content parts, and quality preview through HTTP. Do not point this smoke test at ClearerMind or a real ChatGPT export.

Expected: the source reaches `succeeded`, exact content locators are returned, and stopping/restarting the worker does not duplicate the version or parts.

- [ ] **Step 6: Commit the completed ingestion foundation**

```bash
git add backend/uri_backend/ingestion/quality.py backend/uri_backend/ingestion/worker.py backend/uri_backend/sources backend/tests/ingestion backend/scripts/seed_clearermind_pilot.py README.md docs/IMPLEMENTATION_STATUS.md index.html
git commit -m "Complete the ingestion foundation"
```

## Increment acceptance gate

Do not begin reviewed extraction or frontend replacement until all of the following are true:

- An empty PostgreSQL 16 database migrates to head with pgvector enabled.
- Project capability tests deny cross-project and unauthorized source access.
- Every source family produces immutable versions, addressable normalized parts, and a multidimensional quality report from synthetic fixtures.
- An entire ChatGPT export never leaves staging; only selected conversation artifacts persist.
- Git ingestion leaves the source repository unchanged and records the exact resolved commit range.
- Worker retry and idempotency tests pass against PostgreSQL.
- The backend suite, existing Node suite, production build, and `git diff --check` pass.
- A synthetic upload completes through the real API and worker after a restart.

The next plan begins from these interfaces and adds local-model extraction, cited draft review, atomic publication, hybrid GraphRAG retrieval, contribution/lifecycle services, and dashboard projections. The third plan replaces prototype-local frontend state with those APIs and completes the ClearerMind demonstration.
