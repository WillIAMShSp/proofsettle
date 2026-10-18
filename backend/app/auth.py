"""Who is calling. Supabase owns login; this process owns the workflow.

A request carries `Authorization: Bearer <supabase access token>`. We ask Supabase Auth
who that token is, then read `public.profiles.role` (Buyer, Supplier or Reviewer): with SQL
when our database is Supabase Postgres, otherwise through Supabase's REST API as that user.
`X-Demo-Role` is not consulted. Tests replace `current_caller` and never reach this code.

`current_caller` is the role plus who the caller is (Supabase user id and email), which
app.access uses to decide which shipments they can see. `current_actor` is just the role.

Local dev only: with `PROOFSETTLE_DEV_AUTH=true`, a request without a bearer token may name
its role in `X-Dev-Role` instead. Anyone who can reach the server can then act as any role,
so never turn it on for a deployed backend.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
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

_PROFILE_SQL = text("SELECT CAST(role AS text) AS role, name FROM public.profiles WHERE id = :id")


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


@dataclass(frozen=True)
class Profile:
    """The caller's row in public.profiles."""

    actor: Actor
    name: str | None


def _profile(role: object, name: object) -> Profile:
    clean = name.strip() if isinstance(name, str) else ""
    return Profile(actor_from_role(role), clean[:200] or None)


@dataclass(frozen=True)
class Caller:
    actor: Actor
    # The Supabase Auth user, and their email lowercased. Both None for a dev login, which
    # has a role but no identity.
    user_id: str | None = None
    email: str | None = None
    # public.profiles.name, shown as the buyer of shipments this account creates.
    name: str | None = None


def supabase_user(token: str) -> tuple[str, str | None]:
    """The Auth user id (`sub`) and lowercased email for a live Supabase access token."""
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
    email = payload.get("email")
    return user_id, email.strip().lower() if isinstance(email, str) and email.strip() else None


def read_profile(db: Session, user_id: str) -> Profile:
    """This auth user's public.profiles row. Workflow tables are not in public."""
    try:
        row = db.execute(_PROFILE_SQL, {"id": user_id}).one_or_none()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(503, "Could not read the user profile") from exc
    if row is None:
        raise HTTPException(403, "No ProofSettle profile for this account")
    return _profile(row[0], row[1])


def supabase_profile(token: str, user_id: str) -> Profile:
    """The public.profiles row via Supabase's REST API, as the user (RLS: own row).

    For a local SQLite database, which has no `public.profiles` to query.
    """
    try:
        rows = _supabase_get(f"/rest/v1/profiles?select=role,name&id=eq.{user_id}", token)
    except urllib.error.HTTPError as exc:
        raise HTTPException(503, "Could not read the user profile") from exc
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise HTTPException(403, "No ProofSettle profile for this account")
    return _profile(rows[0].get("role"), rows[0].get("name"))


_Db = Annotated[Session, Depends(get_db)]


def current_caller(
    db: _Db,
    authorization: Annotated[str | None, Header()] = None,
    x_dev_role: Annotated[str | None, Header()] = None,
) -> Caller:
    if settings.dev_auth and authorization is None and x_dev_role is not None:
        return Caller(actor_from_role(x_dev_role))
    token = bearer_token(authorization)
    user_id, email = supabase_user(token)
    # On Supabase Postgres the profile is in the same database; locally it is only in Supabase.
    if db.get_bind().dialect.name == "postgresql":
        profile = read_profile(db, user_id)
    else:
        profile = supabase_profile(token, user_id)
    return Caller(profile.actor, user_id, email, profile.name)


def current_actor(caller: Annotated[Caller, Depends(current_caller)]) -> Actor:
    # FastAPI caches current_caller per request, so routes using both ask Supabase once.
    return caller.actor
