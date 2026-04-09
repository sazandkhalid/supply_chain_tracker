from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.api.dependencies import CurrentUser, DbSession
from backend.models.exception_event import ExceptionEvent, ExceptionStatus
from backend.schemas.exception_event import (
    ExceptionAcknowledge,
    ExceptionEventResponse,
    ExceptionResolve,
)

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


@router.get("", response_model=List[ExceptionEventResponse])
async def list_exceptions(
    db: DbSession,
    current_user: CurrentUser,
    shipment_id: UUID | None = None,
    severity: str | None = None,
    status_filter: str | None = None,
):
    """List all exceptions for the org, with optional filters."""
    query = select(ExceptionEvent).where(ExceptionEvent.org_id == current_user.org_id)
    if shipment_id:
        query = query.where(ExceptionEvent.shipment_id == shipment_id)
    if severity:
        query = query.where(ExceptionEvent.severity == severity.upper())
    if status_filter:
        query = query.where(ExceptionEvent.status == status_filter.upper())

    query = query.order_by(ExceptionEvent.detected_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/{exception_id}/acknowledge", response_model=ExceptionEventResponse)
async def acknowledge_exception(
    exception_id: UUID,
    payload: ExceptionAcknowledge,
    db: DbSession,
    current_user: CurrentUser,
):
    exc = await db.scalar(
        select(ExceptionEvent).where(
            ExceptionEvent.id == exception_id, ExceptionEvent.org_id == current_user.org_id
        )
    )
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")
    if exc.status != ExceptionStatus.OPEN:
        raise HTTPException(status_code=409, detail=f"Exception is already {exc.status}")

    exc.status = ExceptionStatus.ACKNOWLEDGED
    if payload.note:
        meta = dict(exc.rule_metadata or {})
        meta["acknowledgement_note"] = payload.note
        exc.rule_metadata = meta

    await db.flush()
    await db.refresh(exc)
    return exc


@router.post("/{exception_id}/resolve", response_model=ExceptionEventResponse)
async def resolve_exception(
    exception_id: UUID,
    payload: ExceptionResolve,
    db: DbSession,
    current_user: CurrentUser,
):
    exc = await db.scalar(
        select(ExceptionEvent).where(
            ExceptionEvent.id == exception_id, ExceptionEvent.org_id == current_user.org_id
        )
    )
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")
    if exc.status == ExceptionStatus.RESOLVED:
        raise HTTPException(status_code=409, detail="Exception already resolved")

    exc.status = ExceptionStatus.RESOLVED
    exc.resolved_by = current_user.user_id
    exc.resolved_at = datetime.now(timezone.utc).isoformat()

    meta = dict(exc.rule_metadata or {})
    meta["resolution_note"] = payload.resolution_note
    exc.rule_metadata = meta

    await db.flush()
    await db.refresh(exc)
    return exc
