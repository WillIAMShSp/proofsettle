"""Who is calling. Supabase owns login; this process owns the workflow.

A request carries `Authorization: Bearer <supabase access token>`. We ask Supabase Auth
who that token is, then read `public.profiles.role` (Buyer, Supplier or Reviewer).
`X-Demo-Role` is not consulted. Tests replace `current_actor` and never reach this code.
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


def _supabase_profile_role(user_id: str, token: str | None = None) -> Actor:
    """Fetch user role from Supabase REST API when local DB does not have public.profiles."""
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(503, "Could not read the user profile: Supabase auth is not configured")
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/profiles?id=eq.{user_id}&select=role"
    auth_header = f"Bearer {token}" if token else f"Bearer {settings.supabase_anon_key}"
    req = urllib.request.Request(
        url,
        headers={"apikey": settings.supabase_anon_key, "Authorization": auth_header},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except HTTPException:
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "Could not read the user profile") from exc

    if isinstance(payload, list) and len(payload) > 0 and isinstance(payload[0], dict):
        return actor_from_role(payload[0].get("role"))
    raise HTTPException(403, "No ProofSettle profile for this account")


def profile_role(db: Session, user_id: str, token: str | None = None) -> Actor:
    """Role for this auth user from public.profiles. Workflow tables are not in public."""
    try:
        row = db.execute(_PROFILE_SQL, {"id": user_id}).one_or_none()
    except SQLAlchemyError as exc:
        db.rollback()
        # On SQLite / when public.profiles does not exist in local DB, fetch from Supabase REST API.
        try:
            return _supabase_profile_role(user_id, token)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Could not read the user profile") from exc
    if row is None:
        raise HTTPException(403, "No ProofSettle profile for this account")
    return actor_from_role(row[0])


_Db = Annotated[Session, Depends(get_db)]


def current_actor(db: _Db, authorization: Annotated[str | None, Header()] = None) -> Actor:
    token = bearer_token(authorization)
    return profile_role(db, supabase_user_id(token), token)
