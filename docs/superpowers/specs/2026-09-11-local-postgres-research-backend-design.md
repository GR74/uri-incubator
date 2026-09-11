# Local PostgreSQL research intelligence backend

Date: 2026-09-11

Status: Approved conversational design, pending repository review

## Goal

Turn the URI browser prototype into a working local pilot whose dashboard is populated by evidence from a real research project. ClearerMind is the first pilot. The system ingests a deliberately selected Git history, selected ChatGPT conversations, and several complementary research-source formats; extracts cited candidate knowledge with a local language model; routes it through human review; and publishes an auditable project record and research graph.

The pilot starts on PostgreSQL rather than SQLite so persistence, migrations, constraints, search, and vector retrieval match the intended production direction. It remains local-first: PostgreSQL, processing workers, the model runtime, and artifact storage run on the researcher's computer. The architecture must allow later replacement of local artifact storage with S3-compatible storage and local processes with hosted services without changing the domain model.

## Product principles

1. Original evidence is immutable and content-addressed.
2. AI output is a cited draft, never an official fact by default.
3. Human approval is an explicit, atomic publication event.
4. The graph displays recorded, explainable relationships rather than decorative or similarity-only edges.
5. Source quality is multidimensional; file extension alone never determines trustworthiness.
6. Git activity is evidence of change, not automatic evidence of human scientific judgment or contribution.
7. Stashing freezes work without deleting its history or preventing an authorized continuation.
8. Sensitive participant data is not required for the pilot and must not be copied into URI.

## Scope

### Included in the pilot

- A Python FastAPI modular monolith.
- PostgreSQL 16 with the pgvector extension from the first migration.
- A separate background worker using the same application package and database.
- Local, content-addressed artifact storage behind a replaceable storage interface.
- Versioned ingestion for the six approved source families.
- Local-model extraction through a provider interface, initially backed by Ollama.
- Full-text, vector, metadata, and graph-assisted retrieval.
- Cited draft review and publication.
- Project memberships, capability checks, contribution events, and audit history.
- Dashboard projections that replace the prototype's seed records and browser-local stores.
- Reversible stash, resume, archive sharing, export, and linked continuation.

### Explicitly excluded

- Exo's identity manifold, cognition services, personality or behavioral inference, TRHN, and organization-per-schema tenancy.
- Automatic publication of model-generated claims or semantic relationships.
- Raw participant-level research data ingestion.
- Production OIDC, institutional single sign-on, billing, or cloud deployment.
- Live OAuth integrations for every external product during the pilot.
- Treating commit count, message volume, or generated text volume as scientific contribution quality.

## System architecture

The pilot is one deployable backend with explicit internal modules:

```text
URI React interface
        |
        v
FastAPI application
  - projects and membership
  - source registry and uploads
  - evidence drafts and review
  - published research record
  - graph and retrieval
  - dashboard projections
  - lifecycle, sharing, and handoff
        |
        +------ PostgreSQL 16 + pgvector
        |
        +------ local content-addressed artifact store
        |
        +------ durable job table <------ background worker
                                              |
                                              +-- parsers
                                              +-- embedding provider
                                              +-- local LLM provider
```

The worker claims durable jobs from PostgreSQL, records heartbeats and attempts, and commits each state transition. A separate message broker is unnecessary for the pilot. The job interface must be replaceable if production scale later warrants a dedicated queue.

Database changes use ordered migrations. Application configuration comes from environment variables with a checked-in example file containing no credentials. Structured logs include request, project, source, artifact, ingestion-run, and job identifiers without logging sensitive source text.

## Core data model

### Projects and access

- `users`: the local pilot's known researchers.
- `labs`: optional grouping and sharing boundary.
- `projects`: title, code, description, state, owner, and lifecycle version.
- `project_memberships`: project role and membership state.
- `membership_capabilities`: explicit grants or restrictions beyond the role default.

The local demo may keep its identity selector, but every API operation resolves it to a server-side user and enforces project access. UI visibility is never the authorization boundary.

### Sources and immutable evidence

- `sources`: logical external source, source family, project, owner, access classification, and external identifier.
- `source_versions`: source-native version, author/time metadata, acquisition time, parser version, checksum, and supersession link.
- `artifacts`: immutable content-addressed blobs with media type, size, checksum, storage key, and quarantine state.
- `content_parts`: ordered normalized units such as a document paragraph, conversation message, notebook cell, commit, diff hunk, protocol step, or result row.
- `source_quality_assessments`: separate quality dimensions, warnings, parse coverage, and assessor provenance.
- `ingestion_runs` and `ingestion_jobs`: durable orchestration, attempt history, status, and structured errors.

An artifact is identified by SHA-256. Re-uploading identical bytes reuses the artifact but may create another project-scoped source reference. A unique idempotency boundary combines project, source, source-native version, and checksum.

### Draft and published knowledge

- `draft_sets`: one reviewable change set produced manually or by an ingestion run.
- `draft_candidates`: typed candidate statement, structured payload, confidence, extraction version, and status.
- `candidate_citations`: exact references to one or more content parts, including offsets or source-native locations.
- `reviews`: requested reviewer, decision, comments, actor, and timestamp.
- `records`: stable published knowledge identity.
- `record_versions`: append-only approved versions and structured type-specific payloads.
- `record_citations`: the evidence supporting a published version.
- `relations`: typed, directed relationships between published records and other graph entities.
- `relation_citations`: evidence that justifies each published edge.
- `supersessions`: corrections or replacements that retain the earlier history.

Initial record types are decision, method, result, dead end, blocker, next step, claim, dataset, protocol, experiment, analysis run, artifact reference, and project event. Initial relations include proposes, accepts, rejects, explains, implements, tests, uses, produces, supports, challenges, summarizes, cites, defines, deviates from, assigned to, reviewed by, supersedes, belongs to, and continued from.

Publication validates that every candidate requiring evidence has at least one readable citation, that cited content belongs to the same authorized project, and that all referenced records exist. It then creates record versions, citations, relations, audit events, and projection invalidations in one database transaction.

### Audit, contribution, and lifecycle

- `audit_events`: append-only security and domain event trail.
- `contribution_events`: proposed, authored, corrected, reviewed, approved, implemented, or handed-off contributions tied to records and sources.
- `project_lifecycle_events`: created, stashed, shared, resumed, continued, or closed.
- `archive_exports`: immutable export manifests and the authorization context used to create them.
- `handoffs`: recipient, readiness state, acknowledged omissions, and accepted continuation.

Contribution summaries are derived from reviewed domain actions. Source-native authorship remains visible but is not promoted into role, permission, or credit without confirmation.

## Approved source families

### 1. Git

The pilot registers a trusted local repository or Git bundle, one named branch or ref, an explicit commit range, and optional path allowlists. It records repository identity, remote URL when available, ref name, start and end commit IDs, commits, authorship metadata, allowed file snapshots, and relevant diffs.

The importer reads the repository without changing its checkout. Secret-like files, large binaries, ignored research data, and paths outside the approved repository are excluded. Git can establish what changed and which code produced an analysis; it cannot independently establish why a scientific choice was made or who deserves intellectual credit.

### 2. Selected conversations

A user supplies a ChatGPT export or another supported conversation packet. The system first inventories titles, dates, and message counts in a temporary staging area. The user explicitly selects conversations for the project. Only selected conversations are promoted into immutable artifacts and normalized parts; unselected staged content is purged.

Each message retains role, author label where known, timestamp where available, conversation ID, and message position. Conversations are useful for proposals, corrections, rationale, and rejected approaches, but statements within them remain assertions until connected to stronger evidence or approved as decisions.

### 3. Research documents

The document adapter accepts Markdown, plain text, DOCX, and text-bearing PDF. It preserves headings, paragraphs, tables, comments or revisions when the format exposes them, page or paragraph locations, and document metadata. Scanned PDFs are reported as requiring OCR rather than producing fabricated empty extraction.

Typical pilot documents include methods, manuscript sections, decision notes, meeting notes, and reviewed redlines.

### 4. Computational notebooks and analysis runs

The adapter accepts Jupyter notebooks plus structured JSON or CSV run outputs. It retains cell order, cell type, source, selected outputs, execution metadata, parameters, environment information, code revision, dataset references, result artifacts, and tests when provided.

The normalized run model follows the useful separation between run metadata and output artifacts. A result should ideally connect to the code revision, parameters, dataset manifest, and generated file that produced it.

### 5. Dataset and research manifests

The adapter accepts JSON or YAML manifests containing public accession or DOI, dataset version, cohort summary, license, loader, checksums, local availability, and restrictions. It records references to controlled data without uploading raw participant rows, imaging, EEG, or identifiable files.

### 6. Lab notebook and protocol exports

The adapter accepts Markdown, HTML, JSON, CSV, or PDF exports representing electronic or conventional lab notebook entries and protocols. It preserves entry or protocol IDs, versions, timestamps, authors, ordered sections or steps, materials, observations, attachments, deviations, and signatures when present.

The pilot proves a generic export contract rather than implementing live Benchling or protocols.io OAuth. Live connectors can be added after the data model and review workflow are validated.

### Optional literature references

BibTeX, RIS, DOI lists, and Zotero JSON may be accepted through a reference-manifest extension. Literature references connect external papers to project claims and methods, but a citation does not by itself prove the project's result.

## Source guidance and quality UX

Before ingestion, the interface previews supported content, exclusions, privacy risks, and likely evidentiary value. It never labels a source simply good or bad. The assessment reports:

- provenance completeness;
- temporal and version fidelity;
- decision or rationale density;
- reproducibility support;
- content and parse completeness;
- citation addressability;
- privacy or licensing risk;
- extraction confidence.

Warnings remain attached to the source version and visible during candidate review. Low-scoring dimensions do not silently block ingestion unless they indicate a security, authorization, malware, or unsupported-format problem.

## Ingestion and analysis flow

```text
Select and scope source
  -> preview privacy, coverage, and quality warnings
  -> acquire bytes or Git objects
  -> hash and store immutable source version
  -> normalize into ordered content parts
  -> create embeddings and searchable text
  -> extract typed, cited candidate records and relationships
  -> run deterministic schema, citation, duplication, and conflict checks
  -> present one reviewable draft set
  -> edit, combine, exclude, submit, or request changes
  -> publish approved records and edges atomically
  -> refresh dashboard and graph projections
```

The extraction contract is structured JSON validated independently of the model. Each candidate contains its type, neutral statement, rationale when present, event time, named actors, confidence, uncertainty, and exact citations. The extractor may report that no useful candidate exists. It must not fill absent authors, dates, parameters, outcomes, or causal relationships.

Every run records model provider, model identifier, model digest when available, prompt version, schema version, parser version, sampling parameters, and timing. Changing any extraction component creates a new run rather than rewriting earlier output.

## Local AI and retrieval

The local model layer has two replaceable providers:

- an embedding provider that produces vectors stored in pgvector;
- a structured-generation provider, initially Ollama, for extraction and cited answer synthesis.

The exact model is selected through a small evaluation against frozen ClearerMind examples. The choice must satisfy structured-output reliability, citation fidelity, acceptable latency on the pilot machine, and license constraints. The architecture does not embed a model name into domain records.

Retrieval is hybrid:

1. PostgreSQL full-text search finds lexical matches.
2. pgvector finds semantically related content parts and approved records.
3. Metadata filters enforce project, source type, time, publication state, and permissions.
4. Graph traversal expands through cited, approved relationships with a bounded depth.
5. A reranking step assembles a compact evidence bundle.
6. The answer generator responds from that bundle and cites the exact supporting parts.

Draft or pending content is excluded by default. Authorized reviewers may explicitly include it, and answers then label it as unapproved. If the evidence bundle does not support an answer, the system says so and identifies missing context rather than improvising.

## Dashboard projection layer

Ingestion tables do not directly dictate the interface. A projection service returns stable, permission-filtered read models for the current dashboard:

| UI area | Backend projection |
| --- | --- |
| Home | Accessible active projects, recorded next steps, pending handoffs, review queue, and recent approved activity |
| Projects | Active and stashed project summaries plus lifecycle state |
| Overview | Project metadata, approved counts, latest result, next action, research activity, and continuity flags |
| Research | Team-entered or confirmed tasks, experiments, milestones, assignments, measurements, and run links |
| Record | Searchable published record versions, types, authors, dates, citations, and supersession state |
| Evidence | Sources, versions, artifacts, ingestion progress, quality warnings, draft sets, and citations |
| Reviews | Permission-filtered review queue and immutable decision history |
| Handoffs | Approved continuity packet, acknowledged omissions, contributors, files, and next steps |
| Map | Permission-filtered published nodes, cited edges, warnings, and deterministic layout inputs |
| Discover | Stashed projects explicitly shared with the lab and permitted continuation actions |
| People | Explicit project memberships, roles, capabilities, reviewed contribution events, and continuity dependencies |
| Settings | Project access, source policies, lifecycle actions, archive visibility, and export controls |

Most scientific dashboard content is derived from approved evidence. Roles, permissions, assignments, review decisions, sharing, and stash state come from explicit user actions rather than passive source inference.

The first frontend integration replaces the static project and people registries and both browser-local evidence/research stores with API clients. UI calculations that are purely presentational may remain in the browser, but counts used across screens must share one server-defined meaning.

## Roles and permissions

Initial role templates are:

- PI or owner: manage members and access, approve records, publish, stash, share, export, and transfer.
- Student lead: ingest sources, author and review drafts, maintain research tracking, and invite contributors when granted.
- Contributor: add authorized sources and propose records within assigned project areas.
- Reviewer: read cited evidence and approve, reject, or request changes.
- Guest: read only the explicitly shared archive or evidence bundle.

Capabilities are checked server-side for every project-scoped operation. Source text may have a stricter classification than a derived approved statement. An export includes only content readable by both the requester and the intended share policy, records omissions, and defaults to excluding drafts and restricted raw text.

## Project stashing and continuation

Stashing requires a reason and recommended next step. In one transaction it changes the project state to stashed, records the actor and time, freezes the published graph version, and disables automatic ingestion and project writes. It does not delete artifacts, sources, drafts, reviews, records, relations, contribution history, or audit events.

Authorized readers can search and export a stashed project. The owner can change archive visibility, resume the same project, or permit a continuation. Continue creates a new active project with an immutable `continued_from` relationship and an explicit import manifest; it never mutates the stashed source project.

## API surface

The initial API is grouped by product capability rather than database table:

- `/api/projects` and `/api/projects/{project_id}`
- `/api/projects/{project_id}/members`
- `/api/projects/{project_id}/sources`
- `/api/projects/{project_id}/ingestion-runs`
- `/api/projects/{project_id}/draft-sets`
- `/api/projects/{project_id}/record`
- `/api/projects/{project_id}/research`
- `/api/projects/{project_id}/dashboard`
- `/api/projects/{project_id}/graph`
- `/api/projects/{project_id}/contributions`
- `/api/reviews`
- `/api/projects/{project_id}/handoffs`
- `/api/projects/{project_id}/lifecycle`
- `/api/projects/{project_id}/exports`
- `/api/discover`
- `/api/health` and `/api/ready`

Commands accept idempotency keys where retries could otherwise duplicate state. Responses expose stable IDs, versions, and timestamps. Concurrent edits use version checks and return a conflict rather than overwriting newer work.

## Failure and recovery behavior

- One failed artifact creates a scoped failed job and does not roll back successful siblings.
- Retrying an artifact resumes from the last valid durable stage and cannot duplicate records.
- Unsupported or password-protected files remain registered with an actionable error.
- Malformed model output is retained as run diagnostics but creates no candidate records.
- Missing or invalid citations block publication.
- A lost worker lease becomes retryable after a bounded timeout.
- A database or artifact-store readiness failure prevents new ingestion and is visible in health status.
- Projection failure does not corrupt source, draft, or published data; projections can be rebuilt.
- Deleting a source reference does not delete shared artifact bytes or published history. Material deletion requires a separately authorized retention workflow and is outside this pilot.

## ClearerMind pilot story

1. Create the ClearerMind project and explicitly assign the PI/owner, student lead, reviewer, and contributors.
2. Register the approved Git branch and commit range without changing its working tree.
3. Upload a ChatGPT export, select only relevant conversations, and purge the remainder from staging.
4. Import the methods/manuscript documents, structured result files, analysis/run metadata, dataset manifest, and available notebook or protocol exports.
5. Show the source-quality and privacy preview before ingestion.
6. Run local parsing, embedding, and cited extraction.
7. Review a draft set containing decisions, method changes, rejected approaches, results, claims, blockers, and next steps.
8. Publish only confirmed items and display the populated Overview, Record, Evidence, Research, People, and contribution views.
9. Use the map and cited retrieval to answer why a method changed, which code and data produced a result, what supports a manuscript claim, and what another researcher needs to continue.
10. Stash the completed pilot, export its archive, share it with an authorized lab member, and demonstrate a linked continuation.

The demo must use real ClearerMind project materials that are safe and intentionally selected. It must not fabricate a wet-lab notebook, raw participant record, conversation, result, or attribution merely to fill a dashboard card. Empty or unavailable evidence should remain visibly honest.

## Verification strategy

### Automated tests

- PostgreSQL migrations apply from an empty database and upgrade through every committed revision.
- Repository, conversation, document, notebook/run, manifest, and lab-notebook/protocol adapters have representative fixtures.
- Identical artifacts and retried jobs remain idempotent.
- Parsers preserve stable source locations and report partial coverage.
- Extraction schemas reject missing citations, invented required fields, and invalid relation targets.
- Publication is atomic and append-only; corrections create superseding versions.
- Full-text, vector, metadata, and graph retrieval respect project and publication filters.
- Every API route enforces project capabilities independently of the UI.
- Restricted source text is absent from unauthorized search, graph detail, answer context, and exports.
- Dashboard projections match approved records and explicit workflow state.
- Stash makes the project read-only; resume and continuation preserve the full lifecycle.
- Worker lease expiry, retry, parser failure, malformed model output, and projection rebuild are covered.
- Existing static-workspace regression tests continue to pass throughout frontend migration.

### Pilot verification

- Build and run the complete local stack from documented commands on a clean machine with Docker or a locally installed PostgreSQL service.
- Restore a database backup and verify artifact checksum integrity.
- Compare extracted ClearerMind candidates against a frozen, manually reviewed expected set.
- Demonstrate that every published answer opens its supporting passage, commit, cell, or result file.
- Attempt cross-project, guest, stashed-project, and restricted-source writes and verify denial.
- Exercise desktop and narrow-screen flows for source selection, progress, review, dashboard, map, retrieval, contribution, handoff, stash, and continuation.
- Record supported formats, model/runtime requirements, latency, known omissions, and any source that could not be safely ingested.

## Success criteria

The pilot succeeds when a researcher can start from an empty local PostgreSQL database, ingest the approved ClearerMind source bundle, review and publish cited knowledge, navigate a genuinely populated current dashboard, retrieve evidence-backed answers, inspect contributions and graph provenance, and stash/share/continue the project without losing or silently rewriting its history.
