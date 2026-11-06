"""The front end's committed openapi.json must match the API."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_openapi", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eo = _load()


def test_committed_openapi_matches_the_api() -> None:
    committed = eo.DEFAULT_OUTPUT.read_text(encoding="utf-8")
    current = eo.render(eo.openapi_document())
    assert json.loads(committed) == json.loads(current), (
        "src/frontend/openapi.json is out of date. Run "
        "`uv run python scripts/export_openapi.py` and then "
        "`npm run api:types` in src/frontend."
    )
    assert committed == current, "Re-run scripts/export_openapi.py to normalize formatting."


def test_main_writes_to_a_given_path(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    assert eo.main(["export_openapi.py", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["openapi"].startswith("3.")
    assert "/api/v1/auth/me" in document["paths"]
