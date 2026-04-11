import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.core.database import Base, get_engine
import backend.models  # noqa: F401 — registers all models with Base.metadata
from backend.api.routers import auth, documents, exceptions, notifications, shipments, sync

logger = logging.getLogger(__name__)


async def ensure_schema() -> None:
    """
    Create any missing tables — pragmatic alternative to running Alembic on
    every deploy for this single-environment Railway target.  Best-effort:
    if the database is unreachable, log loudly but don't crash so the
    simulation half of the unified app can still serve clients.

    Called from :mod:`main_unified.py`'s lifespan so the hook fires on the
    parent ASGI app (mounted sub-app lifespans are unreliable).
    """
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Compliance DB schema ensured (create_all).")
    except Exception as exc:  # pragma: no cover — boot-time best-effort
        logger.warning(
            "Could not initialize compliance DB schema: %s. "
            "Compliance endpoints will 500 until DATABASE_URL points at a "
            "reachable Postgres.",
            exc,
        )


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Trade compliance and exception detection for GCC/Iraq import-export operations.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(shipments.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(exceptions.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}
