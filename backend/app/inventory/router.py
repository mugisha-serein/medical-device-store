from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.inventory.models import Inventory
from app.inventory.service import ensure_inventory
from app.inventory.schemas import InventoryResponse, InventoryUpdate

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


@router.get("/products/{product_id}", response_model=InventoryResponse)
async def check_stock(product_id: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint to check available stock for a product."""
    inv = await ensure_inventory(db, product_id, initial_quantity=0)
    return InventoryResponse(
        id=inv.id,
        product_id=inv.product_id,
        quantity_total=inv.quantity_total,
        quantity_held=inv.quantity_held,
        quantity_committed=inv.quantity_committed,
        quantity_available=inv.quantity_available,
    )


@router.put("/admin/products/{product_id}", response_model=InventoryResponse)
async def update_inventory(
    product_id: str,
    data: InventoryUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin endpoint to set total stock for a product."""
    inv = await ensure_inventory(db, product_id, initial_quantity=0)
    inv.quantity_total = data.quantity_total
    db.add(inv)
    await db.flush()

    return InventoryResponse(
        id=inv.id,
        product_id=inv.product_id,
        quantity_total=inv.quantity_total,
        quantity_held=inv.quantity_held,
        quantity_committed=inv.quantity_committed,
        quantity_available=inv.quantity_available,
    )
