"""
Unified FastAPI entry point for Railway deployment.
Combines the real-time simulation server with the TradeFlow AI
trade-compliance API into a single service.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Import the two sub-applications ──────────────────────────────
from server import app as sim_app  # noqa: F401 — exported for tests
from backend.api.main import app as compliance_app, ensure_schema

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Ensure compliance DB schema on boot.  Best-effort — never blocks startup.
    await ensure_schema()
    yield


app = FastAPI(
    title="TradeFlow AI",
    version="0.1.0",
    description="Unified logistics simulation + trade compliance platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount compliance API — its routers already use /api/v1 prefix
app.mount("/compliance", compliance_app)

# Mount simulation at root (handles /, /start-sim, /ws)
app.mount("/", sim_app)
