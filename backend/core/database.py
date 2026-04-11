from typing import AsyncGenerator, Optional

import boto3
from sqlalchemy.dialects.postgresql import JSONB as _PGJSONB, UUID as _PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase

from .config import settings


# Make Postgres UUID columns compile to CHAR(36) on SQLite so we can run
# integration tests (and local dev) without a live Postgres.  Production
# still uses real Postgres UUID — this only fires when the dialect is
# SQLite.  Binding/result adaptation is handled by SQLAlchemy 2.0 via the
# existing ``as_uuid=True`` flag.
@compiles(_PGUUID, "sqlite")
def _compile_uuid_sqlite(element, compiler, **kw):  # pragma: no cover — dialect hook
    return "CHAR(36)"


# Same idea for JSONB: SQLite has no native JSONB, but storing JSON as TEXT
# is fine for tests — SQLAlchemy's Python-side bind/result handling on the
# column's `Optional[dict]` type already goes through dict <-> JSON.  Without
# this shim, create_all() explodes on SQLite when it hits a JSONB column,
# which silently leaves half the tables missing and makes every endpoint
# that touches documents / events / exceptions return 500 under tests.
@compiles(_PGJSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover — dialect hook
    return "TEXT"

# Lazy-initialized so test collection doesn't try to connect
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        kwargs: dict = {"echo": settings.DEBUG}
        # Connection pooling knobs are specific to network-backed drivers.
        # SQLite (used in tests / local dev) rejects them.
        if not settings.DATABASE_URL.startswith("sqlite"):
            kwargs["pool_size"] = 10
            kwargs["max_overflow"] = 20
        _engine = create_async_engine(settings.DATABASE_URL, **kwargs)
    return _engine


def get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_dynamodb_table():
    """Return the DynamoDB table resource for real-time tracking (existing infra)."""
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )
    return dynamodb.Table(settings.DYNAMODB_TABLE_NAME)
