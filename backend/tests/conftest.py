from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import Caller, current_caller
from app.chain import set_chain
from app.config import settings
from app.db import get_db, make_engine
from app.main import app
from app.routes import evidence_store
from app.seed_db import reset_and_seed
from app.storage import LocalStore
from app.workflow import Actor


def test_caller(
    x_demo_role: Annotated[str | None, Header()] = None,
    x_demo_user: Annotated[str | None, Header()] = None,
    x_demo_email: Annotated[str | None, Header()] = None,
    x_demo_name: Annotated[str | None, Header()] = None,
) -> Caller:
    """Stand-in for Supabase login. Production `current_caller` never reads these headers.

    X-Demo-User / X-Demo-Email play the Supabase user id and email, X-Demo-Name the profile
    name; without a user or email the caller has no identity (like a dev login) and sees
    every shipment.
    """
    if x_demo_role not in {role.value for role in (Actor.BUYER, Actor.SUPPLIER, Actor.REVIEWER)}:
        raise HTTPException(400, "X-Demo-Role header must be Buyer, Supplier or Reviewer")
    email = x_demo_email.lower() if x_demo_email else None
    return Caller(Actor(x_demo_role), x_demo_user, email, x_demo_name)


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's backend/.env keys out of the tests: no real Gemini inspection, no
    real Supabase Storage. Tests that need either set it up themselves."""
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "supabase_secret_key", "")


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
    reset_and_seed(engine, LocalStore(files))
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
    app.dependency_overrides[evidence_store] = lambda: LocalStore(files)
    app.dependency_overrides[current_caller] = test_caller
    yield TestClient(app)
    app.dependency_overrides.clear()
