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
GitHub Actions workflow. The license check fails CI on anything else.

## Pull requests

Work on a branch and open a pull request against `main`. Keep changes small; a maintainer
reviews every diff by hand.
