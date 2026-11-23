from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class OrderItemCreate(BaseModel):
    product_id: str
    quantity: int = Field(..., gt=0)


class ShippingAddress(BaseModel):
    name: str = Field(..., min_length=1)
    address: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    postal: Optional[str] = None
    phone: str = Field(..., min_length=7)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(..., min_length=1)
    shipping: ShippingAddress


class OrderItemResponse(BaseModel):
    id: str
    product_id: str
    product_name: str
    product_sku: str
    quantity: int
    unit_price: float
    line_total: float

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: str
    user_id: str
    status: str
    shipping_name: Optional[str] = None
    shipping_address: Optional[str] = None
    shipping_city: Optional[str] = None
    shipping_postal: Optional[str] = None
    shipping_phone: Optional[str] = None
    subtotal: float
    shipping_cost: float
    total: float
    payment_reference: Optional[str] = None
    placed_at: datetime
    items: list[OrderItemResponse] = []

    model_config = {"from_attributes": True}
