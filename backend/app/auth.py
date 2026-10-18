"""Who is calling. Supabase owns login; this process owns the workflow.

A request carries `Authorization: Bearer <supabase access token>`. We ask Supabase Auth
who that token is, then read `public.profiles.role` (Buyer, Supplier or Reviewer).
`X-Demo-Role` is not consulted. Tests replace `current_actor` and never reach this code.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.workflow import Actor

# Stored on public.profiles.role. Auditor is an older label and is not a workflow actor.
ROLES = {
    "Buyer": Actor.BUYER,
    "Supplier": Actor.SUPPLIER,
    "Reviewer": Actor.REVIEWER,
}

_PROFILE_SQL = text("SELECT CAST(role AS text) AS role FROM public.profiles WHERE id = :id")
_PROFILE_ACCOUNT_SQL = text("SELECT CAST(role AS text) AS role, name FROM public.profiles WHERE id = :id")

_NO_PROFILE = (
    "No ProofSettle profile for this account. "
    "If the row exists, Row Level Security on public.profiles is hiding it. Run supabase/auth.sql."
)


def actor_from_role(value: object) -> Actor:
    if not isinstance(value, str):
        raise HTTPException(403, "Profile role must be Buyer, Supplier or Reviewer")
    try:
        return ROLES[value]
    except KeyError as exc:
        raise HTTPException(403, "Profile role must be Buyer, Supplier or Reviewer") from exc


def bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(401, "Missing Authorization bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Missing Authorization bearer token")
    return token.strip()


def supabase_user_id(token: str) -> str:
    """The Auth user id (`sub`) for a live Supabase access token."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(503, "Supabase auth is not configured")
    url = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_anon_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise HTTPException(401, "Invalid or expired session") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "Could not reach Supabase auth") from exc
    user_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(user_id, str):
        raise HTTPException(401, "Invalid or expired session")
    try:
        UUID(user_id)
    except ValueError as exc:
        raise HTTPException(401, "Invalid or expired session") from exc
    return user_id


class Account:
    """One signed-in account. The role alone is not an account: every Buyer used to look the same."""

    def __init__(self, role: Actor, user_id: str | None = None, name: str | None = None) -> None:
        self.role = role
        self.user_id = user_id
        self.name = name


def _profile_from_rest(user_id: str, token: str) -> tuple[Actor, str | None]:
    """Role and name for this user, read as this user so another account's row is not returned.

    The publishable key is only the apikey. It is not sent as the bearer: that key can read
    every public.profiles row while row level security is off.
    """
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(503, "Could not read the user profile: Supabase auth is not configured")
    url = (
        settings.supabase_url.rstrip("/")
        + "/rest/v1/profiles?id=eq."
        + urllib.parse.quote(user_id)
        + "&select=id,role,name"
    )
    request = urllib.request.Request(
        url,
        headers={
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # HTTPError is a URLError. An empty or forbidden read is a missing profile, not an outage.
        raise HTTPException(403, _NO_PROFILE) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "Could not read the user profile") from exc
    if not isinstance(payload, list):
        raise HTTPException(403, _NO_PROFILE)
    rows = [row for row in payload if isinstance(row, dict) and row.get("id") == user_id]
    if len(rows) != 1:
        raise HTTPException(403, _NO_PROFILE)
    name = rows[0].get("name")
    return actor_from_role(rows[0].get("role")), name if isinstance(name, str) and name else None


def profile_role(db: Session, user_id: str, token: str | None = None) -> Actor:
    """Role for this auth user from public.profiles. Workflow tables are not in public."""
    try:
        row = db.execute(_PROFILE_SQL, {"id": user_id}).one_or_none()
    except SQLAlchemyError as exc:
        db.rollback()
        # SQLite has no public.profiles. Ask Supabase as this user, never as the anon key.
        if not token:
            raise HTTPException(503, "Could not read the user profile") from exc
        role, _name = _profile_from_rest(user_id, token)
        return role
    if row is None:
        raise HTTPException(403, "No ProofSettle profile for this account")
    return actor_from_role(row[0])


def load_account(db: Session, user_id: str, token: str) -> Account:
    """The account behind this access token. Another user's profile is not a source for it."""
    try:
        row = db.execute(_PROFILE_ACCOUNT_SQL, {"id": user_id}).one_or_none()
    except SQLAlchemyError:
        db.rollback()
        role, name = _profile_from_rest(user_id, token)
        return Account(role, user_id, name)
    if row is None:
        role, name = _profile_from_rest(user_id, token)
        return Account(role, user_id, name)
    name = row[1] if isinstance(row[1], str) and row[1] else None
    return Account(actor_from_role(row[0]), user_id, name)


_Db = Annotated[Session, Depends(get_db)]


def current_actor(db: _Db, authorization: Annotated[str | None, Header()] = None) -> Account:
    token = bearer_token(authorization)
    return load_account(db, supabase_user_id(token), token)
