# URI Implementation Status

## Backend ingestion foundation

The local PostgreSQL backend now has a queued normalization slice for synthetic
source artifacts. A worker moves a source version from queued to running to a
terminal state; successful transactions add immutable normalized parts and one
multidimensional quality assessment together. API status and content endpoints
remain project-capability scoped. The assessment has seven separate dimensions
and no overall score; privacy and licensing warnings remain distinct from those
dimensions. The ClearerMind helper is metadata-only and does not inspect or
import real repositories or conversation exports.

This is not a production deployment and does not claim that real ClearerMind,
ChatGPT, participant, or other private evidence has been imported.

Generic backend uploads are first written to a bounded owner-only quarantine
file, then validated by a fail-closed family/media adapter and privacy preflight
before content-addressed artifact publication. Conversation exports and Git use
their scoped intake routes rather than generic upload.

## Current increment

Implement the first connected workspace from `UX_BLUEPRINT.md`: Project Home, evidence intake, review, published record, and handoff/export. GPT-5.6 Sol workers own workspace components, evidence workflow, and CSS; the primary agent owns integration and verification.

The existing prototype remains accessible with `?legacy=1`. This increment uses fictional seed records and local browser persistence. It does not connect authentication, a cloud database, hosted processing, or AI extraction.

## Integration decisions

- Keep the generated, self-contained `index.html` deployment. Compile the additional JSX scripts in source order and inline workspace styles.
- Keep original records in the existing store; persist evidence and draft revisions separately. Publication uses stable entry identifiers to avoid duplicate additions.
- In the demo, PI/PhD identities can publish within assigned projects; students submit for review. This is a temporary capability mapping, not production authorization.
- Markdown/text uploads are the supported local preview. Unsupported PDF/DOCX and scanned material must produce a clear explanation instead of fabricated extraction.
- Partner search and deep links must not display unshared views. All data in this static prototype is still downloadable; real confidentiality requires the planned backend.

## Verification checklist

- [x] Baseline production build passes.
- [x] Capture the original desktop interface.
- [x] Partner-search regression tests pass.
- [x] Integrated production build passes.
- [x] Desktop and narrow-screen layouts inspected.
- [x] Manual draft survives refresh and navigation.
- [x] Markdown upload, citation review, and unsupported-file recovery checked.
- [x] Student submission and reviewer publication checked.
- [x] Published entry remains unique after refresh; idempotent mapping covered by tests.
- [x] Handoff/export and project scoping checked.
- [x] Legacy navigation, partner direct links, and malformed storage checked.
- [x] Production page loads from a local file with HTTP(S) requests blocked; no external requests observed.

Seventeen automated checks pass. Browser verification exercised direct publication,
student submission, adding material after submission (new revision required),
requesting changes, resubmission, approval of exactly the included entries,
and read-only source inspection after publication. The mobile review panes switch
correctly at 390px without horizontal document overflow. Markdown download succeeds.

Independent review identified revision mutation, duplicate-source visibility,
project selection, malformed storage, and mobile-pane issues. They were corrected
and checked with targeted tests/browser reproductions. A subsequent identity-switch
render error and an empty-project continuity error were also fixed and covered by regression tests.

Remaining work: real authentication and persistent services, AI extraction,
PDF/DOCX/OCR ingestion, production capability administration, and a pilot readiness
review. No deployment or GitHub write was performed.

## Scarlet and gray visual refresh

The workspace now uses Ohio State's scarlet (#BA0C2F) and gray (#A7B1B7), with
charcoal-gradient Home/project headers, a dark navigation sidebar, and decorative
research-node artwork. Navigation, evidence intake, and review workflows are retained.
Approved-record coverage and six-month activity graphics use actual accessible
records, exclude pending entries, and label their date window. Invalid dates do not
create activity. These are record counts, not research-quality or readiness scores.

The production build and all 17 tests pass. Desktop and 390px mobile previews were
inspected, with no horizontal document overflow or browser errors. Screenshots are
saved under `docs/screenshots/scarlet-*.png`. This is a local visual update, not a
deployment or backend release.

## Local verification commands

```sh
node build/build.js
node build/serve.js
node --test tests/*.test.cjs
```

Local preview: `http://127.0.0.1:4173`. Rebuild before refreshing the production preview.

## Structured research tracking increment

Project work now has a separate Research tab for team-entered tasks, experiments,
milestones, responsibility, and measurements. The Project Overview shows a compact
operational summary below the approved-record hero without treating record counts as
a research score. Current-state and next-action scientific explanations remain exact
and are available through details disclosures.

Tracking uses immutable project-scoped revisions in `uri.research.v1`. Every save and
export rereads storage first, stale edits fail instead of overwriting a newer revision,
and corrupt storage remains untouched while writes and exports are blocked. Measurement
values remain form strings until blank validation and explicit numeric conversion; zero
and negative values are supported. Raw scatter series group only exact metric, unit,
condition, and experiment matches. CSV contains current selected-project records and
JSON contains selected-project revision history, both labeled as team-entered rather
than reviewed findings.

The demo edit policy permits original authors, assigned owners of operational work,
and PI/PhD reviewers to update tasks, experiments, and milestones. Measurements remain
editable only by their original author or PI/PhD reviewers. This is a browser prototype
policy, not production authorization.

Targeted automated checks cover blank-versus-zero conversion, exact series grouping,
fresh-read stale rejection, failed durable writes, export scoping, inaccessible browser
storage, complete revision snapshots, exact source inspection, constant-series plots,
and assigned-owner editing. The final production build and all 45 regression tests
pass. Independent domain and UI reviews found no blocking issues. Desktop and 390px
mobile walkthroughs verified persistence, exports, permissions, revision history,
and recovery from stale edits or failed storage writes. The generated file opens
offline with HTTP(S) blocked, no external requests, and no page errors. Before/after
screenshots are in `docs/screenshots/research-*.png`; synthetic browser checks used
an isolated context without changing the user's stored records. No deployment or
GitHub write was performed.
