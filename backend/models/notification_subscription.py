import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from .base import TimestampMixin, UUIDMixin


class NotificationSubscription(Base, UUIDMixin, TimestampMixin):
    """
    A WhatsApp number subscribed to receive alerts for an organisation.

    Each row represents one team member (or shared group number) who
    should be notified when the exception engine fires.  Multiple
    subscribers per org are supported — common in Saudi logistics teams
    that coordinate via shared WhatsApp groups.
    """

    __tablename__ = "notification_subscriptions"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Phone number in E.164 format, e.g. +966501234567
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    # Human-readable label, e.g. "Ops Manager" or "Warehouse Team"
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    # Granular opt-in flags so team members can choose their alert level
    notify_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_high: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<NotificationSubscription {self.phone_number} label={self.label!r}>"
