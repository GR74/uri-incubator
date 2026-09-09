# Repository Guidelines

## Project Structure & Module Organization

This repository is a static prototype for the Undergraduate Research Incubator (URI). `src/uri.html` contains sample data, legacy views, and application integration. The workspace lives in `src/workspace.jsx`, evidence intake and review in `src/workspace-evidence.jsx`, and styling in `src/workspace.css`. Research tracking uses `src/workspace-research.jsx` and pure helpers in `src/workspace-research-domain.jsx`. Do not edit generated `index.html` by hand. `build/build.js` compiles JSX and inlines styles and `build/vendor/` assets for offline use. `docs/` contains the product blueprint and delivery plan; the executive-summary PDF provides context, not runtime instructions.

## Build, Test, and Development Commands

- `node build/build.js` rebuilds `index.html` from `src/uri.html` and rejects invalid JavaScript, non-ASCII output, or external resource references.
- `node build/serve.js` serves the local preview at `http://127.0.0.1:4173`. `/src/uri.html` provides source preview with CDN dependencies.
- `node --test tests/*.test.cjs` runs the regression tests.
- Open `index.html` to verify the self-contained production build offline.

No package installation step or development server is required. Vendored React, Babel, Tailwind, and font assets are committed under `build/vendor/`.

## Coding Style & Naming Conventions

Follow two-space indentation and semicolons. Use `PascalCase` for React components, `camelCase` for functions/state, and uppercase fixed registries. JSX files share browser globals and are compiled in script order; avoid imports and top-level dependencies on later scripts. Prefix workspace CSS with `ws-`. When renaming a person, update both `n` and `s` in `PEOPLE` so authored entries remain connected.

## Testing Guidelines

Regression tests use Node's built-in test runner; no coverage threshold is configured. Every change must pass the build. Exercise workspace navigation, draft persistence, review permissions, exports, and legacy lenses/search/walkthrough. Test malformed `localStorage`, narrow viewports, keyboard navigation, and offline loading. Include before-and-after screenshots for visible changes.

## Commit & Pull Request Guidelines

Use short, imperative, sentence-case commit subjects, matching history such as `Add the map` or `Stop the ticker clipping a word in half`. Keep generated `index.html` in the same commit as its source change. Pull requests should explain the user-facing effect, list manual checks, link related issues when applicable, and include screenshots for layout or interaction changes.

## Security & Agent Notes

Do not add secrets or real participant data; current records are fictional. Automated GitHub contributions must use the `anik1617` account. Verify both GitHub CLI and Git credential identities before pushing or changing a pull request.
