"""
Unified FastAPI entry point for Railway deployment.
Combines the real-time simulation server with the TradeFlow AI
trade-compliance API into a single service.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Import the two sub-applications ──────────────────────────────
from server import app as sim_app, connected_clients, build_payload, simulation_loop
from backend.api.main import app as compliance_app

app = FastAPI(
    title="TradeFlow AI",
    version="0.1.0",
    description="Unified logistics simulation + trade compliance platform",
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
