"""Postgres keeps workflow tables out of Supabase's public schema. SQLite has no schemas."""

from app.db import POSTGRES_SCHEMA, make_engine


def test_postgres_targets_its_own_schema():
    engine = make_engine("postgresql+psycopg://user:pass@localhost/postgres")
    try:
        assert engine.get_execution_options()["schema_translate_map"] == {None: POSTGRES_SCHEMA}
        assert POSTGRES_SCHEMA != "public"
    finally:
        engine.dispose()


def test_sqlite_uses_plain_table_names():
    engine = make_engine("sqlite://")
    try:
        assert "schema_translate_map" not in engine.get_execution_options()
    finally:
        engine.dispose()
