from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    doc_type: str = Field(..., description="DocumentType enum value")
    reference_number: Optional[str] = None
    issue_date: Optional[str] = None        # ISO date: YYYY-MM-DD
    expiry_date: Optional[str] = None
    issuing_authority: Optional[str] = None
    issuing_country: Optional[str] = Field(None, min_length=2, max_length=2)
    hs_code: Optional[str] = None
    gross_weight_kg: Optional[float] = Field(None, gt=0)
    net_weight_kg: Optional[float] = Field(None, gt=0)
    quantity: Optional[float] = Field(None, gt=0)
    quantity_unit: Optional[str] = None
    declared_value: Optional[float] = Field(None, gt=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None


class DocumentResponse(BaseModel):
    id: UUID
    shipment_id: UUID
    org_id: UUID
    doc_type: str
    status: str
    reference_number: Optional[str]
    issue_date: Optional[str]
    expiry_date: Optional[str]
    issuing_authority: Optional[str]
    issuing_country: Optional[str]
    hs_code: Optional[str]
    gross_weight_kg: Optional[float]
    net_weight_kg: Optional[float]
    quantity: Optional[float]
    quantity_unit: Optional[str]
    declared_value: Optional[float]
    currency: Optional[str]
    file_name: Optional[str]
    file_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
