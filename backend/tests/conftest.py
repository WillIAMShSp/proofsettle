from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import current_actor
from app.chain import set_chain
from app.db import get_db, make_engine
from app.main import app
from app.routes import evidence_dir
from app.seed_db import reset_and_seed
from app.workflow import Actor


def test_actor(x_demo_role: Annotated[str | None, Header()] = None) -> Actor:
    """Stand-in for Supabase login. Production `current_actor` never reads this header."""
    if x_demo_role not in {role.value for role in (Actor.BUYER, Actor.SUPPLIER, Actor.REVIEWER)}:
        raise HTTPException(400, "X-Demo-Role header must be Buyer, Supplier or Reviewer")
    return Actor(x_demo_role)


@pytest.fixture(autouse=True)
def no_configured_chain() -> Iterator[None]:
    """Keep a developer's backend/.env (a live Solana RPC) out of the tests. Tests that need a
    chain install one with set_chain, as test_chain_live does."""
    set_chain(None)
    yield
    set_chain(None)


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
    app.dependency_overrides[current_actor] = test_actor
    yield TestClient(app)
    app.dependency_overrides.clear()
