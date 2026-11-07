# domus :house_with_garden:

Holistic home helper: IOT inventory, mapping, control, and Home Assistant integration.

## Status

Domus is in early development (v0.1). The design work so far, including the original spec, the decisions made, and the master plan, is in [`docs/_prompts/`](docs/_prompts/README.md).

**No data compatibility before v0.3.** During v0.1 and v0.2, database structures, schemas, and backup contents may change in ways that older versions cannot read, and a newer version may not restore an older backup. Don't keep data you care about in Domus yet.

Licensed under the [Apache License 2.0](LICENSE).

To install and run Domus on your own computer, with uv or Docker, see the
[install guide](docs/install-local.md).

To set up a development environment and run the checks, see [CONTRIBUTING.md](CONTRIBUTING.md).
