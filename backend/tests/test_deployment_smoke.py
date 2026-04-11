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


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def auth_headers(client):
    """
    Register a fresh org for the endpoint-surface tests below and return
    ``Authorization: Bearer …`` headers bound to that org.  Uses a distinct
    email from the auth-flow test so the two can coexist in one module.
    """
    payload = {
        "email": "endpoints@example.com",
        "password": "supersecret123",
        "full_name": "Endpoint Smoke",
        "org_name": "EndpointCo",
        "org_country_code": "SA",
    }
    r = await client.post("/compliance/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_sync_status_is_public(client):
    """The connectivity-check endpoint must not require auth."""
    r = await client.get("/compliance/api/v1/sync/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "server_timestamp" in body


async def test_shipment_crud_round_trip(client, auth_headers):
    """Create → list → fetch → patch a shipment end-to-end."""
    create_payload = {
        "reference_number": "TF-SMOKE-0001",
        "origin_country": "CN",
        "destination_country": "SA",
        "transport_mode": "SEA",
        "hs_code": "847130",
        "gross_weight_kg": 1000.0,
        "declared_value": 50000.0,
        "currency": "USD",
    }
    r = await client.post(
        "/compliance/api/v1/shipments", json=create_payload, headers=auth_headers
    )
    assert r.status_code == 201, r.text
    shipment = r.json()
    shipment_id = shipment["id"]
    assert shipment["reference_number"] == "TF-SMOKE-0001"

    r_list = await client.get("/compliance/api/v1/shipments", headers=auth_headers)
    assert r_list.status_code == 200
    assert any(s["id"] == shipment_id for s in r_list.json())

    r_get = await client.get(
        f"/compliance/api/v1/shipments/{shipment_id}", headers=auth_headers
    )
    assert r_get.status_code == 200
    assert r_get.json()["id"] == shipment_id

    r_patch = await client.patch(
        f"/compliance/api/v1/shipments/{shipment_id}",
        json={"status": "DOCS_SUBMITTED"},
        headers=auth_headers,
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["status"] == "DOCS_SUBMITTED"


async def test_document_upload_triggers_exception_engine(client, auth_headers):
    """
    Adding a document with an HS-code mismatch against the shipment must
    create an OPEN exception — exercises documents + exceptions + engine.
    """
    # Fresh shipment so counts don't interfere with other tests.
    r = await client.post(
        "/compliance/api/v1/shipments",
        json={
            "reference_number": "TF-SMOKE-0002",
            "origin_country": "CN",
            "destination_country": "SA",
            "transport_mode": "SEA",
            "hs_code": "847130",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    shipment_id = r.json()["id"]

    r_doc = await client.post(
        f"/compliance/api/v1/shipments/{shipment_id}/documents",
        json={
            "doc_type": "COMMERCIAL_INVOICE",
            "reference_number": "INV-1",
            "hs_code": "999999",  # deliberate mismatch
        },
        headers=auth_headers,
    )
    assert r_doc.status_code == 201, r_doc.text

    r_exc = await client.get(
        f"/compliance/api/v1/exceptions?shipment_id={shipment_id}",
        headers=auth_headers,
    )
    assert r_exc.status_code == 200
    exceptions = r_exc.json()
    assert len(exceptions) >= 1
    assert any("HS" in e["exception_type"] or "HS" in e["title"] for e in exceptions)


async def test_sync_push_and_pull(client, auth_headers):
    """Push a SHIPMENT_CREATED event then pull it back."""
    import uuid as _uuid

    event_id = str(_uuid.uuid4())
    shipment_id = str(_uuid.uuid4())
    push_payload = {
        "events": [
            {
                "id": event_id,
                "event_type": "SHIPMENT_CREATED",
                "shipment_id": shipment_id,
                "client_timestamp": "2026-04-11T08:00:00+00:00",
                "payload": {
                    "reference_number": "TF-SMOKE-SYNC-001",
                    "origin_country": "IQ",
                    "destination_country": "SA",
                    "transport_mode": "ROAD",
                },
            }
        ],
        "batch_id": "smoke-batch-1",
    }
    r = await client.post(
        "/compliance/api/v1/sync/push", json=push_payload, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["processed"] == 1
    assert body["errors"] == 0

    # Duplicate push is silently deduped.
    r2 = await client.post(
        "/compliance/api/v1/sync/push", json=push_payload, headers=auth_headers
    )
    assert r2.status_code == 200
    assert r2.json()["duplicates"] == 1

    r_pull = await client.get(
        "/compliance/api/v1/sync/pull", headers=auth_headers
    )
    assert r_pull.status_code == 200
    assert "X-Sync-Checkpoint" in r_pull.headers
    pulled = r_pull.json()
    assert any(
        s["reference_number"] == "TF-SMOKE-SYNC-001" for s in pulled["shipments"]
    )


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
