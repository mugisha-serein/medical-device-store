from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CategoryResponse(BaseModel):
    id: str
    slug: str
    name: str
    tagline: Optional[str] = None
    icon_svg: Optional[str] = None

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    category_id: str
    specs: Optional[dict] = None
    requires_prescription: bool = False
    certification_refs: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    category_id: Optional[str] = None
    specs: Optional[dict] = None
    requires_prescription: Optional[bool] = None
    certification_refs: Optional[str] = None
    is_active: Optional[bool] = None


class ProductResponse(BaseModel):
    id: str
    sku: str
    name: str
    description: Optional[str] = None
    price: float
    category_id: str
    category_name: Optional[str] = None
    specs: Optional[dict] = None
    requires_prescription: bool
    certification_refs: Optional[str] = None
    is_active: bool
    stock: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}
