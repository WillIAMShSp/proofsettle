"""Who is calling. Supabase owns login; this process owns the workflow.

A request carries `Authorization: Bearer <supabase access token>`. We ask Supabase Auth
who that token is, then read `public.profiles.role` (Buyer, Supplier or Reviewer): with SQL
when our database is Supabase Postgres, otherwise through Supabase's REST API as that user.
`X-Demo-Role` is not consulted. Tests replace `current_actor` and never reach this code.

Local dev only: with `PROOFSETTLE_DEV_AUTH=true`, a request without a bearer token may name
its role in `X-Dev-Role` instead. Anyone who can reach the server can then act as any role,
so never turn it on for a deployed backend.
"""

import json
import urllib.error
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


def _supabase_get(path: str, token: str) -> object:
    """GET a Supabase endpoint as the token's user. HTTP errors are left to the caller."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(503, "Supabase auth is not configured")
    request = urllib.request.Request(
        settings.supabase_url.rstrip("/") + path,
        headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_anon_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # Supabase answers a bad `apikey` with 401 too; that is our config, not the session.
        body = exc.read().decode(errors="replace") if exc.fp else ""
        if "Invalid API key" in body:
            raise HTTPException(
                503, "Supabase rejected the backend's API key (check SUPABASE_PUBLISHABLE_KEY)"
            ) from exc
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "Could not reach Supabase auth") from exc


def supabase_user_id(token: str) -> str:
    """The Auth user id (`sub`) for a live Supabase access token."""
    try:
        payload = _supabase_get("/auth/v1/user", token)
    except urllib.error.HTTPError as exc:
        raise HTTPException(401, "Invalid or expired session") from exc
    user_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(user_id, str):
        raise HTTPException(401, "Invalid or expired session")
    try:
        UUID(user_id)
    except ValueError as exc:
        raise HTTPException(401, "Invalid or expired session") from exc
    return user_id


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


def supabase_profile_role(token: str, user_id: str) -> Actor:
    """Role from public.profiles via Supabase's REST API, as the user (RLS: own row).

    For a local SQLite database, which has no `public.profiles` to query.
    """
    try:
        rows = _supabase_get(f"/rest/v1/profiles?select=role&id=eq.{user_id}", token)
    except urllib.error.HTTPError as exc:
        raise HTTPException(503, "Could not read the user profile") from exc
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise HTTPException(403, "No ProofSettle profile for this account")
    return actor_from_role(rows[0].get("role"))


_Db = Annotated[Session, Depends(get_db)]


def current_actor(
    db: _Db,
    authorization: Annotated[str | None, Header()] = None,
    x_dev_role: Annotated[str | None, Header()] = None,
) -> Actor:
    if settings.dev_auth and authorization is None and x_dev_role is not None:
        return actor_from_role(x_dev_role)
    token = bearer_token(authorization)
    user_id = supabase_user_id(token)
    # On Supabase Postgres the profile is in the same database; locally it is only in Supabase.
    if db.get_bind().dialect.name == "postgresql":
        return profile_role(db, user_id)
    return supabase_profile_role(token, user_id)
