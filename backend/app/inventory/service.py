from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import Inventory, StockHold, HoldStatus


HOLD_DURATION_MINUTES = 15  # Stock hold expires after 15 minutes


async def get_inventory_for_product(db: AsyncSession, product_id: str) -> Inventory | None:
    result = await db.execute(
        select(Inventory).where(Inventory.product_id == product_id)
    )
    return result.scalar_one_or_none()


async def ensure_inventory(db: AsyncSession, product_id: str, initial_quantity: int = 0) -> Inventory:
    """Ensure inventory record exists for a product, creating if needed."""
    inv = await get_inventory_for_product(db, product_id)
    if not inv:
        inv = Inventory(
            product_id=product_id,
            quantity_total=initial_quantity,
            quantity_held=0,
            quantity_committed=0,
        )
        db.add(inv)
        await db.flush()
    return inv


async def decrement_stock(
    db: AsyncSession,
    product_id: str,
    quantity: int,
) -> bool:
    """
    Decrement stock atomically using row-level locking.
    Returns True if successful, False if insufficient stock.
    """
    # SELECT ... FOR UPDATE to lock the row
    result = await db.execute(
        select(Inventory)
        .where(Inventory.product_id == product_id)
        .with_for_update()
    )
    inv = result.scalar_one_or_none()
    if not inv:
        return False

    available = inv.quantity_total - inv.quantity_held - inv.quantity_committed
    if available < quantity:
        return False

    inv.quantity_committed += quantity
    db.add(inv)
    return True


async def restore_stock(
    db: AsyncSession,
    product_id: str,
    quantity: int,
) -> bool:
    """
    Restore stock atomically (e.g., on cancellation).
    Returns True if successful.
    """
    result = await db.execute(
        select(Inventory)
        .where(Inventory.product_id == product_id)
        .with_for_update()
    )
    inv = result.scalar_one_or_none()
    if not inv:
        return False

    # Never restore more than what's committed
    actual_restore = min(quantity, inv.quantity_committed)
    inv.quantity_committed -= actual_restore
    db.add(inv)
    return True


async def hold_stock(
    db: AsyncSession,
    product_id: str,
    order_id: str,
    quantity: int,
) -> StockHold:
    """
    Reserve stock for an order during checkout.
    Creates a hold that expires after HOLD_DURATION_MINUTES.
    """
    result = await db.execute(
        select(Inventory)
        .where(Inventory.product_id == product_id)
        .with_for_update()
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Product inventory not found.")

    available = inv.quantity_total - inv.quantity_held - inv.quantity_committed
    if available < quantity:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient stock. Available: {available}, requested: {quantity}",
        )

    hold = StockHold(
        inventory_id=inv.id,
        order_id=order_id,
        quantity=quantity,
        status=HoldStatus.ACTIVE,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=HOLD_DURATION_MINUTES),
    )
    inv.quantity_held += quantity
    db.add(inv)
    db.add(hold)
    await db.flush()
    return hold


async def commit_hold(db: AsyncSession, order_id: str) -> bool:
    """
    Convert held stock to committed (on payment success).
    """
    result = await db.execute(
        select(StockHold).where(
            StockHold.order_id == order_id,
            StockHold.status == HoldStatus.ACTIVE,
        )
    )
    holds = result.scalars().all()

    for hold in holds:
        inv = await db.execute(
            select(Inventory)
            .where(Inventory.id == hold.inventory_id)
            .with_for_update()
        )
        inv_row = inv.scalar_one_or_none()
        if inv_row:
            inv_row.quantity_held -= hold.quantity
            inv_row.quantity_committed += hold.quantity
            hold.status = HoldStatus.COMMITTED
            db.add(inv_row)
            db.add(hold)

    return len(holds) > 0


async def release_hold(db: AsyncSession, order_id: str) -> bool:
    """
    Release held stock (on timeout or cancellation).
    """
    result = await db.execute(
        select(StockHold).where(
            StockHold.order_id == order_id,
            StockHold.status == HoldStatus.ACTIVE,
        )
    )
    holds = result.scalars().all()

    for hold in holds:
        inv = await db.execute(
            select(Inventory)
            .where(Inventory.id == hold.inventory_id)
            .with_for_update()
        )
        inv_row = inv.scalar_one_or_none()
        if inv_row:
            inv_row.quantity_held -= hold.quantity
            hold.status = HoldStatus.RELEASED
            db.add(inv_row)
            db.add(hold)

    return len(holds) > 0


async def release_expired_holds(db: AsyncSession) -> int:
    """
    Release all expired stock holds. Returns count of released holds.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(StockHold).where(
            StockHold.status == HoldStatus.ACTIVE,
            StockHold.expires_at < now,
        )
    )
    expired_holds = result.scalars().all()
    count = 0

    for hold in expired_holds:
        inv = await db.execute(
            select(Inventory)
            .where(Inventory.id == hold.inventory_id)
            .with_for_update()
        )
        inv_row = inv.scalar_one_or_none()
        if inv_row:
            inv_row.quantity_held -= hold.quantity
            hold.status = HoldStatus.EXPIRED
            db.add(inv_row)
            db.add(hold)
            count += 1

    return count
