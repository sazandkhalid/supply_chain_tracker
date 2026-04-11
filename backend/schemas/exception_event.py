from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class ExceptionEventResponse(BaseModel):
    id: UUID
    shipment_id: UUID
    org_id: UUID
    exception_type: str
    severity: str
    status: str
    title: str
    description: str
    detected_at: str
    resolved_at: Optional[str]
    resolved_by: Optional[UUID]
    rule_metadata: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


class ExceptionAcknowledge(BaseModel):
    note: Optional[str] = None


class ExceptionResolve(BaseModel):
    resolution_note: str
