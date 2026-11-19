from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class InventoryResponse(BaseModel):
    id: str
    product_id: str
    quantity_total: int
    quantity_held: int
    quantity_committed: int
    quantity_available: int

    model_config = {"from_attributes": True}


class InventoryUpdate(BaseModel):
    quantity_total: int = Field(..., ge=0)


class StockHoldResponse(BaseModel):
    id: str
    order_id: str
    quantity: int
    status: str
    expires_at: datetime
    created_at: datetime
