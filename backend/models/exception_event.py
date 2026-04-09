import uuid
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from .base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .shipment import Shipment


class ExceptionType(str, Enum):
    HS_CODE_MISMATCH = "HS_CODE_MISMATCH"
    MISSING_REQUIRED_DOC = "MISSING_REQUIRED_DOC"
    WEIGHT_DISCREPANCY = "WEIGHT_DISCREPANCY"
    QUANTITY_DISCREPANCY = "QUANTITY_DISCREPANCY"
    VALUE_DISCREPANCY = "VALUE_DISCREPANCY"
    EXPIRED_CERTIFICATE = "EXPIRED_CERTIFICATE"
    EXPIRING_SOON = "EXPIRING_SOON"
    COUNTRY_MISMATCH = "COUNTRY_MISMATCH"
    INVALID_HS_CODE = "INVALID_HS_CODE"
    RESTRICTED_ORIGIN = "RESTRICTED_ORIGIN"
    DOCUMENT_INCONSISTENCY = "DOCUMENT_INCONSISTENCY"


class ExceptionSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ExceptionEvent(Base, UUIDMixin, TimestampMixin):
    """
    A flagged compliance or documentation exception on a shipment.
    Created by the exception engine; lifecycle managed by ops team.
    """

    __tablename__ = "exception_events"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    exception_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=ExceptionStatus.OPEN)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # ISO 8601 timestamps
    detected_at: Mapped[str] = mapped_column(String(30), nullable=False)
    resolved_at: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # Rule details: which documents were compared, actual values, expected values
    rule_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    shipment: Mapped["Shipment"] = relationship("Shipment", back_populates="exceptions")

    def __repr__(self) -> str:
        return f"<ExceptionEvent {self.exception_type} [{self.severity}/{self.status}]>"
