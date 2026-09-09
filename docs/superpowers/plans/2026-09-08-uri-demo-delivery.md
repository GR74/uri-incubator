# URI Demo Delivery Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox syntax for tracking.

**Goal:** Deliver the approved evidence-to-handoff journey for the presentation in two weeks, with a separately verified readiness gate for participating labs.

**Architecture:** Start with the existing static React prototype for screen validation. Isolate evidence, draft review, publication, and export state behind explicit interfaces before connecting persistent services. Treat the current bundle as fictional demonstration data because client-side visibility controls do not provide confidentiality.

**Tech Stack:** Existing React, Tailwind, vendored Babel, and Node build for the first screen iteration. Backend selection is a separate engineering deliverable in Task 2, informed by approved hosting and data requirements.

**Spec:** `docs/UX_BLUEPRINT.md` and `docs/PRODUCT_FLOW.md`.

## Global Constraints

- AI output is always a cited draft; it never silently changes the official record.
- Search, exports, and direct URLs enforce the same permissions as visible pages.
- Student ownership after lab attachment remains provisional.
- Preserve user changes and the existing source/generated-output build contract.
- Use fictional evidence for presentation rehearsal; label prepared extraction honestly.
- Keep GitHub writes subject to the repository account policy and explicit publishing scope.

## Task 1: Make the screens reviewable (days 1–2)

**Files:** Modify `src/uri.html`; regenerate `index.html`; refine `docs/UX_BLUEPRINT.md` against implementation.

**Interfaces:** The shell consumes the current user and accessible project selection. The six screens share a project identifier and a selected evidence/change-set identifier; switching screens must preserve draft state.

- [x] Build the compact shell and Project Home with one primary action, current state, concrete next action, and explainable gaps.
- [x] Build Add Evidence, Progress, Review, Published, and Start Here using clearly marked sample states.
- [x] Reuse project records and loss simulation; move oversized introductions out of the working path.
- [x] Check empty project, unreadable source, partial extraction, changes requested, and no-publish-permission states visually.
- [x] Run `node build/build.js`. Exercise all six screens at desktop and narrow widths, using keyboard navigation; capture before/after screenshots.

Deliverable: a connected UX prototype with no requirement for another product questionnaire.

## Task 2: Resolve the persistent service design (days 2–3)

**Files:** Create `docs/BACKEND_ARCHITECTURE.md` and `docs/DATA_MODEL.md`.

**Interfaces:** Specify project membership/capabilities, source and source-version records, extraction jobs, cited draft revisions, review decisions, official entries, supersession links, and export snapshots. Every project-scoped operation receives authenticated identity and project scope.

- [ ] Verify current official documentation for candidate managed authentication, relational database, object storage, and background-job services.
- [ ] Choose one coherent deployment approach, documenting local development, environment configuration, failure recovery, and expected usage limits. Escalate only account ownership, spending, or institutional requirements that block the choice.
- [ ] Specify atomic publication: authorize the actor, validate reviewed revision, insert official entries and audit events, mark revision published, then commit together. Retrying the same publication must not duplicate entries.
- [ ] Specify source page/section citations, duplicate detection, and versioned extraction output. Document the gap between a generated AI packet and a complete original conversation; missing history cannot be reconstructed reliably.
- [ ] Define the access matrix and regression cases for direct URLs, global search, files, membership removal, review delegation, and export.

Deliverable: a buildable backend specification with identified deployment dependencies, not a claim that services already exist.

## Task 3: Complete one persistent vertical slice (days 4–6)

**Files:** Use the exact application, migration, and service paths established by Task 2. Record those paths in its architecture document before implementation.

**Interfaces:** Authenticated project creation, member lookup, manual evidence creation, source retrieval, draft save/load, and publication return persisted identifiers and explicit success/failure states.

- [ ] Implement sign-in, private project creation, membership authorization, and durable manual updates.
- [ ] Connect the same six screens to the persistent slice; preserve saved work on refresh and sign-in changes.
- [ ] Verify a project member succeeds and an unrelated account fails for each record/file endpoint, including direct requests.
- [ ] Verify removal of a member revokes subsequent access and that cross-project identifiers cannot bypass checks.

Deliverable: one working workflow backed by accounts and durable data. Hosting activation requires the necessary account access; continue local integration if it is unavailable.

## Task 4: Connect ingestion and review (days 7–9)

**Files:** Extend the ingestion, source storage, and review modules named in the backend architecture; add fixtures under `tests/fixtures/ingestion/`.

**Interfaces:** An upload produces a source record and processing job. Processing produces cited draft revisions. Approval refers to a specific immutable revision; publication uses Task 2's transaction boundary.

- [ ] Support Markdown packets, text transcripts, text-bearing PDFs, and DOCX. Detect scanned/unreadable material and expose a clear unsupported or OCR-processing state based on implemented capability.
- [ ] Preserve originals; reject unsupported content explicitly. Retry failed jobs without creating duplicate official entries.
- [ ] Connect extraction to cited drafts, with explicit unsupported-claim and contradictory-source cases.
- [ ] Implement request review, changes requested, revision resubmission, delegated approval, and direct publication according to capability.
- [ ] Test an edited submission cannot inherit approval from an earlier revision, and a repeated publish request produces one official update.

Deliverable: real extraction and human review for the supported formats, with visible recovery paths.

## Task 5: Complete continuity and handoff (days 10–11)

**Files:** Extend the continuity, handoff, and export modules established by the architecture; update the presentation fixture and walkthrough.

**Interfaces:** Continuity consumes authorized official entries and declared readiness evidence. Handoff and export consume an authorized versioned snapshot with source references.

- [ ] Generate an evidence-linked Start Here brief with current state, historical decisions, uncertainty, and missing-context interview questions.
- [ ] Connect the loss simulation to explicit assumptions. Show a before/after change only where approved evidence resolves a named gap.
- [ ] Implement full authorized history export, supersession links, omission notes, and ordered parts for large projects.
- [ ] Verify inaccessible material is absent from brief text, citations, search, exports, and downloaded files.

Deliverable: a new researcher can inspect the record and take its context into another AI.

## Task 6: Rehearse and stabilize (days 12–14)

**Files:** Create `docs/DEMO_RUNBOOK.md` and `docs/PILOT_READINESS.md`; update application fixes and generated assets as required by the selected build.

- [ ] Rehearse one fictional project from missing method context through upload, cited review, approval, resolved documentation gap, handoff, and export.
- [ ] Confirm realistic error recovery, keyboard operation, readable metadata, narrow layouts, refresh persistence, and consistent back navigation.
- [ ] Run the access regression suite, publication/revision checks, and a backup-restore exercise before designating the service ready for lab data.
- [ ] Prepare an honestly labeled offline sample demonstration if hosted processing is unavailable. Preserve the live path separately.
- [ ] Freeze new features for final rehearsals. Record actual supported formats and remaining pilot limitations.

Deliverable: a rehearsed presentation plus an evidence-based pilot readiness decision.

## Scope control

Preserve The Shelf, researcher records, and the graph as supporting views. Defer new graph interactions, Drive synchronization, browser capture, live audio transcription, and automated partner publication until after the central journey is dependable. Retain private-to-lab attachment in the model; validate ownership and institutional governance in interviews before relying on it for real lab onboarding.

If the schedule slips, simplify secondary views and integrations first. Keep source provenance, review integrity, and authorization in the central slice. This schedule is a target and depends on deployment access and the observed effort of integration.
