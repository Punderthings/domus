"""Fail if any installed Python distribution uses a license outside our allowlist.

AGENTS.md requires every dependency, including build and test tools, to use a
license on the ASF Category A list:
https://www.apache.org/legal/resolved.html#category-a

Usage (CI runs this after ``uv sync``)::

    uv run pip-licenses --from=mixed --format=json | uv run python scripts/check_licenses.py

The script reads pip-licenses JSON on stdin, so it never touches the network.
Adding a license to ``ALLOWED`` or a package to ``OVERRIDES`` needs a
maintainer's review.
"""

import json
import re
import sys
from collections.abc import Iterable, Mapping
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
# SPDX id. "BSD License" is deliberately absent: it does not say which BSD
# variant, so such packages need a reviewed entry in OVERRIDES.
ALIASES: Mapping[str, str] = {
    "Apache License 2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "ISC License (ISCL)": "ISC",
    "MIT License": "MIT",
    "Python Software Foundation License": "PSF-2.0",
    "zlib/libpng License": "Zlib",
}

# Packages whose metadata is ambiguous or missing, mapped to the SPDX id a
# maintainer confirmed from the package's own LICENSE file.
OVERRIDES: Mapping[str, str] = {
    "nodeenv": "BSD-3-Clause",  # classifier says only "BSD License"
}

# The distribution being checked is our own project.
SELF: frozenset[str] = frozenset({"domus"})

_OR = re.compile(r"\s+OR\s+")
_AND = re.compile(r"\s+AND\s+")


def _normalize(term: str) -> str:
    term = term.strip().strip("()").strip()
    return ALIASES.get(term, term)


def is_allowed(license_text: str) -> bool:
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
        if parts and all(p in ALLOWED for p in parts):
            return True
    return False


def find_violations(packages: Iterable[Mapping[str, str]]) -> list[str]:
    """Return one message per package whose license is not allowed."""
    problems: list[str] = []
    for pkg in packages:
        name = pkg.get("Name", "")
        if name.lower() in SELF:
            continue
        license_text = OVERRIDES.get(name.lower(), pkg.get("License", ""))
        if not is_allowed(license_text):
            version = pkg.get("Version", "?")
            problems.append(f"{name} {version}: {license_text or 'no license metadata'}")
    return sorted(problems, key=str.lower)


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    packages: list[dict[str, str]] = json.load(stdin)
    problems = find_violations(packages)
    if problems:
        stdout.write("Dependencies with licenses outside the ASF Category A allowlist:\n")
        for problem in problems:
            stdout.write(f"  {problem}\n")
        return 1
    stdout.write(f"All {len(packages)} distributions use allowed licenses.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
