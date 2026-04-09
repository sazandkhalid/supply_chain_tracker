from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.api.routers import auth, documents, exceptions, notifications, shipments, sync

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
