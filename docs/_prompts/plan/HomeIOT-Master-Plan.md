# Home IoT Maintenance App: Master Plan

Status: **Draft v0.3** (2026-11-06). Front end decided (React + Mantine). Backend decided (Python/FastAPI). Name (Domus) and repo (punderthings/domus) decided. Open: confirm the access rule design in section 2.
Project name: **Domus**. Repository: [punderthings/domus](https://github.com/punderthings/domus).

---

## 1. Product summary

A self-hosted web app for technical homeowners to inventory, locate, maintain, and troubleshoot every device in a property: appliances, HVAC, electrical, plumbing, and IoT. It owns its own equipment database (our UUIDs, works without Home Assistant), and enriches records with live Home Assistant (HA) context when HA is available.

Design principles:

1. **Homeowner owns the data.** One portable database plus a files folder. Backup and restore never need HA or internet.
2. **HA-native, not HA-dependent.** Reuse HA vocabulary (area, floor, device, entity, label) so mapping is 1:1, but every feature works standalone.
3. **Boring, permissive stack.** Apache-2.0 project. Core dependencies are MIT/BSD/Apache/ISC/PSF/PostgreSQL only. GPL, AGPL, and SSPL are never used. **LGPL is never used in the core application.** It is allowed only in optional, separately installed extras that a user explicitly enables, such as HEIC photo support via libheif (confirmed by Shane).
4. **Runs anywhere.** One Docker image or `pip install` on a laptop, offline. Same image on any cloud host.
5. **Read-only REST first.** Every core object exposed at `/api/v1` with OpenAPI docs.

## 2. Users and roles

| Role | Can do |
| :-- | :-- |
| **Admin** | Everything: users, backup/restore, HA connection settings, delete. |
| **Maintainer** | Everything a Resident can do, plus adding and configuring devices and integrations: HA connection and import, mapping HA devices to assets, editing rooms and floor plans, and (v0.3+) programming HA items and automations. Cannot manage users or change any Admin, cannot run restore or delete the property, cannot edit critical items, and is limited by any access rules an Admin sets. |
| **Resident** | Create/edit assets, locations, tasks; log maintenance; upload photos; view HA state; trigger HA actions (v2). |
| **Guest** | Sees only items marked public, plus a "house guide" subset (for example, where the water shutoff is). Never sees costs, receipts, serials, or network ids. Can control (v0.2+) only items an access rule allows. |

API tokens (personal access tokens) inherit the owner's role, with an optional read-only scope for integrations.

**Access rules (one model for guests, maintainers, and protected items).** Roles rank Admin > Maintainer > Resident > Guest. The typical Maintainer is the teenage geek in the house: they can add the new game console and TV and wire them into HA, but the parents don't let them reach the master bedroom controls. Two Admin-only settings sit on top of roles (schema in data-storage-backup.md section 2.3.1):

- **Critical items** (`is_critical` on asset and area): only Admins can edit, re-map, reconfigure, or delete them. Every other role keeps its normal view and control. Examples are the furnace, the main water shutoff, the alarm panel, and the HA connection itself.
- **Access rules** (one `access_rule` table): each rule has a scope (building, area, tag, or asset), a subject (a role or one specific member), a level on the ladder `hidden < view < control < manage`, and an optional expiry. Rules can raise or lower access. The most specific scope wins (asset > tag > area > building), and a rule for one member beats a rule for their role.
- **Defaults**: Guests get `view` everywhere and never see costs, receipts, serials, or network ids. Admins are never limited by rules.
- **Shane's examples, as rules**:
  - Guests can switch lights in public rooms but not bedrooms: `guest: control` on the living room, kitchen, and porch, with bedrooms left at the guest default of `view`.
  - The teen Maintainer can't touch the master bedroom: `maintainer: view` on the master bedroom, and a `guest: view` rule there as well. Use `hidden` instead to hide it entirely.
  - The house sitter can control the thermostat for two weeks: a member rule of `control` on the thermostat with an expiry.
  - The teen can run the living room TV even though the room is restricted: a member rule of `control` on the TV asset.
- **Enforcement**: one server-side `AccessPolicy` service. Guest API responses use a separate response schema with sensitive fields removed. HA service calls are checked against the effective level before they are proxied, and the HA token never leaves the backend. Restricted and critical items are left out of a Maintainer's HA import preview and bulk edits, so re-importing cannot change them. Every rule change is written to the audit log, and tests cover each role against each level.
- **HA caveat**: HA has no per-device user permissions, so these limits only hold for actions that go through our app. A Maintainer with their own HA admin login could bypass them in HA, so the docs will recommend giving Maintainers a non-admin HA user.

## 3. Scope by release

**v0.1 MVP** (the schema supports several properties per install, which Shane confirmed; the v0.1 UI shows one property with a switcher added later)
- Inventory: assets with name, category, manufacturer, model, serial, MAC, install date, warranty, purchase info, notes, tags, links to manuals.
- Locations: Property > Building > Floor > Room > Location (wall + position, window, ceiling, etc.). A property can have several buildings (house, garage, shed), and outdoor areas (yard, driveway) attach directly to the property.
- Maintenance: recurring tasks with intervals ("every 6 months", "every November"), due list, mark done, auto-reschedule, completion log with cost and notes.
- Attachments: photos (device label, wall), PDFs (manuals), with thumbnails.
- Floor plan viewer: upload an image per floor, drop pins for assets. Wall photo viewer with hotspot pins.
- HA import: connect with a long-lived token, preview devices/areas/floors, match existing assets, import selected without duplicates.
- Auth: local users with Admin/Maintainer/Resident/Guest.
- Backup/restore: one-click archive (DB + files + manifest), scheduled backups, restore from UI or CLI.
- Read-only REST API and iCal feed of upcoming maintenance.

**v0.2**
- Live HA context on asset page (state, last seen, IP/network, battery, power source) via WebSocket.
- Search across everything (name, model, serial, MAC, room, tag, circuit).
- Parts catalog per asset (filter part numbers, purchase links) and procedures (step lists).
- Notifications: email (SMTP), HA persistent notification / mobile push via HA, ntfy/webhook.
- CSV/JSON export of selected records; printable QR labels for assets.

**v0.3+**
- Outdoor site map: buildings placed on an aerial or sketch site image, with outdoor assets (landscape lighting, irrigation, hose bibs, septic) pinned on it.
- Infrastructure entities: electrical panels, breakers/circuits, conduits, plumbing lines, shutoff valves, with "fed by" relationships (breaker 14 powers outlets in Kitchen; valve V3 isolates hose bib).
- Seasonal tasks tied to infrastructure (November: close V3 and drain hose).
- Home Assistant custom integration (Python, HACS) exposing maintenance due dates as HA sensors/todo items and accepting "mark done" from HA.
- Optional OIDC login (Authentik, Keycloak, HA as OAuth provider), multi-property.
- Optional OCR of label photos to prefill model/serial (Tesseract, Apache-2.0).

## 4. System architecture

```
 Browser (SPA, served as static files)
        │  HTTPS, JSON, cookie session or bearer token
        ▼
 ┌──────────────────────────── App container ───────────────────────────┐
 │ FastAPI (ASGI, Uvicorn)                                              │
 │  ├─ /api/v1/*   REST (read-only public surface + write endpoints)     │
 │  ├─ /auth/*     login, logout, tokens                                 │
 │  ├─ /calendar.ics  iCal feed (token in URL, read-only)                │
 │  ├─ Services: inventory, locations, maintenance, attachments,         │
 │  │            ha_sync, backup, notifications                          │
 │  ├─ Scheduler (APScheduler, in-process): due-date checks, backups,   │
 │  │            HA resync                                               │
 │  └─ HA client (httpx + websockets), optional                          │
 └───────┬──────────────────────────────┬───────────────────────────────┘
         ▼                              ▼
  SQLite (default) or PostgreSQL   Files dir (photos, manuals, thumbs,
  via SQLAlchemy 2 + Alembic       floor plans), content-addressed
                                         │
                       Home Assistant (optional) ◄── REST + WebSocket API
```

Key decisions:

- **Modular monolith.** One process, clear internal service modules. No message broker, no separate worker. A homeowner app does not need microservices, and a single process is what makes "runs on a laptop" true.
- **Backend: Python 3.14+ / FastAPI** (confirmed by Shane; 3.14+ for all project code, CI, and the Docker base image). 3.14 also gives us the built-in `uuid.uuid7()`, so no extra UUID package is needed. The future HA custom integration has to run on whatever Python version Home Assistant ships, and we will target 3.14+ there too as long as HA supports it. Reasons: HA and its future integration are Python; Pydantic models generate OpenAPI and typed front end clients; mature permissive ecosystem.
- **Storage abstraction for files**: local directory by default; S3-compatible object storage optional for cloud (boto3, Apache-2.0).
- **Configuration**: environment variables and a single `config.toml` (pydantic-settings). Secrets (HA token, SMTP password) encrypted at rest in DB with a key from env/file.

### 4.1 Core domain model (summary; the authoritative schema is in section 6 and data-storage-backup.md, which adds product, asset_identifier, and asset_relation tables)

| Entity | Key fields |
| :-- | :-- |
| Property | id (UUIDv7), name, address, timezone, site_plan attachment (optional, v0.3+) |
| Building | id, property_id, name, kind (house, garage, shed, barn, pool_house, other), is_primary, notes; site placement (v0.3+): site_x, site_y in meters in a local per-property grid (origin is a user-chosen point, x east, y north), rotation, footprint polygon. No latitude/longitude by default, for privacy. |
| SpatialRelation | id, from_type/from_id and to_type/to_id (building or area), kind (attached_to, adjacent_to, detached, connected_by), via (breezeway, buried conduit, ...), distance_m, bearing, notes |
| Floor | id, building_id, name, level, floor_plan attachment, ha_floor_id |
| Room (HA "area") | id, floor_id (nullable), property_id, name, kind (room, hallway, attic, yard, driveway, ...), ha_area_id. Outdoor areas have no floor, belong to the property directly, and get site_x, site_y, and a footprint (v0.3+). |
| Location | id, room_id, kind (wall, ceiling, floor, window, door, exterior, inside_asset), wall (N/E/S/W or label), x/y on floor plan, x/y on wall photo, description |
| Asset | id (UUIDv7), name, category, manufacturer, model, serial, mac_addresses[], other_ids (JSON), install_date, purchase_date, warranty_until, power_source, network info, location_id, parent_asset_id, status, notes, ha_device_id, ha_entity_ids[] |
| Attachment | id, owner (asset/location/floor/task), kind (photo, manual, receipt, label), sha256, mime, filename, url (external link alternative) |
| MaintenanceTask | id, asset_id or location_id, title, procedure (markdown), recurrence (RFC 5545 RRULE or "N days after last done"), next_due, lead_time, parts[] |
| MaintenanceEvent | id, task_id, done_at, done_by, cost, notes, attachments |
| Part | id, asset_id, name, part_number, vendor_url, typical_cost |
| Tag | id, name, color (maps to HA labels) |
| User / ApiToken | id, email, display_name, role, password_hash (argon2) |
| AuditLog | who, what, when, before/after |

**Buildings and the site.** Every property has at least one building, created automatically as the primary building ("House"), so single-building users never see the extra level. Buildings and outdoor areas (yard, patio) get simple spatial relationships now: attached, adjacent, detached, or connected by something such as a breezeway or buried conduit, with optional distance and bearing. Outdoor areas also get site_x, site_y, and a footprint. Site coordinates are real meters, so distances such as a landscape lighting run can be measured. The site placement fields are reserved for a future outdoor map (v0.3+): an uploaded aerial or sketch image, or a simple SVG, with buildings drawn as footprints and outdoor assets pinned on it, such as landscape lighting, irrigation zones, the hose bib, or the septic tank. Pins on the site-plan image itself still use normalized 0-1 coordinates, like the floor plans, so the same Konva viewer works for both.

Two recurrence modes cover real life: **fixed calendar** ("every November 1") via RRULE, and **floating** ("6 months after it was last changed"), where marking done recalculates next_due from the completion date.

### 4.2 Home Assistant integration

HA exposes everything we need, without a custom component, through its WebSocket API (authenticated with a long-lived access token):

| HA command | Used for |
| :-- | :-- |
| `config/floor_registry/list` | Floors (HA has no building concept, so on import the user assigns each HA floor to a building, defaulting to the primary building) |
| `config/area_registry/list` | Rooms |
| `config/device_registry/list` | Devices: manufacturer, model, sw/hw version, serial, `connections` (MAC), `identifiers`, area |
| `config/entity_registry/list` | Entities per device |
| `config/label_registry/list` | Labels to tags |
| `get_states` / `subscribe_entities` | Live state on troubleshooting view |
| REST `POST /api/services/<domain>/<service>` | Control (v0.2+, Admin/Maintainer/Resident, subject to protection) |

Import workflow ("no duplicates"):
1. Fetch registries, build candidate list.
2. Match against existing assets in priority order: stored `ha_device_id` > MAC address > (manufacturer + serial) > (manufacturer + model + area) fuzzy name match.
3. Show a preview: New / Matched / Changed / Ignored. User picks.
4. Apply in one transaction; store `ha_device_id` link and a sync snapshot. Re-runs are idempotent.

HA is never a source of truth for our fields; we store HA IDs as foreign references only. If HA is offline, the asset page shows "HA unavailable" and everything else works.

Future HA custom integration (v0.3, Python, in a separate repo, HACS-installable) talks to our REST API and exposes: a `todo` entity of due maintenance, per-asset "next maintenance" sensors, and a service `domus.mark_done`.

### 4.3 API design

- REST, JSON, `/api/v1`, OpenAPI 3.1 auto-generated, served at `/api/docs`.
- Read-only endpoints for every core entity (list with filters + pagination, get by UUID). Write endpoints exist for the UI but are documented as "unstable" until v1.0.
- Field naming follows HA where it overlaps (`area_id`, `floor_id`, `device_id`, `manufacturer`, `model`, `sw_version`, `serial_number`, `connections`).
- Auth: secure HttpOnly session cookie for the browser (with CSRF token); bearer personal access tokens for integrations.
- ETags + `updated_since` filter so integrations can sync cheaply.

### 4.4 Security

- Passwords: Argon2id (argon2-cffi, MIT). Rate-limited login.
- First-run setup wizard creates the Admin; no default credentials.
- Uploads: size limits, MIME sniffing, images re-encoded with Pillow to strip EXIF/GPS, PDFs served with `Content-Disposition: attachment` option, strict CSP.
- Role checks in a single dependency layer, tested per endpoint.
- HA token and SMTP secrets encrypted at rest (cryptography / Fernet, Apache-2.0/BSD).
- Run as non-root in container. Behind a reverse proxy for TLS in cloud; documented Caddy (Apache-2.0) example.

### 4.5 Deployment

| Target | How |
| :-- | :-- |
| Laptop, offline | `pipx install domus && domus serve` (SQLite, ./data dir), or `docker run -v ./data:/data` |
| Home server / NAS | Docker Compose (app + optional Postgres) |
| Alongside HA | Same Docker host; later an HA add-on wrapper (HA add-ons are just containers) |
| Cloud VM / PaaS | Same image; Postgres + S3-compatible storage via env vars |

All front end assets are bundled into the image. No runtime CDN calls, so it works fully offline.

### 4.6 Backup and restore (summary; the final format is `.hiotbak`, see section 6)

- Backup = one `.tar.gz` (or zip) containing a consistent DB snapshot (SQLite online backup API or `pg_dump`-free logical JSON export), the files directory, and a `manifest.json` (app version, schema version, checksums).
- Plus a **portable JSON export** of all records so data survives even if the app is abandoned.
- Scheduled backups with retention; optional copy to a second path or S3 target.
- Restore runs migrations forward if the backup is from an older schema version.
- CLI `domus backup|restore|export` works with the server stopped and without HA.

## 5. Candidate libraries and licenses (backend)

| Need | Library | License |
| :-- | :-- | :-- |
| Web framework | FastAPI, Starlette, Uvicorn | MIT, BSD-3, BSD-3 |
| Models / validation / settings | Pydantic v2, pydantic-settings | MIT |
| ORM / migrations | SQLAlchemy 2, Alembic | MIT |
| Postgres driver | asyncpg | Apache-2.0 (**avoid psycopg2/3: LGPL**) |
| SQLite async | aiosqlite | MIT |
| Recurrence | python-dateutil (rrule) | Apache-2.0 / BSD dual |
| iCal feed | icalendar | BSD-2 |
| Scheduler | APScheduler 3.x | MIT |
| HTTP / WebSocket to HA | httpx, websockets | BSD-3 |
| Password hashing | argon2-cffi | MIT |
| Encryption | cryptography | Apache-2.0 / BSD |
| Images | Pillow | MIT-CMU (HPND) |
| QR labels | segno | BSD-3 |
| Fuzzy match on import | rapidfuzz | MIT |
| CLI | Typer | MIT |
| Tests / lint / types | pytest, ruff, mypy | MIT |
| Search | SQLite FTS5 / Postgres full-text (built in) | Public domain / PostgreSQL |

A CI step (`pip-licenses` MIT, and `license-checker` for the JS side) fails the build on any GPL/LGPL/AGPL dependency in the core install or the Docker image, including transitive ones. Optional extras such as `domus[heic]` (libheif, LGPL) live in a separate dependency group that is excluded from the core image and checked separately. They are off unless the user installs and enables them.

## 6. Database and storage

Full design: [data-storage-backup.md](data-storage-backup.md). It confirms the stack in section 4 and adds the following.

- **SQLite 3 in WAL mode is the official database.** PostgreSQL 15+ is supported behind the same SQLAlchemy models but is marked experimental in v1. Drivers are aiosqlite and asyncpg.
- **UUIDv7 for every row**, stored as text so exports stay readable.
- **`asset_identifier` table**: MAC addresses, serials, HA device/entity ids, and any other ids live here, one row each. This is what drives HA import dedupe and lookup by any id.
- **`asset_relation` graph**: `powered_by`, `networked_via`, `shutoff_for`, and so on. Circuits, breakers, pipes, and valves (v0.3) become ordinary assets with relations, so they need no schema redesign.
- **`product` table**, kept separate from the physical `asset`, so manuals, parts, and default maintenance tasks for a model are shared by every unit of it.
- **Content-addressed blob store** (SHA-256) behind a `BlobStore` interface. Local filesystem by default, any S3-compatible service optional.
- **One `.hiotbak` zip format** (manifest + DB snapshot + engine-neutral JSONL export + blobs). It is reused for full backups, partial exports, and "house handover" packages for a buyer. Restore supports `--merge` and `--dry-run`.
- **Off-site copies** are documented recipes rather than built in for v1: restic (BSD-2) for the backup folder, and Litestream (Apache-2.0) for continuous SQLite replication on cloud hosts.
- **Search** uses SQLite FTS5, or `tsvector` + `pg_trgm` on Postgres, behind one `SearchIndex` service.
- **More license traps to avoid**: sharp/libvips and libheif (LGPL), MuPDF (AGPL), Poppler (GPL), MinIO and Garage (AGPL). Manuals are rendered in the browser with pdf.js (Apache-2.0), and images are processed with Pillow.

## 7. Front end architecture options

Full comparison: [frontend-options.md](frontend-options.md). **Decision: Option A, React + Mantine** (Shane chose it for its very wide contributor pool).

All three options are client-side SPAs built with Vite into static files served by FastAPI. Each uses a typed client generated from `openapi.json`, so none needs a Node server at runtime and all work offline.

| Option | Stack | Why pick it |
| :-- | :-- | :-- |
| **A (chosen)** | React 19 + Mantine + TanStack Router/Query + react-konva | Largest ecosystem and contributor pool, rich component library, mature canvas bindings |
| B | SvelteKit (adapter-static SPA) + shadcn-svelte + svelte-konva | Smallest bundles and least boilerplate |
| C | Lit 3 + Web Awesome | Same web-component model as the HA frontend, so the UI can be reused later as native HA custom cards |

Shared across all options:
- Konva for floor plan and wall photo pins. Pin positions are stored as normalized 0-1 coordinates, so they survive replacing an image with a different resolution.
- FullCalendar, using its MIT plugins only, for the maintenance calendar.
- Recurrence is computed on the backend (dateutil.rrule), never in the browser.
- Installable PWA via vite-plugin-pwa.
- The HA token is held only by the backend.
- License flag: react-leaflet uses the Hippocratic License, which is not permissive, so avoid it.

## 8. Repository layout and engineering practice

```
domus/
  backend/   src/domus/{api,services,models,ha,backup,cli}, tests/, alembic/
  frontend/  React + Mantine SPA (Vite, TypeScript strict)
  docs/      (MkDocs Material, MIT; docs/_prompts/ holds the human + AI design history)
  deploy/    Dockerfile, compose.yaml, Caddyfile example
  .github/   CI: lint, typecheck, test, license check, build image
  LICENSE (Apache-2.0), NOTICE, CONTRIBUTING.md, SECURITY.md
```

- Python 3.14+ everywhere (`requires-python = ">=3.14"`, ruff `target-version = "py314"`). Pre-commit with ruff (lint+format), mypy strict on backend, ESLint + Prettier + TypeScript strict on front end.
- Tests: pytest with a fake HA WebSocket server fixture; Playwright (Apache-2.0) end-to-end for the five core workflows.
- Conventional commits, semantic versioning, release images to GHCR.
- DCO or simple CLA-free Apache-2.0 contributions.

## 9. Spec workflows mapped to features

| Workflow | Release | Features |
| :-- | :-- | :-- |
| Add an unconnected appliance | v0.1 | Asset form, label photo upload, manual link/upload, location picker, task template |
| Import HA devices | v0.1 | HA connect, registry fetch, match preview, idempotent import |
| Troubleshoot a device | v0.1 docs/history, v0.2 live HA state | Asset detail page: docs, HA context, network, power, service history |
| Perform maintenance | v0.1 mark done + cost, v0.2 parts/procedures | Task detail, completion form, next-due calculation |
| Find equipment physically | v0.1 room/tag filter + floor plan, v0.2 search, v0.3 circuit | Filters, floor plan pins, search |
| Recover or transfer records | v0.1 | Backup/restore UI + CLI, JSON export |

## 10. First implementation steps (prioritized)

1. **Repo bootstrap** in punderthings/domus: Apache-2.0 LICENSE/NOTICE, monorepo layout, pre-commit, CI with lint/type/test/license check.
2. **Backend skeleton**: FastAPI app, settings, SQLAlchemy + Alembic, SQLite default, health endpoint, OpenAPI docs, Dockerfile.
3. **Auth and roles**: first-run admin setup, login/logout session cookie, Admin/Maintainer/Resident/Guest dependency, critical-item and access-rule checks, personal access tokens, and the guest visibility filter with guest-safe response schemas. Tests prove a Guest cannot read hidden items or sensitive fields.
4. **Data model + initial migration**: property, floor, area, location, product, asset, asset_identifier, asset_relation, tag, document, blob, attachment, maintenance_task, maintenance_event, user, membership, access_rule, audit_log, plus building and spatial_relation. Enable SQLite WAL, foreign keys, and busy timeout. CRUD and read-only list/get endpoints with tests.
5. **Attachments**: `LocalFsBlobStore` with streaming SHA-256 and atomic writes, upload endpoint with type sniffing, EXIF strip, thumbnails, external links.
6. **Maintenance**: `compute_next_due` for both RRULE and floating modes (tests for month-end and DST edges), due list, mark-done, event log, iCal feed.
7. **Backup/restore v1**: JSONL export/import (full and partial), `.hiotbak` writer/reader/verifier, `backup create|verify` and `restore [--merge] [--dry-run]` CLI, scheduled backups with retention, backup-wipe-restore round-trip test in CI. Then the FTS5 search index.
8. **Front end shell** (React + Mantine + TanStack Router/Query, Vite): app layout, login, inventory list/detail, asset form, due-maintenance dashboard.
9. **Floor plan + wall photo pins**: upload plan image per floor, place/drag asset pins, hotspot pins on wall photos.
10. **HA import**: connect screen, registry fetch, matcher, preview, idempotent apply; fake-HA test fixture.
11. **v0.1 release**: Docker image, Compose example, docs site, seeded demo data.

Steps 2 to 7 can start immediately. Step 8 uses React + Mantine and follows the 9-step front end list in [frontend-options.md](frontend-options.md).

## 11. Open questions for Shane

- Critical items and access rules: does the design in section 2 fit what you want? It is written out using your master bedroom examples.

1. ~~Backend language?~~ Answered: Python/FastAPI.
2. ~~Multiple properties?~~ Answered: yes, in the schema.
3. ~~Project name?~~ Answered: Domus.
4. ~~Notifications in v0.1?~~ Answered: iCal feed only; email and HA push come in v0.2.
5. ~~GitHub repo?~~ Answered: punderthings/domus.
6. ~~Front end?~~ Answered: React + Mantine.
7. ~~Postgres in v1?~~ Answered: experimental in v1.
8. ~~Backup encryption?~~ Answered: optional.
9. ~~HEIC?~~ Answered: optional extra only. LGPL is never allowed in core.
10. ~~Guest limits?~~ Answered: guests are limited in what they see and control, implemented with access rules (section 2).
