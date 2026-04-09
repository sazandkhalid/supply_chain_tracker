"""
Append-only event log for shipment lifecycle changes.

Every mutation to a shipment is recorded here as an immutable event.
This is the source of truth for offline-first sync:
- Clients generate UUIDs locally and write events to local SQLite
- On reconnect, they POST a batch of events to /api/v1/sync/push
- Server processes in client_timestamp order, ignores duplicate event IDs

Event types map directly to user actions in the field:
  SHIPMENT_CREATED          → new booking entered offline
  SHIPMENT_STATUS_UPDATED   → status change (e.g. ARRIVED at port)
  DOCUMENT_UPLOADED         → document metadata entered (file uploads handled separately)
  CUSTOMS_ENTRY_UPDATED     → customs entry number or clearance update
  EXCEPTION_ACKNOWLEDGED    → ops person saw the flag
  EXCEPTION_RESOLVED        → ops person fixed the underlying issue
  NOTE_ADDED                → free-text note on a shipment
"""

import uuid
from enum import Enum
from typing import Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from .base import UUIDMixin


class EventType(str, Enum):
    SHIPMENT_CREATED = "SHIPMENT_CREATED"
    SHIPMENT_STATUS_UPDATED = "SHIPMENT_STATUS_UPDATED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    CUSTOMS_ENTRY_UPDATED = "CUSTOMS_ENTRY_UPDATED"
    EXCEPTION_ACKNOWLEDGED = "EXCEPTION_ACKNOWLEDGED"
    EXCEPTION_RESOLVED = "EXCEPTION_RESOLVED"
    NOTE_ADDED = "NOTE_ADDED"


class ShipmentEvent(Base, UUIDMixin):
    """
    Immutable event record. Never updated after insert.
    `id` is client-generated (UUID4) to support offline creation.
    """

    __tablename__ = "shipment_events"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Nullable: SHIPMENT_CREATED events don't have a shipment_id until processed
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(String(60), nullable=False)

    # Client-side timestamp — the moment the action happened on the device.
    # This is the ordering key for replaying events; server created_at is not reliable
    # for ordering because batches arrive late.
    client_timestamp: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    # Server receipt timestamp (set by server, not client)
    server_timestamp: Mapped[str] = mapped_column(String(30), nullable=False)

    # Event-specific data — see EventType docstring for payload shapes
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Sync tracking
    sync_batch_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<ShipmentEvent {self.event_type} @ {self.client_timestamp}>"
