"""Write the API's OpenAPI document for the front end's generated types.

The front end builds its typed client from ``src/frontend/openapi.json``, and
``tests/test_openapi_snapshot.py`` fails when that file no longer matches the
API. After changing an endpoint or schema, run::

    uv run python scripts/export_openapi.py
    (cd src/frontend && npm run api:types)

The app is built against a throwaway SQLite database, so this never touches
real data or the network.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from domus.api.app import create_app
from domus.config import Settings
from domus.db import make_engine

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "src" / "frontend" / "openapi.json"


def openapi_document() -> dict[str, Any]:
    """Return the OpenAPI document the running app would serve."""
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(f"sqlite:///{Path(tmp) / 'openapi.sqlite'}")
        try:
            return create_app(Settings(data_dir=Path(tmp)), engine).openapi()
        finally:
            engine.dispose()


def render(document: dict[str, Any]) -> str:
    """Serialize the document the same way every time, so diffs stay small."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT
    output.write_text(render(openapi_document()), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
