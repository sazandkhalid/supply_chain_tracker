import uuid
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from .base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .shipment import Shipment


class DocumentType(str, Enum):
    BILL_OF_LADING = "BILL_OF_LADING"
    AIRWAY_BILL = "AIRWAY_BILL"
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    PACKING_LIST = "PACKING_LIST"
    CERTIFICATE_OF_ORIGIN = "CERTIFICATE_OF_ORIGIN"
    PHYTOSANITARY_CERTIFICATE = "PHYTOSANITARY_CERTIFICATE"
    HEALTH_CERTIFICATE = "HEALTH_CERTIFICATE"
    IMPORT_PERMIT = "IMPORT_PERMIT"
    CUSTOMS_DECLARATION = "CUSTOMS_DECLARATION"
    INSURANCE_CERTIFICATE = "INSURANCE_CERTIFICATE"
    DANGEROUS_GOODS_DECLARATION = "DANGEROUS_GOODS_DECLARATION"
    OTHER = "OTHER"


class DocumentStatus(str, Enum):
    PENDING = "PENDING"       # Uploaded, not yet reviewed
    VERIFIED = "VERIFIED"     # Manually or AI-verified clean
    FLAGGED = "FLAGGED"       # Has exceptions
    REJECTED = "REJECTED"     # Formally rejected by customs/reviewer


class Document(Base, UUIDMixin, TimestampMixin):
    """
    A customs or trade document attached to a shipment.
    Key fields are structured columns; raw extracted data lives in extracted_data (JSONB).
    """

    __tablename__ = "documents"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    doc_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DocumentStatus.PENDING)
    reference_number: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    # Dates extracted from the document
    issue_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)    # ISO date
    expiry_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # ISO date

    # Issuer info
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    issuing_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)  # ISO alpha-2

    # Cargo fields extracted from THIS document (used for cross-document validation)
    hs_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    gross_weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(12, 3), nullable=True)
    net_weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(12, 3), nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Numeric(12, 3), nullable=True)
    quantity_unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    declared_value: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)

    # File storage
    file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Raw data from OCR/AI extraction — flexible schema
    extracted_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    shipment: Mapped["Shipment"] = relationship("Shipment", back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document {self.doc_type} [{self.status}] shipment={self.shipment_id}>"
