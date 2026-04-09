from datetime import date
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.api.dependencies import CurrentUser, DbSession
from backend.models.document import Document
from backend.models.exception_event import ExceptionEvent, ExceptionStatus
from backend.models.shipment import Shipment
from backend.schemas.document import DocumentCreate, DocumentResponse
from backend.services.exception_engine import (
    DocumentSnapshot,
    ShipmentContext,
    run_exception_checks,
)
from datetime import datetime, timezone

router = APIRouter(tags=["documents"])


def _get_shipment_or_404(shipment_id: UUID, org_id: UUID, db):
    return db.scalar(
        select(Shipment).where(Shipment.id == shipment_id, Shipment.org_id == org_id)
    )


def _doc_to_snapshot(doc: Document) -> DocumentSnapshot:
    def _parse_date(s):
        return date.fromisoformat(s) if s else None

    return DocumentSnapshot(
        doc_type=doc.doc_type,
        reference_number=doc.reference_number,
        issue_date=_parse_date(doc.issue_date),
        expiry_date=_parse_date(doc.expiry_date),
        hs_code=doc.hs_code,
        gross_weight_kg=float(doc.gross_weight_kg) if doc.gross_weight_kg else None,
        net_weight_kg=float(doc.net_weight_kg) if doc.net_weight_kg else None,
        quantity=float(doc.quantity) if doc.quantity else None,
        quantity_unit=doc.quantity_unit,
        declared_value=float(doc.declared_value) if doc.declared_value else None,
        currency=doc.currency,
        issuing_country=doc.issuing_country,
    )


@router.get("/shipments/{shipment_id}/documents", response_model=List[DocumentResponse])
async def list_documents(shipment_id: UUID, db: DbSession, current_user: CurrentUser):
    result = await db.execute(
        select(Document).where(
            Document.shipment_id == shipment_id, Document.org_id == current_user.org_id
        )
    )
    return result.scalars().all()


@router.post(
    "/shipments/{shipment_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_document(
    shipment_id: UUID, payload: DocumentCreate, db: DbSession, current_user: CurrentUser
):
    shipment = await db.scalar(
        select(Shipment).where(
            Shipment.id == shipment_id, Shipment.org_id == current_user.org_id
        )
    )
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    doc = Document(
        shipment_id=shipment_id,
        org_id=current_user.org_id,
        uploaded_by=current_user.user_id,
        **payload.model_dump(exclude_none=True),
    )
    db.add(doc)
    await db.flush()

    # Re-run exception checks after every new document upload
    all_docs_result = await db.execute(
        select(Document).where(
            Document.shipment_id == shipment_id, Document.org_id == current_user.org_id
        )
    )
    all_docs = list(all_docs_result.scalars().all())

    snapshots = [_doc_to_snapshot(d) for d in all_docs]
    shipment_ctx = ShipmentContext(
        reference_number=shipment.reference_number,
        origin_country=shipment.origin_country,
        destination_country=shipment.destination_country,
        transport_mode=shipment.transport_mode,
        hs_code=shipment.hs_code,
        gross_weight_kg=float(shipment.gross_weight_kg) if shipment.gross_weight_kg else None,
        quantity=float(shipment.quantity) if shipment.quantity else None,
        quantity_unit=shipment.quantity_unit,
        declared_value=float(shipment.declared_value) if shipment.declared_value else None,
        currency=shipment.currency,
    )

    # Clear existing OPEN exceptions and replace with fresh run
    existing = await db.execute(
        select(ExceptionEvent).where(
            ExceptionEvent.shipment_id == shipment_id,
            ExceptionEvent.status == ExceptionStatus.OPEN,
        )
    )
    for ex in existing.scalars():
        await db.delete(ex)

    detected_at = datetime.now(timezone.utc).isoformat()
    new_exceptions = run_exception_checks(shipment_ctx, snapshots)
    for exc in new_exceptions:
        db.add(
            ExceptionEvent(
                shipment_id=shipment_id,
                org_id=current_user.org_id,
                exception_type=exc.exception_type,
                severity=exc.severity,
                status=ExceptionStatus.OPEN,
                title=exc.title,
                description=exc.description,
                detected_at=detected_at,
                rule_metadata=exc.rule_metadata,
            )
        )

    # Update shipment exception counts
    shipment.open_exception_count = len(new_exceptions)
    shipment.critical_exception_count = sum(
        1 for e in new_exceptions if e.severity == "CRITICAL"
    )

    await db.flush()
    await db.refresh(doc)
    return doc
