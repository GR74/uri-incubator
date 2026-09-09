# URI UX Blueprint

Status: working design based on the approved product flow. Routine design choices are delegated; student ownership after lab attachment remains provisional pending interviews. This specifies proposed behavior, not functionality already implemented.

## Design objective

A researcher should understand where a project stands, record work with little effort, and leave enough evidence for someone else to continue it. A returning or incoming student should be able to distinguish established findings, unresolved questions, and suggestions.

The presentation follows one fictional project through a documented handoff gap, new evidence, reviewed knowledge, and a useful starting brief. Every screen should answer: what happened, what supports it, and what can I do next?

## Visual direction

Retain the research-journal character through project titles and readable records. The user approved the new UX and requested a richer visual treatment inspired by the original prototype: scarlet and gray, charcoal gradients, and informative research graphics. Use a compact working interface with generous reading space inside documents. Keep information left aligned; reserve boxed surfaces for actionable groups and source previews.

- Palette: Ohio State scarlet `#BA0C2F`, gray `#A7B1B7`, white `#FFFFFF`, with charcoal and light neutral supporting surfaces. Values follow [Buckeye UX primary colors](https://bux.osu.edu/color/primary-colors/). This color treatment does not add university marks or claim institutional endorsement. Status must also have a text label and icon.
- Type: retain the existing serif family for project titles; use the existing sans family for navigation and reading controls. Body text 16px, metadata 14px, section headings 20px, project title 32px. Reserve monospace for literal file identifiers.
- Layout: 224px desktop sidebar, compact header, flexible main content. Review uses approximately 45% source and 55% draft. Below 900px, use a menu and a Source/Draft switch; preserve review position between views.
- Interaction: visible focus, 44px touch targets, clear selected state, reduced motion, no essential information revealed only on hover. Validate actual color combinations during implementation.
- Distinctive moment: the loss simulation names the procedures, decisions, and dependencies affected by a departure. Its explanation is the focal point; surrounding navigation stays quiet.
- Visual summaries: compact dark-gradient headers, labeled record-type counts, and activity bars derived from approved entries. Show the time window explicitly; do not turn documentation volume into a scientific-quality or readiness score. Keep the next action readily accessible.

## Navigation

Keep the agreed destinations: Home, Projects, Evidence, Reviews, Handoffs, Discover. Home aggregates only projects accessible to the current user. Within a project, use Overview, Record, Evidence, People, and Settings. Reviews and Handoffs can open prefiltered to that project.

Use the same labels everywhere. Evidence means original material; draft means an editable proposal; official record means published knowledge. "Publish" and "Request review" replace Git vocabulary. A private project can work without a lab, faculty member, or institutional hierarchy.

## Six core screens

### 1. Project Home

The header shows title, project status, owner, sharing scope, and the primary action **Add evidence**. Below it, show a short current-state paragraph, the next concrete action, unresolved continuity gaps, and recent approved updates. Link to drafts without mixing them into established findings.

```text
Navigation | Project name                 Private    Add evidence
           | Current state: what works and what is unresolved
           | Next action                 | Handoff readiness
           | Continue the recorded test  | 2 methods need clarification
           | Recent approved updates     | What would be lost?
           | Decisions / methods / results with evidence links
```

Use specific findings such as "Only one person is recorded as knowing this method." Do not equate author count with competence or knowledge redundancy. A number, if retained, opens its calculation and limitations. Empty projects invite their first update and do not receive a misleading readiness rating.

### 2. Add Evidence

Offer **Write an update** and **Upload material**. Within upload, accept a Markdown conversation packet, document, or prepared interview transcript. The interface identifies what it can extract before submission; scanned pages require OCR support and must not silently produce empty results.

For manual lab work, offer editable fields: objective, work performed, observations, deviations, outcome, next step, and attachments. These fields are optional except the title and meaningful content. Let researchers save an unfinished entry.

Show selected project and sharing scope beside the files, with filename, source type, and optional context. The primary action is **Analyze evidence**. Preserve successful uploads when another file fails. Flag possible duplicates and let the researcher open the previous source.

### 3. Analysis Progress

Show real stages: uploaded, reading, extracting, linking evidence, ready for review. Show per-file results and allow navigation away while work continues. Avoid invented completion percentages or theatrical timers.

Failure states give a recovery action: retry a failed file, replace an unreadable scan, or use a transcript. Partial extraction states which pages or sections were processed. A file containing instructions is source material, never authority to change application behavior.

### 4. Review Drafts

Place the original source beside extracted entries. Selecting a citation opens the relevant page or text passage. Each draft shows type, proposed statement, source, and a reason for any uncertainty flag. User-authored edits remain distinguishable from extracted statements.

Researchers can edit, exclude, or combine drafts. Conflicting claims remain separate with their sources. A summary states exactly which entries will be submitted; nothing excluded is published accidentally. Preserve drafts and comments across navigation.

The primary action follows permission: **Publish updates** or **Request review**. An assigned reviewer can approve or request changes. Editing after submission creates a new revision requiring review; approval applies to the exact reviewed revision. Empty change sets cannot be published.

### 5. Published Continuity View

Confirm the published entries, author, reviewer if applicable, time, and linked sources. Keep corrections as new versions with explicit supersession links. Show which documented gaps changed and why; additional text alone is not proof of better continuity.

Keep **What would be lost?** as a scenario, visibly separate from real project changes. Explain the assumptions behind a selected person's departure. Approval can improve documentation completeness; establishing another person's practical readiness requires a separate acknowledgment or evidence.

### 6. Start Here and AI Export

Create a brief with the current state, reproducible methods, failed approaches, decision rationale, files, people, open questions, and suggested first steps. Link claims to approved entries. Label generated suggestions and keep unresolved contradictions visible.

Provide targeted interview questions for missing context. Accept the resulting transcript through the same evidence workflow. A student can mark a question answered, but its extracted content still passes through review.

Export a readable Markdown packet containing a current-state introduction and the full authorized historical decision trail, including superseded decisions. Include source references and an explicit list of unavailable or omitted material. Offer **Copy context for AI** and **Download Markdown**. Large exports split into an index and ordered parts without silent truncation. Drafts are excluded by default; an optional draft appendix is clearly labeled and permission checked.

## Supporting flows

- Private-to-lab attachment: student requests, lab accepts, existing history remains, and the resulting access change is shown before confirmation. Attachment does not automatically publish private sources externally.
- Project administration: manage membership, direct publishing, delegated review, and review requirements independently. Student owner and project admin are separate concepts.
- Discover: preserve The Shelf and revival brief. Public or partner material is an explicitly approved projection of the project, including search and exports.
- Researcher records: keep contribution history and explicit sharing controls. Do not conflate project membership with consent to publish a person's profile.

## Presentation and pilot boundaries

The presentation demonstrates one complete path using fictional evidence. Any prepared extraction is labeled as sample output. Do not claim universal file parsing or a production backend when those are not connected.

Before real lab use, demonstrate server-enforced access for records, sources, search, reviews, and export; persistent accounts and storage; recovery from failed processing; and a tested backup restore. The previously observed partner search/deep-link exposure must be covered by regression checks. A browser-only permission gate cannot protect data shipped in the bundle.

## Acceptance walkthrough

An unfamiliar student can find the next action, record a lab update, upload a conversation packet, verify a cited draft, request review, and resume after refresh. A reviewer can request changes and approve the corrected revision. A new student can read Start Here, inspect its evidence, and export the authorized history. The same journey works with a keyboard and a narrow viewport.
