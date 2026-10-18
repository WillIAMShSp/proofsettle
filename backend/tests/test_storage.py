"""Evidence stores: the local folder, and Supabase Storage over a faked network."""

import io
import json
import urllib.error

import pytest

from app.config import settings
from app.storage import LocalStore, StorageError, SupabaseStore, default_store

URL = "https://proj.supabase.co"


def test_local_store_round_trip_and_safety(tmp_path):
    store = LocalStore(tmp_path / "ev")
    store.put("ev_01.jpg", b"one", "image/jpeg")
    assert store.get("ev_01.jpg") == b"one"
    assert store.get("ev_02.jpg") is None
    with pytest.raises(FileExistsError):  # never overwrites a stored photo
        store.put("ev_01.jpg", b"other", "image/jpeg")
    for bad in ("../x.jpg", "ev_01.exe", "notes.txt", "ev_1.jpg/../../x"):
        assert store.get(bad) is None
        with pytest.raises(ValueError):
            store.put(bad, b"x", "image/jpeg")
    store.delete(["ev_01.jpg", "ev_09.jpg"])  # a missing one is fine
    assert store.get("ev_01.jpg") is None


class _Response:
    def __init__(self, body: bytes = b"{}"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def http_error(code, body):
    return urllib.error.HTTPError("u", code, "e", None, io.BytesIO(json.dumps(body).encode()))  # type: ignore[arg-type]


@pytest.fixture
def storage(monkeypatch):
    """Fake Supabase Storage keeping objects in a dict; returns (objects, requests)."""
    objects: dict[str, bytes] = {}
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        path = request.full_url.removeprefix(f"{URL}/storage/v1")
        if request.method == "POST" and path.startswith("/object/list/evidence"):
            return _Response(json.dumps([{"name": n} for n in sorted(objects)]).encode())
        if request.method == "POST" and path == "/bucket":
            raise http_error(409, {"error": "Duplicate", "message": "The resource already exists"})
        if path.startswith("/object/evidence/"):
            name = path.removeprefix("/object/evidence/")
            if request.method == "POST":
                if name in objects:
                    raise http_error(400, {"error": "Duplicate", "message": "The resource already exists"})
                objects[name] = request.data
                return _Response(b'{"Key": "evidence/' + name.encode() + b'"}')
            if request.method == "GET":
                if name not in objects:
                    raise http_error(400, {"statusCode": "404", "error": "not_found", "message": "Object not found"})
                return _Response(objects[name])
        if request.method == "DELETE" and path == "/object/evidence":
            for n in json.loads(request.data)["prefixes"]:
                objects.pop(n, None)
            return _Response(b"[]")
        raise AssertionError(f"unexpected {request.method} {path}")

    monkeypatch.setattr("app.storage.urllib.request.urlopen", urlopen)
    return objects, seen


def test_supabase_store_round_trip(storage):
    objects, seen = storage
    store = SupabaseStore(URL, "sb_secret_abc", "evidence")
    store.put("ev_01.jpg", b"jpeg bytes", "image/jpeg")
    assert objects == {"ev_01.jpg": b"jpeg bytes"}
    upload = seen[-1]
    assert upload.full_url == f"{URL}/storage/v1/object/evidence/ev_01.jpg"
    assert upload.get_header("Content-type") == "image/jpeg"
    assert upload.get_header("X-upsert") == "false"
    assert store.get("ev_01.jpg") == b"jpeg bytes"
    assert store.get("ev_02.jpg") is None  # Storage's 400 not_found is "missing"
    with pytest.raises(StorageError, match="already exists"):
        store.put("ev_01.jpg", b"other", "image/jpeg")
    store.put("ev_02.jpg", b"two", "image/jpeg")
    store.delete(["ev_01.jpg"])
    assert objects == {"ev_02.jpg": b"two"}
    store.clear()
    assert objects == {}
    assert store.ensure_bucket() is False  # already there


def test_a_new_secret_key_is_never_sent_as_a_bearer_token(storage):
    _, seen = storage
    SupabaseStore(URL, "sb_secret_abc", "evidence").get("ev_01.jpg")
    assert seen[-1].get_header("Apikey") == "sb_secret_abc"
    assert seen[-1].get_header("Authorization") is None
    SupabaseStore(URL, "eyJhbGciOi.legacy.jwt", "evidence").get("ev_01.jpg")
    assert seen[-1].get_header("Authorization") == "Bearer eyJhbGciOi.legacy.jwt"


def test_supabase_store_refuses_names_outside_the_pattern(storage):
    _, seen = storage
    store = SupabaseStore(URL, "sb_secret_abc", "evidence")
    assert store.get("../../secret") is None
    with pytest.raises(ValueError):
        store.put("x/../../y.jpg", b"", "image/jpeg")
    assert seen == []


def test_an_unreachable_storage_is_a_storage_error(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("app.storage.urllib.request.urlopen", urlopen)
    with pytest.raises(StorageError, match="reach"):
        SupabaseStore(URL, "sb_secret_abc", "evidence").get("ev_01.jpg")


def test_default_store_follows_the_secret_key(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evidence_dir", tmp_path)
    assert isinstance(default_store(), LocalStore)
    monkeypatch.setattr(settings, "supabase_secret_key", "sb_secret_abc")
    monkeypatch.setattr(settings, "supabase_url", URL)
    store = default_store()
    assert isinstance(store, SupabaseStore) and store.bucket == "evidence"


def test_the_photo_url_serves_the_stored_bytes(client, seeded):
    res = client.get("/evidence/ev_01/file")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.content == (seeded[1] / "ev_01.jpg").read_bytes()
    (seeded[1] / "ev_01.jpg").unlink()
    assert client.get("/evidence/ev_01/file").status_code == 404


def test_a_storage_outage_is_a_502(client):
    from app.main import app
    from app.routes import evidence_store

    class Down:
        def get(self, name):
            raise StorageError("Could not reach Supabase Storage: down")

    app.dependency_overrides[evidence_store] = lambda: Down()
    res = client.get("/evidence/ev_01/file")
    assert res.status_code == 502 and "Supabase Storage" in res.json()["detail"]
