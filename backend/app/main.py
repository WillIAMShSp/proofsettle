from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.db import create_tables, engine, get_db
from app.routes import router

JSON_UTF8 = b"application/json; charset=utf-8"


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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_tables(engine)
    yield


app = FastAPI(title="ProofSettle API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["X-Demo-Role", "Content-Type"],
)
app.add_middleware(JSONCharsetMiddleware)
app.include_router(router)


@app.get("/health")
def health(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError:
        db_status = "unavailable"
    return {"status": "ok", "db": db_status}
