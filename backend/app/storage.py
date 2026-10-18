"""Where evidence photos live: a folder on this machine, or a private Supabase Storage bucket.

The database holds each photo's SHA-256 and `file_name`; the bytes are here. Every reader
(the photo URL, AI inspection, "Verify hashes") re-hashes what it gets back, so a store only
has to keep bytes, not vouch for them.

SupabaseStore is used when the backend has the project's secret key
(PROOFSETTLE_SUPABASE_SECRET_KEY, server-side only). It talks to the Storage REST API with
urllib, like app.auth talks to Supabase Auth. The bucket is private: the browser never
reads it directly, only through GET /evidence/{id}/file.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

# Stored names are "<evidence id>.<ext>", e.g. "ev_05.jpg". Anything else is refused, so a
# name can never point outside the folder or the bucket.
_NAME = re.compile(r"^ev_\d+\.(jpg|png)$")


class StorageError(Exception):
    """The store could not be reached or refused the request."""


class EvidenceStore(Protocol):
    def put(self, name: str, data: bytes, content_type: str) -> None:
        """Store a new photo. Refuses to overwrite an existing one."""
        ...

    def get(self, name: str) -> bytes | None:
        """The photo's bytes, or None if there is none by that name."""
        ...

    def delete(self, names: Iterable[str]) -> None:
        """Remove these photos; missing ones are ignored."""
        ...

    def clear(self) -> None:
        """Remove every evidence photo (demo reset)."""
        ...


def _check(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError(f"not an evidence file name: {name!r}")
    return name


class LocalStore:
    """Photos as files in one folder (the default, and the tests' store)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, name: str, data: bytes, content_type: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / _check(name)).open("xb") as f:  # "x": never overwrite
            f.write(data)

    def get(self, name: str) -> bytes | None:
        if not _NAME.fullmatch(name):
            return None
        path = self.root / name
        return path.read_bytes() if path.is_file() else None

    def delete(self, names: Iterable[str]) -> None:
        for name in names:
            (self.root / _check(name)).unlink(missing_ok=True)

    def clear(self) -> None:
        for path in self.root.glob("ev_*") if self.root.exists() else ():
            path.unlink()


class SupabaseStore:
    """Photos as objects in a private Supabase Storage bucket."""

    def __init__(self, project_url: str, secret_key: str, bucket: str, *, timeout: float = 30.0) -> None:
        if not project_url or not secret_key or not bucket:
            raise ValueError("SupabaseStore needs the project URL, the secret key and a bucket")
        self.base = project_url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.timeout = timeout
        self.headers = {"apikey": secret_key}
        # New-style keys (sb_secret_...) are not JWTs: Supabase rejects them as a Bearer token,
        # so they go only in `apikey`. A legacy service_role JWT goes in both.
        if not secret_key.startswith("sb_"):
            self.headers["Authorization"] = f"Bearer {secret_key}"

    def _object_url(self, name: str) -> str:
        return f"{self.base}/object/{urllib.parse.quote(self.bucket)}/{urllib.parse.quote(_check(name))}"

    def _send(self, method: str, url: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
        request = urllib.request.Request(url, data=body, headers=self.headers | (headers or {}), method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise StorageError(f"Could not reach Supabase Storage: {e}") from e

    def _json(self, method: str, url: str, payload: object) -> bytes:
        return self._send(method, url, json.dumps(payload).encode(), {"Content-Type": "application/json"})

    def put(self, name: str, data: bytes, content_type: str) -> None:
        try:
            self._send("POST", self._object_url(name), data, {"Content-Type": content_type, "x-upsert": "false"})
        except urllib.error.HTTPError as e:
            raise StorageError(f"Supabase Storage refused {name}: {_detail(e)}") from e

    def get(self, name: str) -> bytes | None:
        if not _NAME.fullmatch(name):
            return None
        try:
            return self._send("GET", self._object_url(name))
        except urllib.error.HTTPError as e:
            # Storage answers a missing object with 400 or 404 ({"error": "not_found"}).
            if e.code in (400, 404):
                return None
            raise StorageError(f"Supabase Storage refused {name}: {_detail(e)}") from e

    def delete(self, names: Iterable[str]) -> None:
        prefixes = [_check(n) for n in names]
        if not prefixes:
            return
        try:
            self._json("DELETE", f"{self.base}/object/{urllib.parse.quote(self.bucket)}", {"prefixes": prefixes})
        except urllib.error.HTTPError as e:
            raise StorageError(f"Supabase Storage refused the delete: {_detail(e)}") from e

    def list_names(self) -> list[str]:
        names: list[str] = []
        while True:
            try:
                raw = self._json(
                    "POST",
                    f"{self.base}/object/list/{urllib.parse.quote(self.bucket)}",
                    {"prefix": "", "limit": 1000, "offset": len(names)},
                )
            except urllib.error.HTTPError as e:
                raise StorageError(f"Supabase Storage refused the listing: {_detail(e)}") from e
            page = [o["name"] for o in json.loads(raw) if isinstance(o, dict) and isinstance(o.get("name"), str)]
            names += page
            if len(page) < 1000:
                return names

    def clear(self) -> None:
        self.delete([n for n in self.list_names() if _NAME.fullmatch(n)])

    def ensure_bucket(self) -> bool:
        """Create the bucket, private, if it doesn't exist. True if it was created."""
        try:
            self._json("POST", f"{self.base}/bucket", {"id": self.bucket, "name": self.bucket, "public": False})
            return True
        except urllib.error.HTTPError as e:
            detail = _detail(e)
            if e.code == 409 or "already exists" in detail.lower() or "duplicate" in detail.lower():
                return False
            raise StorageError(f"Could not create bucket {self.bucket!r}: {detail}") from e


def default_store() -> EvidenceStore:
    """Supabase Storage when the backend has the secret key, else the local folder."""
    from app.config import settings

    if settings.supabase_secret_key:
        return SupabaseStore(settings.supabase_url, settings.supabase_secret_key, settings.evidence_bucket)
    return LocalStore(settings.evidence_dir)


def _detail(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode(errors="replace"))
        return str(body.get("message") or body.get("error") or body) if isinstance(body, dict) else str(body)
    except (OSError, ValueError):
        return f"HTTP {e.code}"
