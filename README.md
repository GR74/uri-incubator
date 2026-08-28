# URI — Undergraduate Research Incubator

A research continuity register for undergraduate labs. Prototype, sample data.

Undergraduate labs lose roughly four years of knowledge every four years: students
graduate mid-project, and what they tried, what failed, and why they chose one
approach over another leaves with them. URI is one record — written when someone
leaves, read when someone arrives.

**Live:** _(add your deploy URL here)_

## What's in it

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
build/build.js    rebuilds index.html from src
build/vendor/     React, Tailwind, Babel, and the embedded typefaces
```

## Changing something

```bash
# 1. edit src/uri.html
# 2. rebuild
node build/build.js
# 3. commit and push — the host redeploys on its own
```

`src/uri.html` opens directly in a browser for quick checks (it loads React and
the fonts from CDNs, so it needs a connection). `index.html` is fully
self-contained and is what gets deployed.

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
