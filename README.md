# domus :house_with_garden:

Holistic home helper: IOT inventory, mapping, control, and Home Assistant integration.

## Status

Domus is in early development. The v0.1 features are merged on `main`; no release is tagged yet.

What v0.1 does: an inventory of Devices by Property, Building, Floor, and Area; maintenance tasks with due dates, **Mark done**, and an iCal feed; floor plans and wall photos with device pins; import from Home Assistant; search; roles (Admin, Maintainer, Resident, Guest) with access rules and critical items; and backups you can make in the web interface or the CLI, with restore from the CLI. What is still to do from the v0.1 plan, such as scheduled backups, is listed in [section 12 of the master plan](docs/_prompts/plan/HomeIOT-Master-Plan.md#12-v01-status-2026-11-07).

The design work, including the original spec, the decisions made, and the plans, is in [`docs/_prompts/`](docs/_prompts/README.md).

**No data compatibility before v0.3.** During v0.1 and v0.2, database structures, schemas, and backup contents may change in ways that older versions cannot read, and a newer version may not restore an older backup. Don't keep data you care about in Domus yet.

Licensed under the [Apache License 2.0](LICENSE).

To install and run Domus on your own computer, with uv or Docker, see the
[install guide](docs/install-local.md).

To set up a development environment and run the checks, see [CONTRIBUTING.md](CONTRIBUTING.md).
