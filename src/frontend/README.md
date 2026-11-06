# Domus front end

The React + Mantine single-page app (see
[frontend-options.md](../../docs/_prompts/plan/frontend-options.md)). `npm run build` writes
the static files to `src/domus/static/`, which the FastAPI backend serves and which ship in
the wheel and Docker image. Nothing is loaded from a CDN at runtime, so it works offline.

## Develop

Needs Node.js 22.12 or later (npm comes with it).

```sh
cd src/frontend
npm ci
npm run dev          # http://localhost:5173, forwards /api to a local `domus serve` on :8000
```

To try the built app the way users get it, build it and let the backend serve it:

```sh
npm run build                     # writes src/domus/static/
cd ../.. && uv run domus serve    # http://127.0.0.1:8000
```

`domus serve` serves the files in `src/domus/static/` with a strict Content-Security-Policy,
and returns `index.html` for app routes such as `/devices/<id>`.

Run the same checks CI runs:

```sh
node scripts/check-licenses.mjs   # every npm package must be ASF Category A
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

Tests never use the network: `src/test/server.ts` replaces `fetch` with an in-memory fake API.

## Layout

| Path                         | What it holds                                                                                                                |
| :--------------------------- | :--------------------------------------------------------------------------------------------------------------------------- |
| `openapi.json`               | The backend's OpenAPI document, exported by `scripts/export_openapi.py`                                                      |
| `src/api/`                   | `schema.d.ts` (generated), `client.ts` (openapi-fetch, CSRF header, errors), `types.ts`, `queries.ts` (TanStack Query hooks) |
| `src/auth/`                  | Role and access-level helpers, the active property                                                                           |
| `src/components/`            | App shell, shared widgets                                                                                                    |
| `src/pages/`                 | One component per route                                                                                                      |
| `src/router.tsx`             | Routes (TanStack Router, code-based)                                                                                         |
| `src/terms.ts`               | Display words for data model objects (Area, Device) in one place                                                             |
| `src/test/`                  | Test setup, fixtures from `examples/sample-home/`, fake API                                                                  |
| `scripts/check-licenses.mjs` | Lockfile license check, no extra dependency                                                                                  |

## Notes

- API types are generated. `openapi.json` is a copy of the backend's OpenAPI document, and
  `npm run api:types` turns it into `src/api/schema.d.ts` (openapi-typescript), which the
  openapi-fetch client in `src/api/client.ts` uses. `src/api/types.ts` gives the schemas
  friendly names. After changing the API, run `uv run python scripts/export_openapi.py` at
  the repo root, then `npm run api:types`. CI fails if either file is out of date.
- openapi-typescript 7.13 declares a TypeScript 5 peer; an npm `overrides` entry lets it use
  the project's TypeScript 6, which it works with.
- The UI hides what a role can't do, but the API enforces every rule. Guests get responses
  with sensitive fields removed, and pages show only the fields that are present.
- Every dependency is ASF Category A except one build-only exception (decision 20): Vite 8
  requires `lightningcss` (MPL-2.0), which runs at build time and is never part of the built
  app. `scripts/check-licenses.mjs` allows it by name, as a dev dependency only. Other
  choices keep Category B out: `@vitejs/plugin-react-swc` rather than the Babel plugin (Babel pulls in `caniuse-lite`, CC-BY-4.0), and
  `eslint-plugin-react-hooks` 5 with ESLint 9. The system font stack is used instead of a
  bundled font, because most open fonts use the OFL (Category B).
