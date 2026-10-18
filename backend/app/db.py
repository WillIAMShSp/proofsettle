from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.schema import CreateSchema

from app.config import settings

# On Postgres our tables live in their own schema. Supabase's `public` schema already has
# Lovable-generated tables with the same names (shipments, agreements, evidence, ...) and a
# different shape; we never read or write those. SQLite has no schemas and uses plain names.
POSTGRES_SCHEMA = "proofsettle"


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    # SQLite connections are thread-bound by default; FastAPI runs sync routes in a threadpool.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if engine.dialect.name == "postgresql":
        # Rendered into every statement (DDL included), so it works through any pooler.
        engine = engine.execution_options(schema_translate_map={None: POSTGRES_SCHEMA})
    return engine


def create_tables(engine: Engine) -> None:
    import app.models  # noqa: F401  (registers the tables on Base.metadata)

    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(CreateSchema(POSTGRES_SCHEMA, if_not_exists=True))
        Base.metadata.create_all(conn)


def drop_tables(engine: Engine) -> None:
    import app.models  # noqa: F401

    with engine.begin() as conn:
        Base.metadata.drop_all(conn)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
