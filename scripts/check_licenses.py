"""Fail if any installed Python distribution uses a license outside our allowlist.

AGENTS.md requires every dependency, including build and test tools, to use a
license on the ASF Category A list:
https://www.apache.org/legal/resolved.html#category-a

Usage (CI runs this after ``uv sync``)::

    uv run pip-licenses --from=mixed --format=json | uv run python scripts/check_licenses.py

The script reads pip-licenses JSON on stdin, so it never touches the network.

Pass ``--allow-build-only`` to also accept the packages in ``BUILD_ONLY``.
CI does that only for the all-groups check. The core install is checked
without it, so a ``BUILD_ONLY`` package that reaches the core install still
fails the build.
Adding a license to ``ALLOWED`` or a package to ``OVERRIDES`` needs a
maintainer's review.
"""

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import TextIO

# SPDX ids from the ASF Category A list that we expect to meet. Kept short on
# purpose; extend it only after checking the ASF list.
ALLOWED: frozenset[str] = frozenset(
    {
        "0BSD",
        "Apache-1.1",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSL-1.0",
        "HPND",
        "ISC",
        "MIT",
        "MIT-0",
        "MIT-CMU",
        "PostgreSQL",
        "PSF-2.0",
        "Python-2.0",
        "Zlib",
    }
)

# Trove classifier names (and other free-text values) that map to exactly one
# SPDX id. The generic "BSD License" classifier does not say which BSD variant;
# Shane accepts it for every package (decision 23 in
# docs/_prompts/01-decisions.md), so it maps to BSD-3-Clause.
ALIASES: Mapping[str, str] = {
    "Apache License 2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "ISC License (ISCL)": "ISC",
    "MIT License": "MIT",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Python Software Foundation License": "PSF-2.0",
    "zlib/libpng License": "Zlib",
}

# Packages whose metadata is ambiguous or missing, mapped to the SPDX id a
# maintainer confirmed from the package's own LICENSE file.
OVERRIDES: Mapping[str, str] = {
    "jinja2": "BSD-3-Clause",  # classifier says only "BSD License"; docs group (Zensical)
    "nodeenv": "BSD-3-Clause",  # classifier says only "BSD License"
}

# Build-time tools completely separate from application code may
# occasionally use MPL-2.0 (Shane, decision 20 in docs/_prompts/01-decisions.md).
# Each entry is one reviewed package name mapped to the reason it is needed.
# Entries are honored only with --allow-build-only, never for the core install.
BUILD_ONLY_LICENSES: frozenset[str] = frozenset({"MPL-2.0"})
BUILD_ONLY: Mapping[str, str] = {
    # Zensical (MIT), the docs site generator in the "docs" dependency group,
    # needs pathspec for file matching. It only builds the static docs site.
    "pathspec": "docs site build (Zensical), never imported by domus",
}

# The distribution being checked is our own project.
SELF: frozenset[str] = frozenset({"domus"})

_OR = re.compile(r"\s+OR\s+")
_AND = re.compile(r"\s+AND\s+")


def _normalize(term: str) -> str:
    term = term.strip()
    # Splitting "(MIT OR X)" leaves "(MIT" and "X)": drop parentheses that
    # have no partner, plus one enclosing pair, but keep balanced inner ones
    # such as the "(ISCL)" in "ISC License (ISCL)".
    if term.startswith("(") and term.count("(") > term.count(")"):
        term = term[1:].strip()
    if term.endswith(")") and term.count(")") > term.count("("):
        term = term[:-1].strip()
    if term.startswith("(") and term.endswith(")"):
        term = term[1:-1].strip()
    return ALIASES.get(term, term)


def is_allowed(license_text: str, allowed: frozenset[str] = ALLOWED) -> bool:
    """Return True if a license string is acceptable.

    Handles simple SPDX expressions (``A OR B``, ``A AND B``) and the
    ``"; "``-joined classifier lists pip-licenses prints. A choice (OR, or a
    classifier list) passes if any option is allowed; AND needs every part.
    Parenthesized sub-expressions are not supported and are rejected unless
    their flattened form passes.
    """
    text = license_text.strip()
    if not text or text.upper() == "UNKNOWN":
        return False
    choices = [c for part in text.split(";") for c in _OR.split(part)]
    for choice in choices:
        parts = [_normalize(p) for p in _AND.split(choice)]
        if parts and all(p in allowed for p in parts):
            return True
    return False


def find_violations(
    packages: Iterable[Mapping[str, str]],
    build_only: Mapping[str, str] | None = None,
) -> list[str]:
    """Return one message per package whose license is not allowed.

    ``build_only`` names reviewed build-time packages that may also use a
    license in ``BUILD_ONLY_LICENSES``. Pass it only for dev/build checks.
    """
    problems: list[str] = []
    for pkg in packages:
        name = pkg.get("Name", "")
        if name.lower() in SELF:
            continue
        key = name.lower()
        license_text = OVERRIDES.get(key, pkg.get("License", ""))
        allowed = ALLOWED | BUILD_ONLY_LICENSES if build_only and key in build_only else ALLOWED
        if not is_allowed(license_text, allowed):
            version = pkg.get("Version", "?")
            problems.append(f"{name} {version}: {license_text or 'no license metadata'}")
    return sorted(problems, key=str.lower)


def main(
    argv: Sequence[str] | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--allow-build-only",
        action="store_true",
        help="also accept the reviewed build-time packages in BUILD_ONLY",
    )
    args = parser.parse_args(argv)
    packages: list[dict[str, str]] = json.load(stdin)
    problems = find_violations(packages, BUILD_ONLY if args.allow_build_only else None)
    if problems:
        stdout.write("Dependencies with licenses outside the ASF Category A allowlist:\n")
        for problem in problems:
            stdout.write(f"  {problem}\n")
        return 1
    stdout.write(f"All {len(packages)} distributions use allowed licenses.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
