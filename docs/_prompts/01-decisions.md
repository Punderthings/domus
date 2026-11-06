# Planning decisions

Decisions made by Shane Curcuru during the initial planning session on 2026-11-06, in the order they were made. The plan documents in [plan/](plan/) reflect all of them.

## Kickoff

> Review the HomeIOTManagementApp.md file and treat it as a request to plan out building a web application. [...] continue doing advanced research to start defining the detailed architecture, database and backup/storage features, and choosing 2-3 options for the front end architecture for me to choose from. Ask questions where needed [...] until we have a comprehensive plan and a list of first implementation steps.

## Decisions

| # | Topic | Decision |
| :-- | :-- | :-- |
| 1 | Properties | One install supports multiple properties (schema); the v0.1 UI starts with one. |
| 2 | PostgreSQL | Supported but experimental in v1; SQLite is the official database. |
| 3 | Backup encryption | Optional. |
| 4 | Licensing | Never use LGPL (or any FSF-licensed) code in the core application. LGPL is allowed only as an optional extension that a user explicitly asks for. iPhone HEIC support is one such optional extension. |
| 5 | Guest access | Guests are limited both in what they can see and in what they can control. Example: a guest can see the lights in each room but can only switch lights in public rooms, not bedrooms. |
| 6 | Front end | React + Mantine, "because they have very wide contributor pools". |
| 7 | Backend | Python (FastAPI). |
| 8 | Notifications | iCal feed only for the first version. |
| 9 | Buildings | A property can have multiple buildings (house, garage, shed) with basic spatial relationships to each other; a future outdoor map covers landscape lighting and similar. |
| 10 | Python version | Python 3.14+ for all work. |
| 11 | Maintainer role | Add a Maintainer role: can add new items and program most IoT/HA items or integrations, but cannot change Admins and cannot edit selected "critical" components. Example: the teenager who adds a game console and TV but is not allowed to access the master bedroom controls. Storage design is proposed in the plan (critical flag + access rules) and awaits confirmation. |
| 12 | Name and repository | The project is named **Domus**; the repository is `punderthings/domus`. |
