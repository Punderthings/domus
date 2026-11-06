"""Shared fixtures. Tests never use the network (AGENTS.md)."""

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from domus.db import make_engine, make_session_factory
from domus.migrate import upgrade


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine]:
    """A fresh, fully migrated SQLite database in a temp directory."""
    eng = make_engine(f"sqlite:///{tmp_path / 'test.sqlite'}")
    upgrade(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session]:
    factory = make_session_factory(engine)
    with factory() as s:
        yield s
