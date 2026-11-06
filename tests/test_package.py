"""Smoke tests for the installed package."""

import re

import domus


def test_version_is_a_release_string() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+([.\-+].*)?", domus.__version__)
