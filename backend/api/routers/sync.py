"""
Offline-first sync endpoints.

Push:   POST /api/v1/sync/push   — client sends a batch of locally-created events
Pull:   GET  /api/v1/sync/pull   — client fetches all changes since a given timestamp

Design contract:
- Events are identified by client-generated UUID. Duplicate event IDs are silently
  skipped so clients can safely retry failed syncs.
- Events are processed in client_timestamp order within each batch.
- Processing is best-effort within a transaction: if one event fails, it's recorded
  as an error but the rest of the batch continues.
- The pull response gives the client everything it needs to rebuild local state.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from backend.api.dependencies import CurrentUser, DbSession
from backend.models.document import Document, DocumentStatus
from backend.models.exception_event import ExceptionEvent, ExceptionSeverity, ExceptionStatus
from backend.models.shipment import Shipment
from backend.models.shipment_event import EventType, ShipmentEvent
from backend.schemas.document import DocumentResponse
from backend.schemas.exception_event import ExceptionEventResponse
from backend.schemas.shipment import ShipmentResponse
from backend.services.exception_engine import (
    DocumentSnapshot,
    ShipmentContext,
    run_exception_checks,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


# ---------------------------------------------------------------------------
# Push — inbound events from offline clients
# ---------------------------------------------------------------------------


class IncomingEvent(BaseModel):
    """A single event from the client's local log."""

    id: uuid.UUID                    # Client-generated UUID — idempotency key
    event_type: str
    shipment_id: Optional[uuid.UUID] = None
    client_timestamp: str            # ISO 8601
    payload: Dict[str, Any] = {}


class PushRequest(BaseModel):
    events: List[IncomingEvent]
    batch_id: Optional[str] = None   # Client-side batch identifier (for retries)


class EventResult(BaseModel):
    id: uuid.UUID
    status: str                      # "processed" | "duplicate" | "error"
    detail: Optional[str] = None


class PushResponse(BaseModel):
    processed: int
    duplicates: int
    errors: int
    results: List[EventResult]
    server_timestamp: str


def _doc_to_snapshot(doc: Document) -> DocumentSnapshot:
    from datetime import date
    def _d(s): return date.fromisoformat(s) if s else None
    return DocumentSnapshot(
        doc_type=doc.doc_type,
        reference_number=doc.reference_number,
        issue_date=_d(doc.issue_date),
        expiry_date=_d(doc.expiry_date),
        hs_code=doc.hs_code,
        gross_weight_kg=float(doc.gross_weight_kg) if doc.gross_weight_kg else None,
        net_weight_kg=float(doc.net_weight_kg) if doc.net_weight_kg else None,
        quantity=float(doc.quantity) if doc.quantity else None,
        quantity_unit=doc.quantity_unit,
        declared_value=float(doc.declared_value) if doc.declared_value else None,
        currency=doc.currency,
        issuing_country=doc.issuing_country,
    )


async def _refresh_exceptions(shipment: Shipment, db: DbSession) -> None:
    """Re-run exception engine after a document change and persist results."""
    all_docs = (
        await db.execute(
            select(Document).where(Document.shipment_id == shipment.id)
        )
    ).scalars().all()

    snapshots = [_doc_to_snapshot(d) for d in all_docs]
    ctx = ShipmentContext(
        reference_number=shipment.reference_number,
        origin_country=shipment.origin_country,
        destination_country=shipment.destination_country,
        transport_mode=shipment.transport_mode,
        hs_code=shipment.hs_code,
        gross_weight_kg=float(shipment.gross_weight_kg) if shipment.gross_weight_kg else None,
        quantity=float(shipment.quantity) if shipment.quantity else None,
        declared_value=float(shipment.declared_value) if shipment.declared_value else None,
        currency=shipment.currency,
    )

    # Replace OPEN exceptions with fresh run
    existing_open = (
        await db.execute(
            select(ExceptionEvent).where(
                ExceptionEvent.shipment_id == shipment.id,
                ExceptionEvent.status == ExceptionStatus.OPEN,
            )
        )
    ).scalars().all()
    for ex in existing_open:
        await db.delete(ex)

    detected_at = datetime.now(timezone.utc).isoformat()
    new_exceptions = run_exception_checks(ctx, snapshots)
    for exc in new_exceptions:
        db.add(
            ExceptionEvent(
                shipment_id=shipment.id,
                org_id=shipment.org_id,
                exception_type=exc.exception_type,
                severity=exc.severity,
                status=ExceptionStatus.OPEN,
                title=exc.title,
                description=exc.description,
                detected_at=detected_at,
                rule_metadata=exc.rule_metadata,
            )
        )

    shipment.open_exception_count = len(new_exceptions)
    shipment.critical_exception_count = sum(1 for e in new_exceptions if e.severity == "CRITICAL")


async def _process_event(
    event: IncomingEvent,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    batch_id: Optional[str],
    db: DbSession,
    server_ts: str,
) -> None:
    """Apply a single event to the system. Raises on unrecoverable errors."""

    evt_type = event.event_type
    p = event.payload

    if evt_type == EventType.SHIPMENT_CREATED:
        shipment = Shipment(
            id=event.shipment_id or uuid.uuid4(),
            org_id=org_id,
            created_by=user_id,
            reference_number=p["reference_number"],
            origin_country=p["origin_country"],
            destination_country=p["destination_country"],
            transport_mode=p.get("transport_mode", "SEA"),
            hs_code=p.get("hs_code"),
            cargo_description=p.get("cargo_description"),
            gross_weight_kg=p.get("gross_weight_kg"),
            net_weight_kg=p.get("net_weight_kg"),
            quantity=p.get("quantity"),
            quantity_unit=p.get("quantity_unit"),
            declared_value=p.get("declared_value"),
            currency=p.get("currency"),
            freight_terms=p.get("freight_terms"),
            carrier_name=p.get("carrier_name"),
            vessel_name=p.get("vessel_name"),
            origin_port=p.get("origin_port"),
            destination_port=p.get("destination_port"),
            estimated_arrival=p.get("estimated_arrival"),
        )
        db.add(shipment)

    elif evt_type == EventType.SHIPMENT_STATUS_UPDATED:
        if not event.shipment_id:
            raise ValueError("shipment_id required for SHIPMENT_STATUS_UPDATED")
        shipment = await db.scalar(
            select(Shipment).where(Shipment.id == event.shipment_id, Shipment.org_id == org_id)
        )
        if not shipment:
            raise ValueError(f"Shipment {event.shipment_id} not found")
        shipment.status = p["status"]

    elif evt_type == EventType.DOCUMENT_UPLOADED:
        if not event.shipment_id:
            raise ValueError("shipment_id required for DOCUMENT_UPLOADED")
        shipment = await db.scalar(
            select(Shipment).where(Shipment.id == event.shipment_id, Shipment.org_id == org_id)
        )
        if not shipment:
            raise ValueError(f"Shipment {event.shipment_id} not found")
        doc = Document(
            shipment_id=event.shipment_id,
            org_id=org_id,
            uploaded_by=user_id,
            doc_type=p["doc_type"],
            reference_number=p.get("reference_number"),
            issue_date=p.get("issue_date"),
            expiry_date=p.get("expiry_date"),
            issuing_authority=p.get("issuing_authority"),
            issuing_country=p.get("issuing_country"),
            hs_code=p.get("hs_code"),
            gross_weight_kg=p.get("gross_weight_kg"),
            net_weight_kg=p.get("net_weight_kg"),
            quantity=p.get("quantity"),
            quantity_unit=p.get("quantity_unit"),
            declared_value=p.get("declared_value"),
            currency=p.get("currency"),
            file_name=p.get("file_name"),
            file_url=p.get("file_url"),
            extracted_data=p.get("extracted_data"),
            status=DocumentStatus.PENDING,
        )
        db.add(doc)
        await db.flush()
        await _refresh_exceptions(shipment, db)

    elif evt_type == EventType.CUSTOMS_ENTRY_UPDATED:
        if not event.shipment_id:
            raise ValueError("shipment_id required for CUSTOMS_ENTRY_UPDATED")
        shipment = await db.scalar(
            select(Shipment).where(Shipment.id == event.shipment_id, Shipment.org_id == org_id)
        )
        if not shipment:
            raise ValueError(f"Shipment {event.shipment_id} not found")
        if "customs_entry_number" in p:
            shipment.customs_entry_number = p["customs_entry_number"]
        if "actual_arrival" in p:
            shipment.actual_arrival = p["actual_arrival"]

    elif evt_type == EventType.EXCEPTION_ACKNOWLEDGED:
        exc_id = uuid.UUID(p["exception_id"])
        exc = await db.scalar(
            select(ExceptionEvent).where(
                ExceptionEvent.id == exc_id, ExceptionEvent.org_id == org_id
            )
        )
        if not exc:
            raise ValueError(f"Exception {exc_id} not found")
        exc.status = ExceptionStatus.ACKNOWLEDGED
        if p.get("note"):
            meta = dict(exc.rule_metadata or {})
            meta["acknowledgement_note"] = p["note"]
            exc.rule_metadata = meta

    elif evt_type == EventType.EXCEPTION_RESOLVED:
        exc_id = uuid.UUID(p["exception_id"])
        exc = await db.scalar(
            select(ExceptionEvent).where(
                ExceptionEvent.id == exc_id, ExceptionEvent.org_id == org_id
            )
        )
        if not exc:
            raise ValueError(f"Exception {exc_id} not found")
        exc.status = ExceptionStatus.RESOLVED
        exc.resolved_by = user_id
        exc.resolved_at = event.client_timestamp
        meta = dict(exc.rule_metadata or {})
        meta["resolution_note"] = p.get("resolution_note", "")
        exc.rule_metadata = meta

    elif evt_type == EventType.NOTE_ADDED:
        # Notes are captured only in the event log — no separate table needed
        pass

    else:
        raise ValueError(f"Unknown event_type: {evt_type}")

    # Persist the event record itself
    db.add(
        ShipmentEvent(
            id=event.id,
            org_id=org_id,
            created_by=user_id,
            shipment_id=event.shipment_id,
            event_type=evt_type,
            client_timestamp=event.client_timestamp,
            server_timestamp=server_ts,
            payload=event.payload,
            sync_batch_id=batch_id,
        )
    )


async def _fire_whatsapp_alerts(
    org_id: uuid.UUID,
    since_ts: str,
    db: DbSession,
) -> None:
    """
    After a sync batch is committed, check whether it introduced any new
    CRITICAL or HIGH exceptions and notify subscribed WhatsApp numbers.

    Imported inline to avoid a circular dependency at module load time.
    """
    from backend.models.notification_subscription import NotificationSubscription
    from backend.services.whatsapp_notifier import notifier, _ExceptionSummary  # type: ignore[attr-defined]

    if not notifier.enabled:
        return

    new_exceptions = (
        await db.execute(
            select(ExceptionEvent).where(
                ExceptionEvent.org_id == org_id,
                ExceptionEvent.detected_at >= since_ts,
                ExceptionEvent.severity.in_(
                    [ExceptionSeverity.CRITICAL, ExceptionSeverity.HIGH]
                ),
            )
        )
    ).scalars().all()

    if not new_exceptions:
        return

    active_subs = (
        await db.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.org_id == org_id,
                NotificationSubscription.active.is_(True),
            )
        )
    ).scalars().all()

    if not active_subs:
        return

    # Group exceptions by shipment so each shipment gets one message
    by_shipment: Dict[uuid.UUID, List[ExceptionEvent]] = {}
    for exc in new_exceptions:
        by_shipment.setdefault(exc.shipment_id, []).append(exc)

    for shipment_id, exceptions in by_shipment.items():
        shipment = await db.scalar(
            select(Shipment).where(Shipment.id == shipment_id)
        )
        if not shipment:
            continue

        # Filter recipients by their notification preferences
        has_critical = any(e.severity == ExceptionSeverity.CRITICAL for e in exceptions)
        recipients = [
            s.phone_number
            for s in active_subs
            if (has_critical and s.notify_critical) or (not has_critical and s.notify_high)
        ]
        if not recipients:
            continue

        summaries = [_ExceptionSummary(severity=e.severity, title=e.title) for e in exceptions]
        sent = notifier.notify_critical_exceptions(recipients, shipment.reference_number, summaries)
        logger.info(
            "WhatsApp alerts fired for shipment=%s exceptions=%d sent=%d",
            shipment.reference_number,
            len(exceptions),
            sent,
        )


# ---------------------------------------------------------------------------
# Connectivity status — lightweight endpoint for unreliable-network clients
# ---------------------------------------------------------------------------


class SyncStatusResponse(BaseModel):
    status: str          # "ok"
    server_timestamp: str


@router.get("/status", response_model=SyncStatusResponse, summary="Connectivity check")
async def sync_status():
    """
    Ultra-lightweight endpoint that warehouse clients can poll to detect
    when connectivity is restored before attempting a full push/pull.
    Does not require authentication.
    """
    return SyncStatusResponse(
        status="ok",
        server_timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/push", response_model=PushResponse)
async def push_events(
    request: PushRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    """
    Accept a batch of offline events from the client.

    Events with a duplicate ID are silently skipped (idempotent).
    The batch is sorted by client_timestamp before processing so events
    that were created offline in sequence are applied in the right order.
    """
    server_ts = datetime.now(timezone.utc).isoformat()
    results: List[EventResult] = []

    # Deduplicate against existing event IDs in one query
    incoming_ids = [e.id for e in request.events]
    existing_ids = set(
        (
            await db.execute(
                select(ShipmentEvent.id).where(ShipmentEvent.id.in_(incoming_ids))
            )
        ).scalars().all()
    )

    # Sort by client_timestamp for correct ordering
    ordered = sorted(request.events, key=lambda e: e.client_timestamp)

    processed = duplicates = errors = 0

    for event in ordered:
        if event.id in existing_ids:
            duplicates += 1
            results.append(EventResult(id=event.id, status="duplicate"))
            continue

        try:
            await _process_event(
                event,
                org_id=current_user.org_id,
                user_id=current_user.user_id,
                batch_id=request.batch_id,
                db=db,
                server_ts=server_ts,
            )
            await db.flush()
            processed += 1
            results.append(EventResult(id=event.id, status="processed"))
        except Exception as exc:
            await db.rollback()
            errors += 1
            results.append(EventResult(id=event.id, status="error", detail=str(exc)))

    # Fire WhatsApp alerts for any critical/high exceptions produced by this batch
    if processed > 0:
        try:
            await _fire_whatsapp_alerts(current_user.org_id, server_ts, db)
        except Exception as exc:
            # Notification failures must never fail the sync response
            logger.error("WhatsApp alert dispatch failed: %s", exc)

    return PushResponse(
        processed=processed,
        duplicates=duplicates,
        errors=errors,
        results=results,
        server_timestamp=server_ts,
    )


# ---------------------------------------------------------------------------
# Pull — outbound data for client to rebuild / update local state
# ---------------------------------------------------------------------------


class PullResponse(BaseModel):
    shipments: List[ShipmentResponse]
    documents: List[DocumentResponse]
    exceptions: List[ExceptionEventResponse]
    server_timestamp: str


@router.get("/pull", response_model=PullResponse)
async def pull_changes(
    response: Response,
    db: DbSession,
    current_user: CurrentUser,
    since: Optional[str] = None,
):
    """
    Return all records for this org, optionally filtered to those updated
    after `since` (ISO 8601 timestamp).  Clients store the returned
    `server_timestamp` and pass it as `since` on the next pull.

    On first sync, omit `since` to download everything.

    The response always includes an ``X-Sync-Checkpoint`` header containing
    the same ISO 8601 timestamp as ``server_timestamp`` in the body.  Clients
    with intermittent connectivity can read this header before parsing the
    full payload and persist it as their next `since` cursor immediately,
    reducing the risk of re-downloading data after a partial read.
    """
    org_id = current_user.org_id

    shipment_q = select(Shipment).where(Shipment.org_id == org_id)
    doc_q = select(Document).where(Document.org_id == org_id)
    exc_q = select(ExceptionEvent).where(ExceptionEvent.org_id == org_id)

    if since:
        shipment_q = shipment_q.where(Shipment.updated_at >= since)
        doc_q = doc_q.where(Document.updated_at >= since)
        exc_q = exc_q.where(ExceptionEvent.created_at >= since)

    shipments = (await db.execute(shipment_q)).scalars().all()
    documents = (await db.execute(doc_q)).scalars().all()
    exceptions = (await db.execute(exc_q)).scalars().all()

    server_ts = datetime.now(timezone.utc).isoformat()

    # Expose the checkpoint in a header so resilient clients can persist it
    # even if they lose the connection mid-body-read.
    response.headers["X-Sync-Checkpoint"] = server_ts

    return PullResponse(
        shipments=shipments,
        documents=documents,
        exceptions=exceptions,
        server_timestamp=server_ts,
    )
