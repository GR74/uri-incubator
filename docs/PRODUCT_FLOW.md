# URI Product Flow

This document records the approved UX direction for turning URI into a user-ready research continuity platform. The interface may change completely; the durable product loop is evidence in, reviewed knowledge out, and safer handoffs over time.

```mermaid
flowchart TD
    A[Create a private project] --> B{Attach to a lab or team?}
    B -- Not yet --> C[Student remains project owner]
    B -- Request attachment --> D[Lab or team accepts]
    D --> C

    C --> E[Project home<br/>status, next action, continuity risks]
    E --> F[Add research evidence]

    F --> F1[Manual update]
    F --> F2[AI conversation packet<br/>Markdown]
    F --> F3[PDF or DOCX]
    F --> F4[Lab notebook record]
    F --> F5[Handoff transcript]

    F1 --> G[Store original artifact<br/>metadata, author, time, hash]
    F2 --> G
    F3 --> G
    F4 --> G
    F5 --> G
    G --> H[Analyze source]
    H --> H1[Extract decisions, methods, results,<br/>dead ends, blockers, and next steps]
    H1 --> H2[Link citations, flag uncertainty,<br/>duplicates, and conflicts]
    H2 --> I[Draft change set]

    I --> J[Human review<br/>edit, combine, exclude, comment]
    J --> K{Direct-publish permission?}
    K -- Yes --> M[Publish to official record]
    K -- No --> L[Request review]
    L --> L1{Reviewer decision}
    L1 -- Changes requested --> J
    L1 -- Approved --> M

    M --> N[Append-only project record<br/>corrections supersede; history remains]
    N --> O[Continuity analysis]
    O --> O1[Project home and risk alerts]
    O --> O2[What would be lost? simulation]
    O --> O3[Search and evidence graph]
    O --> O4[Start Here handoff brief]
    O --> O5[Full-history AI export]

    N --> P{Share externally?}
    P -- No --> Q[Keep within authorized workspace]
    P -- Yes --> R[Consent, redaction, and disclosure review]
    R --> S[Partner-safe project or researcher view]
```

## Product Shell

Use one consistent navigation model instead of manual role lenses:

1. **Home** — assigned work, review requests, continuity risks, and recent activity.
2. **Projects** — project overview, official history, people, artifacts, and settings.
3. **Evidence** — uploads, analysis status, extracted drafts, and source provenance.
4. **Reviews** — grouped change sets, comments, approvals, and audit history.
5. **Handoffs** — readiness checklist, interview questions, Start Here brief, and incoming tasks.
6. **Discover** — shelved projects and approved external sharing.

## Guardrails

- AI output is always a cited draft; it never silently changes the official record.
- Project admins grant publishing and review capabilities and may delegate reviewers.
- Private-to-lab attachment preserves student authorship and prior history.
- Search, exports, and direct URLs enforce the same permissions as visible pages.
- External views receive only explicitly approved, redacted data.

## Presentation Path

For the two-week demo, follow the central path from **Project home** through **Add research evidence**, **Human review**, **Publish**, **Continuity analysis**, and **Start Here**, then finish with the AI export. Use the loss simulation before and after publishing to make the value change visible.
