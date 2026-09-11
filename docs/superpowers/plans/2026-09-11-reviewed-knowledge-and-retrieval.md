# Reviewed Knowledge and Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert normalized research content into cited draft knowledge, route it through human review, publish an append-only research graph, and expose permission-filtered hybrid retrieval, contributions, lifecycle actions, handoffs, and dashboard projections.

**Architecture:** Extend the FastAPI modular monolith and PostgreSQL schema created by the ingestion plan. Deterministic validation surrounds replaceable local embedding and structured-generation providers; review and publication remain transactional, and all read models derive from immutable sources plus approved records and explicit workflow events. Ollama is optional at test time because provider contract tests use deterministic fakes, but a real local-model acceptance run is required before the pilot gate.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 16, pgvector, Ollama HTTP API, PostgreSQL full-text search, pytest, HTTPX

**Spec:** `docs/superpowers/specs/2026-09-11-local-postgres-research-backend-design.md`

## Global Constraints

- Complete `docs/superpowers/plans/2026-09-11-backend-foundation-and-ingestion.md` and its acceptance gate first.
- Use PostgreSQL 16 and pgvector; never add SQLite, FAISS, or an in-memory production persistence path.
- Every extracted candidate and every published evidence-bearing relation requires at least one exact content-part citation.
- AI output remains a draft until an authorized human publishes it.
- Draft and pending content is excluded from ordinary retrieval and dashboard projections.
- Store provider, model, prompt, schema, parser, and embedding versions for reproducibility.
- Treat graph edges as evidence-bearing domain assertions, not automatic semantic-similarity links.
- Keep source visibility stricter than or equal to derived-record visibility in search, answers, graph details, and exports.
- Publication, stash, resume, share, and continuation transitions are server-enforced and auditable.
- Every behavior-changing task follows red-green-refactor and ends in a focused commit.

---

## Planned file structure

```text
backend/uri_backend/
  knowledge/
    models.py                  Draft, citation, review, record, relation and supersession models
    schemas.py                 Extraction, review and publication contracts
    extraction.py              Structured candidate validation and extraction orchestration
    review.py                  Draft editing, submission and reviewer decisions
    publication.py             Atomic append-only publication
    router.py                  Draft, review and record routes
  retrieval/
    models.py                  Embedding metadata and vector columns
    providers.py               Embedding and structured-generation interfaces
    ollama.py                  Local Ollama HTTP implementation
    indexing.py                Versioned content and record embedding jobs
    hybrid.py                  Full-text/vector fusion and metadata filtering
    graph.py                   Evidence-backed graph projection and bounded expansion
    answers.py                 Cited evidence bundles and answer synthesis
    router.py                  Search, graph and answer routes
  operations/
    models.py                  Research work, contribution, lifecycle, handoff and export models
    schemas.py                 Command and projection contracts
    service.py                 Capability-checked lifecycle and operational commands
    projections.py             Dashboard, people, handoff and discover read models
    router.py                  Research, dashboard, lifecycle, contribution and handoff routes
backend/tests/
  knowledge/
  retrieval/
  operations/
```

### Task 1: Draft, citation, review, and published-record schema

**Files:**
- Create: `backend/uri_backend/knowledge/__init__.py`
- Create: `backend/uri_backend/knowledge/models.py`
- Create: `backend/uri_backend/knowledge/schemas.py`
- Create: `backend/migrations/versions/20260911_0005_knowledge_records.py`
- Create: `backend/tests/knowledge/test_knowledge_schema.py`
- Modify: `backend/migrations/env.py`

**Interfaces:**
- Produces: `DraftSet`, `DraftCandidate`, `CandidateCitation`, `Review`, `Record`, `RecordVersion`, `RecordCitation`, `Relation`, `RelationCitation`, and `Supersession` ORM models.
- Produces: `CandidateType`, `RelationType`, `DraftStatus`, and `ReviewDecision` enums.
- Produces: `CandidatePayload`, `CandidateCitationInput`, `ExtractedCandidate`, and `ExtractedRelation` Pydantic contracts.

- [ ] **Step 1: Write failing database-constraint tests**

```python
async def test_evidence_candidate_requires_a_citation(session, source_version) -> None:
    draft_set = DraftSet(
        project_id=source_version.source.project_id,
        author_id=source_version.created_by,
        status="draft",
        version=1,
    )
    session.add(draft_set)
    await session.flush()
    candidate = DraftCandidate(
        draft_set_id=draft_set.id,
        candidate_type="result",
        statement="The analysis produced a difference.",
        payload={},
        confidence=0.8,
    )
    session.add(candidate)
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_published_record_versions_are_append_only(session, published_record) -> None:
    published_record.version.statement = "rewritten"
    with pytest.raises(ImmutableRecordError):
        await session.commit()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/knowledge/test_knowledge_schema.py -q`

Expected: FAIL because the knowledge schema does not exist.

- [ ] **Step 3: Add append-only knowledge models and constraints**

Use these initial candidate types:

```python
class CandidateType(StrEnum):
    DECISION = "decision"
    METHOD = "method"
    RESULT = "result"
    DEAD_END = "dead_end"
    BLOCKER = "blocker"
    NEXT_STEP = "next_step"
    CLAIM = "claim"
    DATASET = "dataset"
    PROTOCOL = "protocol"
    EXPERIMENT = "experiment"
    ANALYSIS_RUN = "analysis_run"
    ARTIFACT_REFERENCE = "artifact_reference"
    PROJECT_EVENT = "project_event"
```

Draft candidates store neutral statement, structured payload, event time, named actors, confidence, uncertainty, extractor run, status, and version. Use deferred constraint triggers to ensure evidence-bearing candidates and relations have citations before a transaction commits. Reject `UPDATE` and `DELETE` on published record-version and citation tables through application events and PostgreSQL triggers; corrections create a new version and supersession row.

- [ ] **Step 4: Verify migration, citation constraints, and immutability**

Run: `cd backend; uv run pytest tests/knowledge/test_knowledge_schema.py tests/test_migrations.py -q`

Expected: all tests pass for missing citations, cross-project citations, invalid relation targets, append-only records, supersession, and downgrade/re-upgrade.

- [ ] **Step 5: Commit the knowledge schema**

```bash
git add backend/uri_backend/knowledge backend/migrations backend/tests/knowledge
git commit -m "Add cited knowledge records"
```

### Task 2: Replaceable model-provider contracts and Ollama adapter

**Files:**
- Create: `backend/uri_backend/retrieval/__init__.py`
- Create: `backend/uri_backend/retrieval/providers.py`
- Create: `backend/uri_backend/retrieval/ollama.py`
- Create: `backend/tests/retrieval/test_model_providers.py`
- Modify: `backend/uri_backend/config.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `EmbeddingProvider.embed(texts: Sequence[str]) -> list[list[float]]`.
- Produces: `StructuredGenerationProvider.generate(request: StructuredRequest[T]) -> T`.
- Produces: `OllamaProvider(base_url, generation_model, embedding_model, timeout)`.
- Produces: deterministic `FakeEmbeddingProvider` and `FakeStructuredProvider` test doubles under `backend/tests/fakes.py`.

- [ ] **Step 1: Write failing provider-contract tests**

```python
async def test_ollama_structured_generation_sends_json_schema(httpx_mock) -> None:
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/chat",
        json={"message": {"content": '{"items": []}'}, "done": True},
    )
    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        generation_model="pilot-model",
        embedding_model="pilot-embed",
        timeout=30,
    )
    result = await provider.generate(StructuredRequest(schema=CandidateBatch, messages=[]))
    assert result == CandidateBatch(items=[])
    request = httpx_mock.get_request()
    assert json.loads(request.content)["format"] == CandidateBatch.model_json_schema()


async def test_embedding_dimension_mismatch_is_rejected(fake_embeddings) -> None:
    fake_embeddings.responses = [[0.0, 1.0], [1.0]]
    with pytest.raises(EmbeddingDimensionError):
        await fake_embeddings.embed(["a", "b"])
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/retrieval/test_model_providers.py -q`

Expected: FAIL because provider contracts do not exist.

- [ ] **Step 3: Implement bounded local-provider calls**

Send Ollama structured requests with the exact Pydantic JSON schema, `stream: false`, configured model, deterministic temperature, and bounded timeout. Parse the returned JSON through the target Pydantic model. Record response metadata without source text. Map connection failure, timeout, invalid JSON, schema failure, and dimension mismatch to stable retryable or terminal errors.

Settings require explicit model identifiers and expected embedding dimension when local AI is enabled. Startup does not fail when Ollama is disabled; AI routes and jobs return `provider_unavailable` until configured.

- [ ] **Step 4: Verify provider contracts without a live model**

Run: `cd backend; uv run pytest tests/retrieval/test_model_providers.py -q`

Expected: all tests pass for schema requests, timeouts, invalid responses, disabled provider, batch ordering, and embedding dimensions.

- [ ] **Step 5: Commit model providers**

```bash
git add backend/uri_backend/retrieval backend/tests/retrieval/test_model_providers.py backend/tests/fakes.py backend/uri_backend/config.py backend/pyproject.toml backend/uv.lock
git commit -m "Add local model provider contracts"
```

### Task 3: Cited candidate extraction pipeline

**Files:**
- Create: `backend/uri_backend/knowledge/extraction.py`
- Create: `backend/tests/knowledge/test_extraction.py`
- Create: `backend/tests/fixtures/extraction/clearermind_synthetic_parts.json`
- Modify: `backend/uri_backend/ingestion/worker.py`
- Modify: `backend/uri_backend/ingestion/models.py`
- Create: `backend/migrations/versions/20260911_0006_extraction_runs.py`

**Interfaces:**
- Produces: `extract_candidates(session, source_version_id, provider, extraction_config) -> DraftSet`.
- Produces: `ExtractionRun` storing model, model digest, prompt, schema, parser, and sampling versions.
- Consumes: normalized `ContentPart` records from the ingestion plan and `StructuredGenerationProvider` from Task 2.

- [ ] **Step 1: Write failing citation-fidelity tests**

```python
async def test_extraction_discards_unknown_citation_locators(seed_parts, fake_structured) -> None:
    fake_structured.result = CandidateBatch(items=[ExtractedCandidate(
        candidate_type="decision",
        statement="Use the revised method.",
        citations=[CandidateCitationInput(part_id=uuid4(), quote="Use the revised method")],
        confidence=0.9,
    )])
    draft = await extract_candidates(seed_parts.session, seed_parts.source_version_id, fake_structured, TEST_CONFIG)
    assert draft.candidates == []
    assert draft.validation_warnings[0].code == "unknown_citation_part"


async def test_extraction_accepts_exact_quote_from_known_part(seed_parts, fake_structured) -> None:
    part = seed_parts.parts[0]
    fake_structured.result = CandidateBatch(items=[ExtractedCandidate(
        candidate_type="decision",
        statement="Use the revised method.",
        citations=[CandidateCitationInput(part_id=part.id, quote="Use the revised method")],
        confidence=0.9,
    )])
    draft = await extract_candidates(seed_parts.session, seed_parts.source_version_id, fake_structured, TEST_CONFIG)
    assert len(draft.candidates) == 1
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/knowledge/test_extraction.py -q`

Expected: FAIL because extraction orchestration does not exist.

- [ ] **Step 3: Implement chunked, cited extraction and deterministic validation**

Build bounded content windows that preserve part IDs and locators. Ask the model for candidate statements, event times, actors, uncertainty, exact part IDs and short supporting quotes. Validate that each part belongs to the source version, each quote occurs in normalized text after whitespace normalization, record types and relations are allowed, dates are source-supported, relation endpoints exist in the batch or database, and confidence is between zero and one.

Deduplicate only byte-identical normalized statements with the same type and citations. Similar but conflicting claims remain separate and receive a conflict hint. Persist valid candidates and warnings in one transaction, then enqueue extraction for the next source version without publishing anything.

- [ ] **Step 4: Verify extraction behavior**

Run: `cd backend; uv run pytest tests/knowledge/test_extraction.py -q`

Expected: all tests pass for exact citations, unknown parts, absent dates, duplicate windows, conflicting candidates, empty extraction, malformed provider output, retry metadata, and no publication side effects.

- [ ] **Step 5: Commit cited extraction**

```bash
git add backend/uri_backend/knowledge/extraction.py backend/uri_backend/ingestion backend/migrations backend/tests/knowledge backend/tests/fixtures/extraction
git commit -m "Extract cited research drafts"
```

### Task 4: Review and atomic publication workflow

**Files:**
- Create: `backend/uri_backend/knowledge/review.py`
- Create: `backend/uri_backend/knowledge/publication.py`
- Create: `backend/uri_backend/knowledge/router.py`
- Create: `backend/tests/knowledge/test_review_publication.py`
- Modify: `backend/uri_backend/api.py`

**Interfaces:**
- Produces: draft-set list/detail/edit, submission, request-changes, approve-and-publish, and record routes.
- Produces: `publish_draft_set(session, actor, draft_set_id, expected_version) -> PublicationResult`.
- Consumes: `AUTHOR_DRAFT`, `REVIEW_DRAFT`, and `PUBLISH_RECORD` capabilities.

- [ ] **Step 1: Write failing review and atomicity tests**

```python
async def test_student_submission_does_not_publish(client, student_headers, draft_set) -> None:
    response = await client.post(
        f"/api/projects/{draft_set.project_id}/draft-sets/{draft_set.id}/submit",
        headers=student_headers,
        json={"expected_version": draft_set.version},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending_review"
    assert await count_published_records(draft_set.project_id) == 0


async def test_publication_rolls_back_when_one_relation_is_invalid(publication_service, invalid_draft) -> None:
    with pytest.raises(InvalidRelationTarget):
        await publication_service.publish(invalid_draft.id, invalid_draft.version)
    assert await count_published_records(invalid_draft.project_id) == 0
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/knowledge/test_review_publication.py -q`

Expected: FAIL because review and publication services do not exist.

- [ ] **Step 3: Implement versioned review commands and publication transaction**

Authors may edit, combine, include, or exclude candidates while a set is draft or changes-requested. Any edit increments the set version and invalidates an earlier submission. Reviewers can request changes with a nonblank comment. Approve-and-publish requires reviewer and publisher capabilities, revalidates every citation and relation under the current transaction, creates record versions and cited relations, writes contribution and audit events, marks the draft set published, and emits one projection invalidation.

Use `expected_version` on every mutation. A stale request returns HTTP 409 with the current version and makes no change. Repeating a successful publish with the same idempotency key returns the original publication result.

- [ ] **Step 4: Verify the complete review state machine**

Run: `cd backend; uv run pytest tests/knowledge/test_review_publication.py -q`

Expected: all tests pass for author edits, student submission, reviewer visibility, requested changes, resubmission, stale edits, atomic publish, idempotent publish, citation visibility, and stashed-project rejection.

- [ ] **Step 5: Commit review and publication**

```bash
git add backend/uri_backend/knowledge backend/tests/knowledge/test_review_publication.py backend/uri_backend/api.py
git commit -m "Add reviewed record publication"
```

### Task 5: Versioned embeddings and hybrid retrieval

**Files:**
- Create: `backend/uri_backend/retrieval/models.py`
- Create: `backend/uri_backend/retrieval/indexing.py`
- Create: `backend/uri_backend/retrieval/hybrid.py`
- Create: `backend/migrations/versions/20260911_0007_retrieval_index.py`
- Create: `backend/tests/retrieval/test_hybrid_retrieval.py`
- Modify: `backend/uri_backend/ingestion/worker.py`
- Modify: `backend/migrations/env.py`

**Interfaces:**
- Produces: `index_content_parts` and `index_record_versions` with provider/model/dimension versioning.
- Produces: `hybrid_search(session, actor, SearchQuery) -> list[SearchHit]`.
- Produces: weighted reciprocal-rank fusion over PostgreSQL full-text and pgvector ranks.

- [ ] **Step 1: Write failing publication and permission filters**

```python
async def test_default_search_excludes_pending_and_other_projects(search_service, actor, fixtures) -> None:
    hits = await search_service.search(actor, SearchQuery(project_id=fixtures.allowed_project, text="revised method"))
    ids = {hit.entity_id for hit in hits}
    assert fixtures.published_record in ids
    assert fixtures.pending_candidate not in ids
    assert fixtures.other_project_record not in ids


async def test_restricted_source_text_is_not_returned_to_guest(search_service, guest, fixtures) -> None:
    hits = await search_service.search(guest, SearchQuery(project_id=fixtures.project_id, text="restricted phrase"))
    assert all(hit.source_visibility != "restricted" for hit in hits)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/retrieval/test_hybrid_retrieval.py -q`

Expected: FAIL because the retrieval index and service do not exist.

- [ ] **Step 3: Implement versioned indexing and rank fusion**

Store one embedding row per indexed content part or record version with model identifier, model digest, dimension, content checksum, and created time. Use a generated PostgreSQL `tsvector` column and GIN index for lexical retrieval plus an HNSW pgvector index after the dimension is fixed by migration configuration.

Filter authorization, project, publication state, source family, and time before ranking. Fuse lexical and vector ranks with deterministic reciprocal-rank fusion:

```python
def reciprocal_rank_fusion(rank_lists: list[list[UUID]], k: int = 60) -> dict[UUID, float]:
    scores: dict[UUID, float] = defaultdict(float)
    for rank_list in rank_lists:
        for rank, entity_id in enumerate(rank_list, start=1):
            scores[entity_id] += 1.0 / (k + rank)
    return scores
```

Return exact locators, publication status, visibility, and score components. Never infer a graph relation from vector proximity.

- [ ] **Step 4: Verify deterministic retrieval**

Run: `cd backend; uv run pytest tests/retrieval/test_hybrid_retrieval.py -q`

Expected: all tests pass for lexical-only, vector-only, fused ordering, model-version replacement, access filtering, published defaults, reviewer opt-in to pending content, and stable ties.

- [ ] **Step 5: Commit hybrid retrieval**

```bash
git add backend/uri_backend/retrieval backend/uri_backend/ingestion/worker.py backend/migrations backend/tests/retrieval
git commit -m "Add hybrid research retrieval"
```

### Task 6: Evidence-backed graph and cited answers

**Files:**
- Create: `backend/uri_backend/retrieval/graph.py`
- Create: `backend/uri_backend/retrieval/answers.py`
- Create: `backend/uri_backend/retrieval/router.py`
- Create: `backend/tests/retrieval/test_graph_answers.py`
- Modify: `backend/uri_backend/api.py`

**Interfaces:**
- Produces: `build_graph(session, actor, GraphQuery) -> GraphProjection`.
- Produces: `build_evidence_bundle(session, actor, AnswerQuery) -> EvidenceBundle`.
- Produces: `answer_question(session, actor, query, provider) -> CitedAnswer`.
- Produces: `/api/projects/{project_id}/graph`, `/search`, and `/answers` routes.

- [ ] **Step 1: Write failing graph and refusal tests**

```python
async def test_graph_contains_only_cited_published_edges(graph_service, actor, fixtures) -> None:
    graph = await graph_service.build(actor, GraphQuery(project_id=fixtures.project_id))
    edge_ids = {edge.id for edge in graph.edges}
    assert fixtures.cited_relation in edge_ids
    assert fixtures.uncited_relation not in edge_ids
    assert fixtures.pending_relation not in edge_ids


async def test_answer_refuses_when_bundle_has_no_support(answer_service, actor, project_id) -> None:
    answer = await answer_service.answer(actor, AnswerQuery(project_id=project_id, question="What proves the claim?"))
    assert answer.status == "insufficient_evidence"
    assert answer.text == "The approved project record does not contain enough evidence to answer this question."
    assert answer.citations == []
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/retrieval/test_graph_answers.py -q`

Expected: FAIL because graph projection and answers do not exist.

- [ ] **Step 3: Implement bounded graph expansion and citation verification**

Build nodes for projects, published records, explicit sources, artifacts, research items, and confirmed people. Include an edge only when its relation row is published, accessible, and backed by at least one readable citation. Expand from hybrid search hits through approved relations to a maximum configured depth and node count; record skipped inaccessible or unresolved connections as warnings.

The answer prompt receives numbered evidence items containing record ID, source-version ID, part ID, locator, and text. The model returns answer sentences with evidence numbers. Reject any number absent from the bundle. If all sentences lose support, return the fixed insufficient-evidence response. Store question and citation identifiers in audit logs but do not persist generated answers by default.

- [ ] **Step 4: Verify graph and answers**

Run: `cd backend; uv run pytest tests/retrieval/test_graph_answers.py -q`

Expected: all tests pass for cited edges, bounded cycles, inaccessible nodes, pending opt-in, invalid model citations, contradictions, insufficient evidence, and exact source locators.

- [ ] **Step 5: Commit graph retrieval and answers**

```bash
git add backend/uri_backend/retrieval backend/tests/retrieval/test_graph_answers.py backend/uri_backend/api.py
git commit -m "Add cited graph retrieval"
```

### Task 7: Operations, contributions, lifecycle, and dashboard projections

**Files:**
- Create: `backend/uri_backend/operations/__init__.py`
- Create: `backend/uri_backend/operations/models.py`
- Create: `backend/uri_backend/operations/schemas.py`
- Create: `backend/uri_backend/operations/service.py`
- Create: `backend/uri_backend/operations/projections.py`
- Create: `backend/uri_backend/operations/router.py`
- Create: `backend/migrations/versions/20260911_0008_operations_and_lifecycle.py`
- Create: `backend/tests/operations/test_operations.py`
- Create: `backend/tests/operations/test_lifecycle.py`
- Create: `backend/tests/operations/test_dashboard_projections.py`
- Create: `docs/pilot/local-model-evaluation.md`
- Modify: `backend/uri_backend/api.py`
- Modify: `backend/migrations/env.py`
- Modify: `README.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Produces: project-scoped research work, measurement, contribution, lifecycle, handoff, archive-export, dashboard, people, and discover routes.
- Produces: `stash_project`, `resume_project`, `share_archive`, and `continue_project` transactional commands.
- Produces: `get_project_dashboard`, `get_project_people`, `get_handoff_projection`, and `get_discover_projection` read models.

- [ ] **Step 1: Write failing projection and lifecycle tests**

```python
async def test_dashboard_uses_approved_records_and_explicit_work(projections, fixtures) -> None:
    dashboard = await projections.project_dashboard(fixtures.owner, fixtures.project_id)
    assert dashboard.approved_entries == 3
    assert dashboard.recorded_next_steps == 1
    assert dashboard.pending_candidate_count == 0
    assert dashboard.research.in_progress == 1
    assert dashboard.research.measurements == 2


async def test_stash_is_read_only_but_reversible(lifecycle, fixtures) -> None:
    stashed = await lifecycle.stash(
        fixtures.owner,
        fixtures.project_id,
        StashCommand(reason="Analysis complete", next_step="Independent replication", visibility="private"),
    )
    assert stashed.status == "stashed"
    with pytest.raises(ProjectReadOnly):
        await fixtures.sources.register_after_stash()
    resumed = await lifecycle.resume(fixtures.owner, fixtures.project_id, expected_version=stashed.version)
    assert resumed.status == "active"
    assert [event.action for event in resumed.lifecycle] == ["stashed", "resumed"]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend; uv run pytest tests/operations -q`

Expected: FAIL because operational models and projections do not exist.

- [ ] **Step 3: Implement explicit operations and derived projections**

Research work types are task, experiment, milestone, and measurement. Tasks and assignments come from user commands or confirmed draft candidates; model suggestions are never silently assigned or completed. Measurement grouping requires exact metric, unit, condition, and experiment identity.

Contribution events use `proposed`, `authored`, `corrected`, `reviewed`, `approved`, `implemented`, and `handed_off`, each linked to the domain object and actor. Dashboard counts use published records and current operational revisions. People projections use explicit memberships and capability labels, while source-native authorship appears separately as unconfirmed attribution when unmatched.

Stash requires nonblank reason and next step, freezes the current graph version, stops automatic ingestion, and makes domain writes fail before mutation. Resume records a new lifecycle event without deleting stash metadata. Share changes only archive visibility. Continue creates a distinct active project and immutable `continued_from` relation while leaving the source stashed.

- [ ] **Step 4: Verify every current dashboard projection and access boundary**

Run: `cd backend; uv run pytest tests/operations tests/knowledge tests/retrieval -q`

Expected: all tests pass for Home, Projects, Overview, Research, Record, Evidence, Reviews, Handoffs, Map, Discover, People, Settings, contribution events, source-versus-record visibility, stash, resume, share, export manifests, and continuation.

- [ ] **Step 5: Run the full backend acceptance suite**

Run: `cd backend; uv run pytest -q; uv run ruff check uri_backend tests scripts; uv run alembic upgrade head`

Run a configured Ollama model against the frozen synthetic extraction and answer fixtures. Record model identifier, digest, structured-output success rate, citation-validity rate, median latency, and failures in `docs/pilot/local-model-evaluation.md`; do not include source text in the report.

Expected: all deterministic tests pass. The selected model produces schema-valid responses and valid citations for every frozen acceptance case; otherwise it is not approved for the pilot configuration.

- [ ] **Step 6: Commit the working knowledge backend**

```bash
git add backend/uri_backend/operations backend/migrations backend/tests/operations README.md docs/IMPLEMENTATION_STATUS.md docs/pilot/local-model-evaluation.md
git commit -m "Complete the reviewed knowledge backend"
```

## Increment acceptance gate

- Normalized content produces cited candidates without publishing them.
- Student submission, reviewer changes, and atomic publication work through the API.
- Published records and relations are append-only and evidence-backed.
- Full-text, vector, metadata, and graph retrieval return only authorized content.
- Unsupported questions produce an explicit insufficient-evidence response.
- Dashboard projections cover every destination in the current UI.
- Contribution summaries use reviewed actions rather than volume metrics.
- Stash, resume, share, export, and continuation preserve history and permissions.
- Deterministic tests pass without Ollama; the configured real local model passes the frozen acceptance set before pilot use.
