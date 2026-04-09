import uuid
from typing import Optional

from pydantic import BaseModel, Field


class SubscribeRequest(BaseModel):
    # E.164 format — Saudi numbers look like +966501234567
    phone_number: str = Field(
        ...,
        pattern=r"^\+\d{7,15}$",
        description="Phone number in E.164 format, e.g. +966501234567",
    )
    label: str = Field(default="", max_length=100, description="Human-readable label, e.g. 'Ops Manager'")
    notify_critical: bool = True
    notify_high: bool = True
    notify_expiry: bool = True


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    phone_number: str
    label: str
    notify_critical: bool
    notify_high: bool
    notify_expiry: bool
    active: bool

    model_config = {"from_attributes": True}


class TestNotificationResponse(BaseModel):
    sent: int
    total_subscribers: int
    detail: Optional[str] = None
