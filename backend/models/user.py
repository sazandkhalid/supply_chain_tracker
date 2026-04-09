import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from .base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .organization import Organization


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # roles: admin | ops | viewer
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="ops")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="users")

    def __repr__(self) -> str:
        return f"<User {self.email} [{self.role}]>"
