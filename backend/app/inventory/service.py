from collections import Counter
from collections.abc import Iterable
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
    Decrement stock within the engine's serialized SQLite transaction.
    Returns True if successful, False if insufficient stock.
    """
    # Generic lock intent is retained; SQLite serialization is provided by
    # BEGIN IMMEDIATE in the engine, before any inventory reads.
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


class StockReservationError(RuntimeError):
    """An order's reservations cannot be committed safely."""


async def commit_hold(
    db: AsyncSession, order_id: str, order_items: Iterable[tuple[str, int]],
) -> None:
    """Validate and commit every stock hold inside the caller's transaction."""
    expected = Counter(order_items)
    result = await db.execute(
        select(StockHold, Inventory)
        .outerjoin(Inventory, Inventory.id == StockHold.inventory_id)
        .where(StockHold.order_id == order_id)
    )
    reservations = result.all()
    now = datetime.now(timezone.utc)
    actual = Counter()
    inventory_by_id = {}
    for hold, inventory in reservations:
        if (
            inventory is None
            or hold.status != HoldStatus.ACTIVE
            or hold.expires_at <= now
            or hold.quantity <= 0
        ):
            raise StockReservationError("Order has an invalid stock reservation.")
        actual[inventory.product_id, hold.quantity] += 1
        inventory_by_id[inventory.id] = inventory

    # Placement creates one hold per order line, including repeated products.
    if not expected or actual != expected:
        raise StockReservationError("Stock reservations do not match the order items.")

    for inventory in inventory_by_id.values():
        active_quantities = [hold.quantity for hold in inventory.holds if hold.status == HoldStatus.ACTIVE]
        if (
            any(quantity <= 0 for quantity in active_quantities)
            or inventory.quantity_held != sum(active_quantities)
            or inventory.quantity_committed < 0
            or inventory.quantity_available < 0
        ):
            raise StockReservationError("Inventory counters do not match available stock or active holds.")

    for hold, inventory in reservations:
        inventory.quantity_held -= hold.quantity
        inventory.quantity_committed += hold.quantity
        hold.status = HoldStatus.COMMITTED
    await db.flush()


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
