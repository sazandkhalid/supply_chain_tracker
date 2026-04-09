import uuid
from typing import TYPE_CHECKING, List

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from .base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .user import User
    from .shipment import Shipment


class Organization(Base, UUIDMixin, TimestampMixin):
    """Tenant root — every data row is scoped to an org."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # ISO 3166-1 alpha-2 codes — primary country of operation
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    # Additional countries this org operates in (comma-separated ISO codes)
    operating_countries: Mapped[str | None] = mapped_column(Text, nullable=True)
    subscription_tier: Mapped[str] = mapped_column(
        String(50), nullable=False, default="starter"
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    users: Mapped[List["User"]] = relationship("User", back_populates="organization")
    shipments: Mapped[List["Shipment"]] = relationship(
        "Shipment", back_populates="organization"
    )

    def __repr__(self) -> str:
        return f"<Organization {self.name} ({self.country_code})>"
