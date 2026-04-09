import uuid
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from .base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .organization import Organization
    from .document import Document
    from .exception_event import ExceptionEvent


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    DOCS_SUBMITTED = "DOCS_SUBMITTED"
    CUSTOMS_REVIEW = "CUSTOMS_REVIEW"
    CUSTOMS_CLEARED = "CUSTOMS_CLEARED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_PORT = "AT_PORT"
    DELIVERED = "DELIVERED"
    HELD = "HELD"
    REJECTED = "REJECTED"


class FreightTerms(str, Enum):
    FOB = "FOB"
    CIF = "CIF"
    CFR = "CFR"
    EXW = "EXW"
    DDP = "DDP"
    DAP = "DAP"


class TransportMode(str, Enum):
    SEA = "SEA"
    AIR = "AIR"
    ROAD = "ROAD"
    RAIL = "RAIL"
    MULTIMODAL = "MULTIMODAL"


class Shipment(Base, UUIDMixin, TimestampMixin):
    """
    Core trade shipment record. One shipment = one customs entry.
    DynamoDB stores the real-time position/tracking data (keyed by reference_number).
    This table stores the structured trade/compliance data.
    """

    __tablename__ = "shipments"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Identity
    reference_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=ShipmentStatus.DRAFT)

    # Trade route
    origin_country: Mapped[str] = mapped_column(String(2), nullable=False)   # ISO alpha-2
    destination_country: Mapped[str] = mapped_column(String(2), nullable=False)
    origin_port: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    destination_port: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Cargo
    hs_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # Declared HS code
    cargo_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gross_weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(12, 3), nullable=True)
    net_weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(12, 3), nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Numeric(12, 3), nullable=True)
    quantity_unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g. "MT", "PCS", "CTN"

    # Value
    declared_value: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)  # ISO 4217

    # Logistics
    transport_mode: Mapped[str] = mapped_column(String(20), nullable=False, default=TransportMode.SEA)
    freight_terms: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    carrier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vessel_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    voyage_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Customs
    customs_entry_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    estimated_arrival: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # ISO 8601
    actual_arrival: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # Exception summary (denormalized for quick queries)
    open_exception_count: Mapped[int] = mapped_column(nullable=False, default=0)
    critical_exception_count: Mapped[int] = mapped_column(nullable=False, default=0)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="shipments")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="shipment")
    exceptions: Mapped[List["ExceptionEvent"]] = relationship(
        "ExceptionEvent", back_populates="shipment"
    )

    def __repr__(self) -> str:
        return f"<Shipment {self.reference_number} [{self.status}]>"
