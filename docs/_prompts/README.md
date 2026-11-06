# docs/_prompts: design history

This directory records the human and AI design work behind Domus: the prompts and specs we started from, the decisions made along the way, and the planning documents produced from them. It is kept in the repository so contributors can see why the project is shaped the way it is.

It is documentation only. Nothing here is built, imported, or shipped.

## Contents

| Path | What it is | Author |
| :-- | :-- | :-- |
| [00-initial-spec.md](00-initial-spec.md) | The original product request and requirements | Human (Shane Curcuru) |
| [01-decisions.md](01-decisions.md) | Decisions and answers given during planning, in order | Human, recorded by AI |
| [plan/HomeIOT-Master-Plan.md](plan/HomeIOT-Master-Plan.md) | Master plan: requirements, roles and access, architecture, Home Assistant integration, API, security, deployment, libraries, first implementation steps | AI, steered by human review |
| [plan/data-storage-backup.md](plan/data-storage-backup.md) | Data model, file storage, and backup/restore design | AI, steered by human review |
| [plan/frontend-options.md](plan/frontend-options.md) | Front end architecture options and the chosen option | AI, steered by human review |

Related: the sample dataset described in the plan lives in [`examples/sample-home/`](../../examples/sample-home/README.md).

## Conventions

- Add new prompts or specs as numbered files (`02-...md`) so the order of the conversation is preserved.
- Planning documents live under `plan/` and are updated in place as decisions change. Git history keeps earlier versions.
- When a design doc and the code disagree, the code wins. Update the doc, or record the change in `01-decisions.md`.
- AI-generated content was produced with Claude (Anthropic) and reviewed by a human before merging.
