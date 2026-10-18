import io
import json
import urllib.error

import pytest
from fastapi import HTTPException

from app.auth import actor_from_role, current_actor, profile_role, profile_role_from_rest
from app.config import Settings, settings
from app.main import app
from app.workflow import Actor


def test_settings_read_supabase_names_from_an_env_file(tmp_path, monkeypatch):
    for key in (
        "PROOFSETTLE_SUPABASE_URL",
        "SUPABASE_URL",
        "VITE_SUPABASE_URL",
        "PROOFSETTLE_SUPABASE_ANON_KEY",
        "SUPABASE_ANON_KEY",
        "VITE_SUPABASE_ANON_KEY",
        "SUPABASE_PUBLISHABLE_KEY",
        "VITE_SUPABASE_PUBLISHABLE_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("VITE_SUPABASE_URL=https://example.supabase.co\nVITE_SUPABASE_PUBLISHABLE_KEY=publishable\n")
    loaded = Settings(_env_file=env_file)
    assert loaded.supabase_url == "https://example.supabase.co"
    assert loaded.supabase_anon_key == "publishable"


def test_reviewer_buyer_and_supplier_are_workflow_roles():
    assert actor_from_role("Buyer") is Actor.BUYER
    assert actor_from_role("Supplier") is Actor.SUPPLIER
    assert actor_from_role("Reviewer") is Actor.REVIEWER


@pytest.mark.parametrize("value", ["Auditor", "Admin", None, 1])
def test_other_profile_roles_are_rejected(value):
    with pytest.raises(HTTPException) as raised:
        actor_from_role(value)
    assert raised.value.status_code == 403


def test_profile_lookup_reads_public_profiles():
    seen: dict[str, object] = {}

    class _Rows:
        def one_or_none(self):
            return ("Reviewer",)

    class _Db:
        def execute(self, statement, params):
            seen["sql"] = str(statement)
            seen["params"] = params
            return _Rows()

        def rollback(self):
            raise AssertionError("rollback")

    assert profile_role(_Db(), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") is Actor.REVIEWER  # type: ignore[arg-type]
    assert "public.profiles" in str(seen["sql"])
    assert seen["params"] == {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}


def test_missing_profile_is_403():
    class _Rows:
        def one_or_none(self):
            return None

    class _Db:
        def execute(self, statement, params):
            return _Rows()

        def rollback(self):
            raise AssertionError("rollback")

    with pytest.raises(HTTPException) as raised:
        profile_role(_Db(), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")  # type: ignore[arg-type]
    assert raised.value.status_code == 403
    assert "profile" in raised.value.detail.lower()


def test_demo_role_header_is_not_a_session(client):
    app.dependency_overrides.pop(current_actor)
    response = client.get("/shipments", headers={"X-Demo-Role": "Buyer"})
    assert response.status_code == 401
    assert "bearer" in response.json()["detail"].lower()


def test_missing_token_is_401(client):
    app.dependency_overrides.pop(current_actor)
    assert client.get("/shipments").status_code == 401


def test_auth_not_configured_is_503(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_anon_key", "")
    response = client.get("/shipments", headers={"Authorization": "Bearer token"})
    assert response.status_code == 503


def test_rejected_supabase_token_is_401(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")

    def reject(request, timeout=10):
        raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", None, io.BytesIO(b"{}"))

    monkeypatch.setattr("app.auth.urllib.request.urlopen", reject)
    response = client.get(
        "/shipments",
        headers={"Authorization": "Bearer not-a-session", "X-Demo-Role": "Reviewer"},
    )
    assert response.status_code == 401


def test_supabase_user_id_must_be_a_uuid(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"id": "not-a-uuid"}).encode()

    monkeypatch.setattr("app.auth.urllib.request.urlopen", lambda request, timeout=10: _Response())
    response = client.get("/shipments", headers={"Authorization": "Bearer token"})
    assert response.status_code == 401


_USER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class _Body:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


def _configured(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "sb_publishable_test")


def test_postgrest_profile_role_maps_reviewer(monkeypatch):
    _configured(monkeypatch)
    seen: dict[str, str] = {}

    def fake(request, timeout=10):
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["apikey"] = request.get_header("Apikey")
        return _Body(json.dumps([{"role": "Reviewer"}]).encode())

    monkeypatch.setattr("app.auth.urllib.request.urlopen", fake)
    assert profile_role_from_rest("user-jwt", _USER) is Actor.REVIEWER
    assert f"/rest/v1/profiles?id=eq.{_USER}&select=role" in seen["url"]
    assert seen["authorization"] == "Bearer user-jwt"
    assert seen["apikey"] == "sb_publishable_test"


def test_postgrest_empty_profile_is_hidden_or_missing(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr("app.auth.urllib.request.urlopen", lambda request, timeout=10: _Body(b"[]"))
    assert profile_role_from_rest("user-jwt", _USER) is None


def test_postgrest_outage_is_503(monkeypatch):
    _configured(monkeypatch)

    def down(request, timeout=10):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("app.auth.urllib.request.urlopen", down)
    with pytest.raises(HTTPException) as raised:
        profile_role_from_rest("user-jwt", _USER)
    assert raised.value.status_code == 503


def test_rest_role_authorizes_without_the_workflow_database(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    _configured(monkeypatch)

    def fake(request, timeout=10):
        if request.full_url.endswith("/auth/v1/user"):
            return _Body(json.dumps({"id": _USER}).encode())
        return _Body(json.dumps([{"role": "Reviewer"}]).encode())

    monkeypatch.setattr("app.auth.urllib.request.urlopen", fake)
    response = client.get("/shipments", headers={"Authorization": "Bearer user-jwt", "X-Demo-Role": "Buyer"})
    assert response.status_code == 200


def test_hidden_profile_names_row_level_security(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    _configured(monkeypatch)

    def fake(request, timeout=10):
        if request.full_url.endswith("/auth/v1/user"):
            return _Body(json.dumps({"id": _USER}).encode())
        return _Body(b"[]")

    monkeypatch.setattr("app.auth.urllib.request.urlopen", fake)
    response = client.get("/shipments", headers={"Authorization": "Bearer user-jwt"})
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "Row Level Security" in detail
    assert "public.profiles" in detail
    assert "supabase/auth.sql" in detail
