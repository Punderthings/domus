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

| Path                         | What it holds                                                                             |
| :--------------------------- | :---------------------------------------------------------------------------------------- |
| `src/api/`                   | `client.ts` (fetch, CSRF header, errors), `types.ts`, `queries.ts` (TanStack Query hooks) |
| `src/auth/`                  | Role and access-level helpers, the active property                                        |
| `src/components/`            | App shell, shared widgets                                                                 |
| `src/pages/`                 | One component per route                                                                   |
| `src/router.tsx`             | Routes (TanStack Router, code-based)                                                      |
| `src/terms.ts`               | Display words for data model objects (Area, Device) in one place                          |
| `src/test/`                  | Test setup, fixtures from `examples/sample-home/`, fake API                               |
| `scripts/check-licenses.mjs` | Lockfile license check, no extra dependency                                               |

## Notes

- `src/api/types.ts` is hand-written to match the agreed API contract. Once the backend
  publishes `openapi.json`, it will be generated from that instead.
- The UI hides what a role can't do, but the API enforces every rule. Guests get responses
  with sensitive fields removed, and pages show only the fields that are present.
- Toolchain choices that keep every dependency ASF Category A (decision 19, no MPL): Vite 7
  rather than 8 (Vite 8 requires `lightningcss`, MPL-2.0), `@vitejs/plugin-react-swc` rather
  than the Babel plugin (Babel pulls in `caniuse-lite`, CC-BY-4.0), and
  `eslint-plugin-react-hooks` 5 with ESLint 9. The system font stack is used instead of a
  bundled font, because most open fonts use the OFL (Category B).
