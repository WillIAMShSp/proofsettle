"""Who is calling. Supabase owns login; this process owns the workflow.

A request carries `Authorization: Bearer <supabase access token>`. We ask Supabase Auth
who that token is, then read `public.profiles.role` (Buyer, Supplier or Reviewer).
PostgREST is asked as the user, so row level security on `public.profiles` applies.
Direct SQL on this process's database is the fallback: a superuser sees the row even
when RLS hides it from PostgREST, and SQLite has no `public.profiles` table.
`user_metadata` is not a role source. `X-Demo-Role` is not consulted.
Tests replace `current_actor` and never reach this code.
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

_NO_PROFILE = (
    "No ProofSettle profile for this account. PostgREST returned no public.profiles row. "
    "That is a missing profile, or Row Level Security on public.profiles hiding the row. "
    "Run supabase/auth.sql in the Supabase SQL editor, then sign in again."
)

_NO_PROFILE_SQL = (
    "No ProofSettle profile for this account. PostgREST returned no public.profiles row "
    "(missing profile, or Row Level Security on public.profiles). "
    "The workflow database also cannot read public.profiles. Run supabase/auth.sql in the Supabase SQL editor."
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


def profile_role_from_rest(token: str, user_id: str) -> Actor | None:
    """Role from PostgREST as this user. None when the row is absent or hidden by RLS.

    Raises 503 when PostgREST cannot be reached, and 403 when the stored role is not
    Buyer, Supplier or Reviewer. The user's access token is the bearer; the publishable
    key is only the apikey header.
    """
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(503, "Supabase auth is not configured")
    url = (
        settings.supabase_url.rstrip("/")
        + "/rest/v1/profiles?id=eq."
        + urllib.parse.quote(user_id)
        + "&select=role"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": settings.supabase_anon_key,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "Could not reach Supabase profiles") from exc
    if not isinstance(payload, list) or not payload:
        return None
    row = payload[0]
    if not isinstance(row, dict):
        return None
    return actor_from_role(row.get("role"))


def profile_role(db: Session, user_id: str) -> Actor:
    """Role for this auth user from public.profiles. Workflow tables are not in public."""
    try:
        row = db.execute(_PROFILE_SQL, {"id": user_id}).one_or_none()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(503, "Could not read the user profile") from exc
    if row is None:
        raise HTTPException(403, "No ProofSettle profile for this account")
    return actor_from_role(row[0])


_Db = Annotated[Session, Depends(get_db)]


def current_actor(db: _Db, authorization: Annotated[str | None, Header()] = None) -> Actor:
    token = bearer_token(authorization)
    user_id = supabase_user_id(token)
    try:
        role = profile_role_from_rest(token, user_id)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return profile_role(db, user_id)
    if role is not None:
        return role
    try:
        return profile_role(db, user_id)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(403, _NO_PROFILE) from exc
        raise HTTPException(403, _NO_PROFILE_SQL) from exc
