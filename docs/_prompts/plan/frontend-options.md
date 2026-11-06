# Front end architecture options

*Home IoT Maintenance App · prepared 2026-11-06 · status: **decided 2026-11-06: Option A, React + Mantine** (Shane, citing the wide contributor pools)*

## What the front end has to do

Pulled from the spec and the master plan's working assumptions:

- **Backend contract:** FastAPI serving a versioned REST API at `/api/v1` with an OpenAPI schema. The front end generates a typed client from that schema.
- **Deployment:** a static build (HTML/JS/CSS) served by the backend from one Docker image. It must work fully offline on a laptop, so no CDNs, no hosted fonts, no runtime calls to the internet.
- **Views:** inventory list and detail, maintenance calendar with "mark done and reset the interval", a floor plan viewer with draggable device pins over an uploaded image or simple SVG, a wall photo with pinned hotspots, a Home Assistant import preview (match, dedupe, select), backup/restore, and user admin.
- **Roles:** Admin, Resident, Guest. The UI hides what a role can't do, while the API enforces it.
- **Licensing:** permissive only (MIT, BSD, Apache-2.0, ISC). No GPL, LGPL, or AGPL. The project ships under Apache-2.0.
- **Phone use matters:** "photograph its label" and "find which switch is which" happen standing in front of the device, so the UI must work well on a phone and be able to open the camera.

Server-side rendering frameworks (Next.js, Nuxt in SSR mode, SvelteKit with a Node server) add a second runtime next to Python. With FastAPI already serving the API, every option below is a **client-side single page app built to static files**. That keeps it to one process and one image.

## Things that are the same in every option

| Concern | Choice | License |
| :-- | :-- | :-- |
| Build tool | Vite 8 | MIT |
| Typed API client | `@hey-api/openapi-ts` (generates types plus fetch client) or `openapi-typescript` with `openapi-fetch` | MIT |
| Floor plan and wall photo canvas | **Konva** (drag pins, zoom, pan, hit testing, export to PNG). Each framework has an MIT binding. | MIT |
| Alternative for big plans | Leaflet with `CRS.Simple` (an image as a "map" with tile zoom). Use Leaflet directly. **Avoid `react-leaflet`**, which is under the Hippocratic License and is not OSI-approved. | BSD-2 |
| Calendar view | FullCalendar v7 core plus the free plugins (daygrid, list, interaction). Do not use the premium plugins, which are commercial. Lighter alternative: `@event-calendar/core`. | MIT |
| Recurrence | Compute next-due dates on the **backend** (Python `dateutil.rrule`, BSD). The UI only shows them, so reminders work with the browser closed. `rrule` (JS, BSD-3) is there if previews are needed client-side. | BSD |
| Dates | `dayjs` | MIT |
| Styling | Each option's kit, with fonts bundled in the build (no Google Fonts link) | |
| Offline and installable | `vite-plugin-pwa` (Workbox). This gives a cached app shell and "Add to Home Screen" on phones. Data stays online-first against the local server. | MIT |
| Camera | `<input type="file" accept="image/*" capture="environment">`. This works in every mobile browser with no native wrapper. Images are resized client-side before upload. | n/a |
| Home Assistant | The browser talks to **our backend only**. The backend holds the HA long-lived token and proxies or imports. The token never reaches Guest browsers, and the app still works with HA switched off. (`home-assistant-js-websocket`, Apache-2.0, stays available if we later want live state in the UI.) | Apache-2.0 |
| Testing | Vitest (unit) plus Playwright (end to end) | MIT / Apache-2.0 |
| Lint and format | ESLint plus Prettier, or Biome | MIT |

Because of this shared foundation, the choice below is mostly about **the component framework, the UI kit, and future reuse inside Home Assistant**.

---

## Option A: React SPA with Mantine (recommended)

**Stack:** React 19 · Vite · TanStack Router (type-safe routes) · TanStack Query (server cache, retries, optimistic "mark done") · **Mantine 9** (components plus `@mantine/dates`, `@mantine/dropzone`, `@mantine/notifications`, `@mantine/form`) · TanStack Table for the inventory grid · `react-konva` for floor plans and photos · `@fullcalendar/react`.

**Why it fits**
- Mantine is a single, coherent MIT kit with what this app needs built in: data inputs, date pickers, file dropzone, modals, notifications, dark mode, and responsive layout. "Simple but elegant" comes almost for free, without assembling a design system.
- It has the largest ecosystem and the most contributor familiarity. For an Apache-2.0 open source project, that means more people who can send a PR.
- `react-konva` is the most mature Konva binding. Drag-to-place pins and zoom/pan over a photo are well-trodden ground.
- TanStack Query plus a generated OpenAPI client gives end-to-end types from the FastAPI models to the forms.

**Tradeoffs**
- Larger bundle (roughly 150 to 250 KB gzipped for a first version). That doesn't matter on a LAN or laptop.
- React's churn (server components, compiler) is aimed at SSR frameworks. A plain Vite SPA avoids most of it, but some docs and examples assume Next.js.
- Not natively reusable inside the HA frontend, which is Lit. HA reuse would happen by embedding the app in an HA side panel (iframe panel), which works fine.

**Mobile story:** a responsive PWA. Mantine's `AppShell` collapses to a burger menu, and camera capture uses the file input. A Capacitor wrapper (MIT) could ship app-store builds later with no rewrite.

---

## Option B: SvelteKit SPA with shadcn-svelte

**Stack:** Svelte 5 (runes) · SvelteKit 3 with `adapter-static` in SPA mode (file-based routing, no Node server) · TanStack Svelte Query · **shadcn-svelte** (bits-ui primitives plus Tailwind 4, where component source is copied into the repo) · `sveltekit-superforms` plus `zod` for forms · `svelte-konva` · `@event-calendar/core` (Svelte-native calendar).

**Why it fits**
- Smallest and fastest output (often under 100 KB gzipped). It feels snappy on a cheap tablet mounted on a wall.
- Least code per screen. Svelte 5 reactivity makes forms and editors such as the floor plan noticeably shorter to write.
- shadcn-style "own the component source" means no UI-kit upgrade treadmill, and full control of the look.
- SvelteKit's routing and layouts give structure without needing a server.

**Tradeoffs**
- Smaller ecosystem and contributor pool than React. Fewer ready-made complex widgets.
- `svelte-konva` is at 1.0 and much less battle-tested than `react-konva`. We may drop to plain Konva for the editor.
- shadcn-svelte gives primitives, not a full kit. Data tables, date pickers, and dropzones need more assembly than with Mantine.
- SvelteKit is SSR-first. SPA mode is supported, but some docs and adapters assume a server.

**Mobile story:** same PWA approach as Option A. Capacitor also works.

---

## Option C: Lit web components with Web Awesome (aligned with Home Assistant)

**Stack:** Lit 3 · Vite · a light router (`@lit-labs/router` or Vaadin Router, both permissive) · `@lit/task` plus TanStack Query core for data · **Web Awesome 3** (the successor to Shoelace; MIT core, framework-agnostic web components) · plain Konva for the canvas · FullCalendar core (vanilla) · `home-assistant-js-websocket`.

**Why it fits**
- **Same technology as the Home Assistant frontend.** HA's UI, custom cards, and custom panels are Lit web components. The spec plans a future HA plugin. With Lit, our device card, floor plan viewer, and "next maintenance due" widget could ship directly as HA Lovelace custom cards, using the same code in both places.
- Standards-based components outlive framework churn and can be dropped into any other host app.
- Small runtime (Lit is about 5 KB).

**Tradeoffs**
- The most hand-wiring of the three. Routing, forms, validation, and state management are lighter-weight and less integrated than in React or Svelte, so the first version will be slower to build.
- Smaller app-scale ecosystem. Most Lit examples are widgets, not full CRUD apps.
- Web Awesome's free tier is MIT, but some components and themes are in a paid "Pro" tier. We would stick to free components.
- Shadow DOM makes global styling and some third-party libraries (calendar CSS, for example) fiddlier.

**Mobile story:** same PWA approach.

---

## Side by side

| | A: React + Mantine | B: SvelteKit + shadcn-svelte | C: Lit + Web Awesome |
| :-- | :-- | :-- | :-- |
| Speed to a polished first version | ★★★ | ★★☆ | ★☆☆ |
| Floor plan / photo pin editor maturity | ★★★ (react-konva) | ★★☆ (svelte-konva 1.0) | ★★☆ (plain Konva) |
| Bundle size / runtime speed | ★★☆ | ★★★ | ★★★ |
| Ready-made UI kit completeness | ★★★ | ★★☆ | ★★☆ |
| Contributor pool for open source | ★★★ | ★★☆ | ★☆☆ |
| Reuse inside Home Assistant (cards, panels) | ★☆☆ (iframe panel) | ★☆☆ (iframe panel) | ★★★ (native custom cards) |
| Long-term stability / low churn | ★★☆ | ★★☆ | ★★★ |
| All dependencies permissive | Yes (avoid react-leaflet) | Yes | Yes (free tier only) |

## Recommendation

**Option A, React with Mantine, for the app itself.** It is the quickest route to the "simple but elegant" first version. It has the strongest library for the floor plan and photo pin editor, which is the hardest custom UI in the spec, and the biggest pool of open source contributors.

For the future Home Assistant plugin, **build the HA custom cards as a separate small Lit package** that calls the same `/api/v1` REST endpoints. HA cards are small, so this costs little, and it keeps the main app on the most productive stack. It doesn't block anything now.

Pick **B** if you value a lean, fast UI and are happy to assemble more widgets. Pick **C** if deep native HA embedding matters more to you than speed of the first version.

## First front end steps (once an option is chosen)

1. Scaffold the Vite app inside the monorepo at `src/frontend/` (all source lives under `src/` per AGENTS.md; the build output goes to `src/domus/static/`), with lint, format, Vitest, and Playwright, and add a license check in CI (`license-checker` or similar, failing on GPL, LGPL, or AGPL).
2. Generate the typed API client from FastAPI's `openapi.json` as a build step, and fail CI if it drifts.
3. Build the app shell: layout, auth or login, a role-aware nav, dark mode, and bundled fonts.
4. Build the inventory list and detail plus the "add appliance" flow, including camera upload.
5. Build the maintenance list and calendar plus the "mark done" action with optimistic update.
6. Build the floor plan viewer: upload an image, place and drag pins, and save positions as normalized (0 to 1) coordinates so plans can be re-uploaded at any resolution.
7. Build the wall photo hotspots, reusing the same pin component.
8. Build the HA import preview (backend does discovery; UI shows match, merge, and select).
9. Configure the PWA and test it on a phone over the LAN.

*Versions and licenses were checked against the npm registry on 2026-11-06.*
