import io
import json
import urllib.error

import pytest
from fastapi import HTTPException

from app.auth import actor_from_role, current_actor, profile_role
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


def test_dev_role_header_needs_dev_auth(client):
    app.dependency_overrides.pop(current_actor)
    assert client.get("/shipments", headers={"X-Dev-Role": "Buyer"}).status_code == 401


def test_dev_role_header_with_dev_auth(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    monkeypatch.setattr(settings, "dev_auth", True)
    assert client.get("/shipments", headers={"X-Dev-Role": "Buyer"}).status_code == 200
    assert client.get("/shipments", headers={"X-Dev-Role": "Auditor"}).status_code == 403


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


def _fake_supabase(monkeypatch, routes):
    """Answer Supabase GETs by path prefix; record each request."""
    seen = []

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def urlopen(request, timeout=10):
        seen.append(request)
        path = request.full_url.removeprefix("https://example.supabase.co")
        for prefix, answer in routes.items():
            if path.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return _Response(answer)
        raise AssertionError(f"unexpected Supabase call {path}")

    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    monkeypatch.setattr("app.auth.urllib.request.urlopen", urlopen)
    return seen


USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_sqlite_reads_the_profile_through_supabase_rest(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    seen = _fake_supabase(
        monkeypatch,
        {"/auth/v1/user": {"id": USER_ID}, "/rest/v1/profiles": [{"role": "Supplier"}]},
    )
    response = client.get("/shipments", headers={"Authorization": "Bearer session-token"})
    assert response.status_code == 200
    profile_request = seen[1]
    assert profile_request.full_url.endswith(f"/rest/v1/profiles?select=role&id=eq.{USER_ID}")
    assert profile_request.get_header("Authorization") == "Bearer session-token"


def test_sqlite_without_a_profile_row_is_403(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    _fake_supabase(monkeypatch, {"/auth/v1/user": {"id": USER_ID}, "/rest/v1/profiles": []})
    response = client.get("/shipments", headers={"Authorization": "Bearer session-token"})
    assert response.status_code == 403


def test_rejected_api_key_is_a_config_error_not_a_bad_session(client, monkeypatch):
    app.dependency_overrides.pop(current_actor)
    bad_key = urllib.error.HTTPError(
        "https://example.supabase.co/auth/v1/user",
        401,
        "unauthorized",
        None,  # type: ignore[arg-type]
        io.BytesIO(b'{"message":"Invalid API key"}'),
    )
    _fake_supabase(monkeypatch, {"/auth/v1/user": bad_key})
    response = client.get("/shipments", headers={"Authorization": "Bearer session-token"})
    assert response.status_code == 503
    assert "API key" in response.json()["detail"]
