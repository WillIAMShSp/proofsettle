import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.chain import get_chain
from app.chain.anchoring import anchor_all
from app.config import settings
from app.db import SessionLocal, create_tables, engine, get_db
from app.inspection import InspectionFailed
from app.routes import router
from app.storage import StorageError
from app.workflow import TransitionError

JSON_UTF8 = b"application/json; charset=utf-8"
log = logging.getLogger(__name__)


class JSONCharsetMiddleware:
    """Send "application/json; charset=utf-8" instead of a bare "application/json".

    Our JSON is UTF-8 with literal ×, − and ≥; without the charset, Windows PowerShell 5.1
    decodes it as Latin-1. A middleware also covers FastAPI's own error responses (404,
    422, HTTPException), which don't use the app's default response class.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_charset(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (k, JSON_UTF8 if k.lower() == b"content-type" and v.lower() == b"application/json" else v)
                    for k, v in message.get("headers", [])
                ]
            await send(message)

        await self.app(scope, receive, send_with_charset)


def _anchor_backlog() -> None:
    """Mirror anything not on-chain yet (seeded history, events from an RPC outage)."""
    chain = get_chain()
    if chain is None:
        return
    try:
        with SessionLocal() as db:
            for r in anchor_all(db, chain):
                if r.error:
                    log.warning("Startup anchoring of %s stopped: %s", r.shipment_id, r.error)
    except Exception:
        log.exception("Startup anchoring crashed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_tables(engine)
    if get_chain() is not None:
        threading.Thread(target=_anchor_backlog, name="anchor-backlog", daemon=True).start()
    yield


app = FastAPI(title="ProofSettle API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Dev-Role"],
)
app.add_middleware(JSONCharsetMiddleware)
app.include_router(router)


@app.exception_handler(TransitionError)
def transition_error(_: Request, exc: TransitionError) -> JSONResponse:
    # 400 / 403 / 409 as API_CONTRACT.md's Errors table says; nothing was committed.
    return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)


@app.exception_handler(InspectionFailed)
def inspection_failed(_: Request, exc: InspectionFailed) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.exception_handler(StorageError)
def storage_failed(_: Request, exc: StorageError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.get("/health")
def health(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError:
        db_status = "unavailable"
    return {"status": "ok", "db": db_status}
