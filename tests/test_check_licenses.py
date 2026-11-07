"""Tests for scripts/check_licenses.py."""

import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_licenses.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_licenses", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cl = _load()


@pytest.mark.parametrize(
    "text",
    [
        "MIT",
        "MIT License",
        "Apache-2.0",
        "Apache Software License",
        "BSD-3-Clause",
        "PSF-2.0",
        "Python Software Foundation License",
        "Apache-2.0 OR BSD-2-Clause",
        "MIT AND BSD-3-Clause",
        "(MIT OR GPL-3.0-only)",
        "GPL-3.0-only OR MIT",
        "MIT License; Mozilla Public License 2.0 (MPL 2.0)",
        "ISC License (ISCL)",
        "zlib/libpng License",
    ],
)
def test_allowed(text: str) -> None:
    assert cl.is_allowed(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "UNKNOWN",
        "LGPL-3.0-or-later",
        "GNU Lesser General Public License v3 (LGPLv3)",
        "GPL-2.0-only",
        "AGPL-3.0-only",
        "MPL-2.0",
        "Mozilla Public License 2.0 (MPL 2.0)",
        "MIT AND LGPL-2.1-only",
        "Unlicense",
        "Hippocratic-2.1",
    ],
)
def test_rejected(text: str) -> None:
    assert not cl.is_allowed(text)


def test_generic_bsd_classifier_is_accepted() -> None:
    """Decision 23: "BSD License" without a variant is accepted for any package."""
    assert cl.is_allowed("BSD License")
    assert (
        cl.find_violations([{"Name": "pg8000", "Version": "1.31.6", "License": "BSD License"}])
        == []
    )


def test_find_violations_uses_overrides_and_skips_self() -> None:
    packages = [
        {"Name": "domus", "Version": "0.0.1", "License": "UNKNOWN"},
        {"Name": "nodeenv", "Version": "1.0", "License": "BSD License"},
        {"Name": "ok", "Version": "1.0", "License": "MIT"},
        {"Name": "Bad", "Version": "2.0", "License": "LGPL-3.0-only"},
        {"Name": "empty", "Version": "3.0", "License": ""},
    ]
    assert cl.find_violations(packages) == [
        "Bad 2.0: LGPL-3.0-only",
        "empty 3.0: no license metadata",
    ]


def test_main_exit_codes() -> None:
    good = io.StringIO(json.dumps([{"Name": "a", "Version": "1", "License": "MIT"}]))
    out = io.StringIO()
    assert cl.main([], good, out) == 0
    assert "All 1 distributions" in out.getvalue()

    bad = io.StringIO(json.dumps([{"Name": "b", "Version": "1", "License": "GPL-3.0-only"}]))
    out = io.StringIO()
    assert cl.main([], bad, out) == 1
    assert "b 1: GPL-3.0-only" in out.getvalue()


_MPL_TOOL = {"Name": "Some-Tool", "Version": "1.0", "License": "MPL-2.0"}


def test_build_only_exception_applies_only_to_listed_packages() -> None:
    build_only = {"some-tool": "build-time only, reviewed"}
    assert cl.find_violations([_MPL_TOOL], build_only) == []
    assert cl.find_violations([_MPL_TOOL]) == ["Some-Tool 1.0: MPL-2.0"]
    other = {"Name": "other", "Version": "2.0", "License": "MPL-2.0"}
    assert cl.find_violations([other], build_only) == ["other 2.0: MPL-2.0"]


def test_build_only_exception_never_allows_lgpl() -> None:
    lgpl = {"Name": "some-tool", "Version": "1.0", "License": "LGPL-3.0-only"}
    assert cl.find_violations([lgpl], {"some-tool": "reviewed"}) == ["some-tool 1.0: LGPL-3.0-only"]


def test_main_build_only_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cl, "BUILD_ONLY", {"some-tool": "reviewed"})
    data = json.dumps([_MPL_TOOL])
    assert cl.main([], io.StringIO(data), io.StringIO()) == 1
    assert cl.main(["--allow-build-only"], io.StringIO(data), io.StringIO()) == 0
