# Contributing to Domus

Thanks for helping. Domus is licensed under the [Apache License 2.0](LICENSE), and
contributions are accepted under the same license. AI coding agents should also read
[AGENTS.md](AGENTS.md), which applies to people too.

## Set up

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.14 for you if needed.

```sh
uv sync                     # create .venv with the package and dev tools
uv run pre-commit install   # optional: run ruff and pyright before each commit
```

## Checks

CI runs these on every pull request; run them locally first:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv run pip-licenses --from=mixed --format=json | uv run python scripts/check_licenses.py
```

Tests must not use the network; stub or mock every fetch.

## Dependencies

Every dependency, including build and test tools, must use a license on the
[ASF Category A list](https://www.apache.org/legal/resolved.html#category-a). Name the
license in your pull request. Ask a maintainer before adding a dependency, a tool, or a
GitHub Actions workflow. The license check fails CI on anything else. The one exception
is an occasional MPL-2.0 build-time tool that is completely separate from application
code: a maintainer reviews it, and it is listed by name in `BUILD_ONLY` in
`scripts/check_licenses.py` (or the front end's own license check).

## Docs site

The user docs in `docs/` are also built into a static site with
[Zensical](https://zensical.org/) (MIT), configured in `mkdocs.yml`. It is in its own
`docs` dependency group, so `uv sync` doesn't install it:

```sh
uv run --group docs zensical serve   # preview at http://127.0.0.1:8000, rebuilds on save
uv run --group docs zensical build   # writes site/ (git-ignored)
```

Zensical needs `pathspec` (MPL-2.0), which is allowed as a build-only tool
(decision 20). Add new pages to `nav` in `mkdocs.yml`.

## Security audit

Maintainers check the locked dependencies for known vulnerabilities from time to time.
It is not part of CI, because it needs the network and its answer changes as new
advisories are published, not as the code changes. From the repository root:

```sh
uv run python scripts/security_audit.py --output security-audit.md
```

It needs uv, npm, and network access. It audits every package pinned in `uv.lock` and
`src/frontend/package-lock.json`, dev and build tools included, at the exact locked
version:

- Python: `pip-audit` (Apache-2.0), against the PyPI vulnerability feed. It runs at a
  pinned version through `uvx`, so it is not a project dependency.
- npm: `npm audit --package-lock-only`, against the GitHub Advisory Database. It reads
  only the lockfile, so you don't need to run `npm install` first.

The report lists each finding with its advisory ids, severity, and fix version, followed
by every package marked runtime or dev. It exits 0 when it finds nothing, 1 when it finds
advisories, and 2 when a tool could not run. The report is written in all three cases.
`security-audit*.md` in the repository root is git-ignored. To audit a pull request,
check out its branch and run the same command. Open an issue or a pull request for each
finding you act on.

## Pull requests

Work on a branch and open a pull request against `main`. Keep changes small; a maintainer
reviews every diff by hand.
