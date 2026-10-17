from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db, make_engine
from app.main import app
from app.routes import evidence_dir
from app.seed_db import reset_and_seed


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[tuple[Engine, Path]]:
    """A fresh SQLite database (and evidence folder) with the three demo shipments."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    files = tmp_path / "evidence"
    reset_and_seed(engine, files)
    yield engine, files
    engine.dispose()


@pytest.fixture
def db(seeded: tuple[Engine, Path]) -> Iterator[Session]:
    with sessionmaker(bind=seeded[0], autoflush=False, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def client(seeded: tuple[Engine, Path]) -> Iterator[TestClient]:
    engine, files = seeded
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[evidence_dir] = lambda: files
    yield TestClient(app)
    app.dependency_overrides.clear()
