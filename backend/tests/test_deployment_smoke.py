"""
Deployment smoke tests.

These exercise the full unified ASGI app (``main_unified.app``) end-to-end
against an in-memory SQLite database so we can prove the Railway-bound
surface area actually boots and serves traffic — without requiring a live
Postgres in CI.  The ``@compiles`` shim in ``backend/core/database.py``
makes the Postgres UUID column type compile to ``CHAR(36)`` on SQLite, so
models work unchanged.

If any of these regress, the deploy is broken.
"""
import asyncio
import importlib.util
import os
import sys

import pytest
import pytest_asyncio


# Skip the whole module if the async-sqlite driver isn't installed — the
# production image doesn't need it, but these tests do.
if importlib.util.find_spec("aiosqlite") is None:
    pytest.skip(
        "aiosqlite not installed — deployment smoke tests require it locally.",
        allow_module_level=True,
    )


pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(scope="module", autouse=True)
def _configure_env():
    """
    Point the app at an in-memory SQLite DB *before* main_unified imports,
    and make sure no stale engine from another test leaks across.
    """
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["SECRET_KEY"] = "test-secret-not-for-prod"

    # Drop cached modules so `from backend.core.config import settings`
    # re-reads the env vars we just set.
    for mod in [
        m
        for m in list(sys.modules)
        if m.startswith("backend") or m in {"main_unified", "server"}
    ]:
        del sys.modules[mod]

    yield


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    from httpx import ASGITransport, AsyncClient

    from backend.api.main import ensure_schema
    from main_unified import app

    # Normally the lifespan runs this on boot; call it directly so the
    # tables exist before our first request.
    await ensure_schema()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_root_returns_ok(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "running" in r.json()["status"].lower()


async def test_compliance_health(client):
    r = await client.get("/compliance/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_auth_register_then_login_flow(client):
    register_payload = {
        "email": "smoketest@example.com",
        "password": "supersecret123",
        "full_name": "Smoke Test",
        "org_name": "SmokeCo",
        "org_country_code": "SA",
    }
    r = await client.post(
        "/compliance/api/v1/auth/register", json=register_payload
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "access_token" in body
    assert body["role"] == "admin"

    # Re-register with the same email should be rejected.
    r2 = await client.post(
        "/compliance/api/v1/auth/register", json=register_payload
    )
    assert r2.status_code == 400

    # Login with correct credentials.
    r3 = await client.post(
        "/compliance/api/v1/auth/login",
        json={"email": register_payload["email"], "password": register_payload["password"]},
    )
    assert r3.status_code == 200, r3.text
    assert "access_token" in r3.json()

    # Login with wrong password → 401.
    r4 = await client.post(
        "/compliance/api/v1/auth/login",
        json={"email": register_payload["email"], "password": "wrong"},
    )
    assert r4.status_code == 401


async def test_database_url_normalization():
    """The validator in Settings must rewrite Railway's postgresql:// URL
    into SQLAlchemy's async dialect form."""
    # Fresh import so we get a new Settings class not bound to the fixture env.
    from backend.core.config import Settings

    s = Settings(DATABASE_URL="postgresql://user:pw@host/db")
    assert s.DATABASE_URL.startswith("postgresql+asyncpg://")

    s2 = Settings(DATABASE_URL="postgres://user:pw@host/db")
    assert s2.DATABASE_URL.startswith("postgresql+asyncpg://")

    s3 = Settings(DATABASE_URL="postgresql+asyncpg://user:pw@host/db")
    assert s3.DATABASE_URL == "postgresql+asyncpg://user:pw@host/db"
