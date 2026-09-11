# URI — Undergraduate Research Incubator

A research continuity register for undergraduate labs. Prototype, sample data.

Undergraduate labs lose roughly four years of knowledge every four years: students
graduate mid-project, and what they tried, what failed, and why they chose one
approach over another leaves with them. URI is one record — written when someone
leaves, read when someone arrives.

**Live:** https://gr74.github.io/uri-incubator/

## What's in it

The new research workspace opens by default. It groups project work, evidence,
reviews, handoffs, and discovery in one navigation shell. Drafts and sample
records are stored in the browser; authentication, cloud storage, and AI
extraction are not connected yet. The original three-lens prototype remains
available from **Original prototype** or with `?legacy=1`.

Each project also has a **Research** view for team-entered tasks, experiments,
milestones, and explicit measurements. Operational tracking stays separate from
the reviewed evidence record and can be exported as project-scoped CSV or JSON.

Three lenses over the same log, switched from the control at the top right:

| Lens | What it's for |
|---|---|
| **Undergraduate** | What you owe the log this week, the shelf of projects you can pick up, your own research record |
| **Faculty & PhD** | Continuity risk, the departure timeline, the sign-off queue, and the extraction interview |
| **Partner** | A redacted view of projects open for continuation, and consented student records |

Highlights worth finding:

- **Continuity Risk → "What would be lost"** — remove a person and the log is
  recounted with their entries treated as unreachable. It names the specific
  procedures that would lose their only living author.
- **Shelve a project** — a six-step extraction interview whose questions are the
  sections of the brief the next student reads. Step 2 asks the thing most
  handoffs leave out: why did you actually stop?
- **The Shelf → claim a project** — the extraction record becomes the opening
  continuity log, so a revived project starts with history instead of a blank page.

Press <kbd>⌘K</kbd> / <kbd>Ctrl+K</kbd> to search everything, or use the
walkthrough in the footer for a guided six-stop tour.

## Repo layout

```
index.html        the deployed page — generated, do not edit by hand
src/uri.html      the source — edit this
src/workspace.jsx workspace screens, project overview, handoff and export
src/workspace-evidence.jsx local evidence intake and review workflow
src/workspace-research-domain.jsx immutable tracking revisions and exports
src/workspace-research.jsx project research view and operational summary
src/workspace.css responsive workspace styles
build/build.js    rebuilds index.html from src
build/serve.js    serves a local preview at http://127.0.0.1:4173
build/vendor/     React, Tailwind, Babel, and the embedded typefaces
tests/            Node regression tests and fictional upload fixtures
```

## Changing something

```bash
# 1. edit the relevant file under src/
# 2. rebuild
node build/build.js
# 3. preview
node build/serve.js
# 4. run regression tests
node --test tests/*.test.cjs
```

Open the local server root for the self-contained production preview. For source
preview, open `/src/uri.html` on that server; it loads React and fonts from CDNs
and the local JSX modules. `index.html` remains self-contained and deployable.

## Local backend ingestion foundation

`backend/` provides a PostgreSQL-only local service for fictional pilot records.
Uploads are accepted into a durable queue and expose a project-authorized status
URL; completed versions expose immutable, locator-addressable parts and seven
independent quality dimensions. Quality is deliberately not combined into a
score. Privacy and licensing cautions are reported separately.

The ClearerMind metadata helper creates only a fictional local owner, project,
and declared evidence-selection metadata. It never reads or imports a repository
or conversation export. It requires explicit repository/ref/commit-range and
conversation selections before it records that declaration.

```bash
cd backend
uv run alembic upgrade head
uv run uri-api
uv run python scripts/seed_clearermind_pilot.py --repository /explicit/local/path --ref main --start-commit <sha> --end-commit <sha> --conversation-id <selected-id>
uv run pytest -q
```

On Windows, use `uv run uri-api` for the local API rather than calling Uvicorn
directly without reload. The launcher selects the event loop required by the
PostgreSQL async driver before the server starts.

### Two things that bite when editing by hand

**A stray newline inside a quoted string blanks the whole page.** Copy that spans
lines has to stay on one line inside `'...'`. There's no visible error — the page
just renders empty. Open it in a browser after editing; the build script also
fails loudly rather than shipping a broken bundle.

**Renaming a person means changing two fields.** In the `PEOPLE` registry, `n:` is
the display name and `s:` is what log entries match their author against. Change
only one and that person's entries silently detach from them, which quietly
changes the single-source counts and the departure simulator.

## Deploying

The build output is a single static file, so any static host works with no
configuration.

**Vercel** — import the repo, framework preset *Other*, leave the build command
empty and the output directory as the repo root. Every push redeploys.

**GitHub Pages** — Settings → Pages → deploy from branch `main`, folder `/ (root)`.

## Notes

All people, projects and results in this prototype are fictional.
