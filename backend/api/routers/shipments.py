from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.api.dependencies import CurrentUser, DbSession
from backend.models.shipment import Shipment
from backend.schemas.shipment import ShipmentCreate, ShipmentResponse, ShipmentUpdate

router = APIRouter(prefix="/shipments", tags=["shipments"])


def _scope(query, org_id: UUID):
    """Enforce org scoping on every query."""
    return query.where(Shipment.org_id == org_id)


@router.get("", response_model=List[ShipmentResponse])
async def list_shipments(db: DbSession, current_user: CurrentUser):
    result = await db.execute(
        _scope(select(Shipment), current_user.org_id).order_by(Shipment.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_shipment(payload: ShipmentCreate, db: DbSession, current_user: CurrentUser):
    shipment = Shipment(
        org_id=current_user.org_id,
        created_by=current_user.user_id,
        **payload.model_dump(exclude_none=True),
    )
    db.add(shipment)
    await db.flush()
    await db.refresh(shipment)
    return shipment


@router.get("/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(shipment_id: UUID, db: DbSession, current_user: CurrentUser):
    shipment = await db.scalar(
        _scope(select(Shipment).where(Shipment.id == shipment_id), current_user.org_id)
    )
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


@router.patch("/{shipment_id}", response_model=ShipmentResponse)
async def update_shipment(
    shipment_id: UUID, payload: ShipmentUpdate, db: DbSession, current_user: CurrentUser
):
    shipment = await db.scalar(
        _scope(select(Shipment).where(Shipment.id == shipment_id), current_user.org_id)
    )
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(shipment, field, value)

    await db.flush()
    await db.refresh(shipment)
    return shipment
