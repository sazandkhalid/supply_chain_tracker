from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ShipmentCreate(BaseModel):
    reference_number: str = Field(..., min_length=1, max_length=100)
    origin_country: str = Field(..., min_length=2, max_length=2, description="ISO alpha-2")
    destination_country: str = Field(..., min_length=2, max_length=2)
    transport_mode: str = Field(default="SEA")
    hs_code: Optional[str] = None
    cargo_description: Optional[str] = None
    gross_weight_kg: Optional[float] = Field(None, gt=0)
    net_weight_kg: Optional[float] = Field(None, gt=0)
    quantity: Optional[float] = Field(None, gt=0)
    quantity_unit: Optional[str] = None
    declared_value: Optional[float] = Field(None, gt=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    freight_terms: Optional[str] = None
    carrier_name: Optional[str] = None
    vessel_name: Optional[str] = None
    voyage_number: Optional[str] = None
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    estimated_arrival: Optional[str] = None


class ShipmentUpdate(BaseModel):
    status: Optional[str] = None
    hs_code: Optional[str] = None
    cargo_description: Optional[str] = None
    gross_weight_kg: Optional[float] = Field(None, gt=0)
    net_weight_kg: Optional[float] = Field(None, gt=0)
    quantity: Optional[float] = Field(None, gt=0)
    quantity_unit: Optional[str] = None
    declared_value: Optional[float] = Field(None, gt=0)
    currency: Optional[str] = None
    customs_entry_number: Optional[str] = None
    actual_arrival: Optional[str] = None
    vessel_name: Optional[str] = None
    voyage_number: Optional[str] = None


class ShipmentResponse(BaseModel):
    id: UUID
    org_id: UUID
    reference_number: str
    status: str
    origin_country: str
    destination_country: str
    origin_port: Optional[str]
    destination_port: Optional[str]
    transport_mode: str
    hs_code: Optional[str]
    cargo_description: Optional[str]
    gross_weight_kg: Optional[float]
    quantity: Optional[float]
    quantity_unit: Optional[str]
    declared_value: Optional[float]
    currency: Optional[str]
    freight_terms: Optional[str]
    carrier_name: Optional[str]
    vessel_name: Optional[str]
    customs_entry_number: Optional[str]
    estimated_arrival: Optional[str]
    actual_arrival: Optional[str]
    open_exception_count: int
    critical_exception_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
