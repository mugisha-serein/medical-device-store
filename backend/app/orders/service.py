from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orders.models import Order, OrderItem, OrderStatus, OutboxEvent
from app.orders.schemas import OrderCreate
from app.catalog.models import Product
from app.inventory.service import hold_stock, restore_stock, decrement_stock


# Shipping cost: free over $250, otherwise $12.50
SHIPPING_THRESHOLD = 250.00
SHIPPING_COST = 12.50


def calculate_shipping(subtotal: float) -> float:
    return 0.0 if subtotal >= SHIPPING_THRESHOLD else SHIPPING_COST


async def place_order(
    db: AsyncSession,
    user_id: str,
    data: OrderCreate,
) -> Order:
    """
    Place a new order with server-side validation and stock reservation.
    """
    # 1. Validate all products exist and are active, compute server-side prices
    line_items = []
    for item in data.items:
        result = await db.execute(
            select(Product).where(Product.id == item.product_id, Product.is_active == True)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(
                status_code=400,
                detail=f"Product {item.product_id} not found or inactive.",
            )
        line_items.append({
            "product_id": product.id,
            "product_name": product.name,
            "product_sku": product.sku,
            "quantity": item.quantity,
            "unit_price": product.price,  # Server-truth price
            "line_total": product.price * item.quantity,
        })

    # 2. Compute server-side totals
    subtotal = sum(li["line_total"] for li in line_items)
    shipping_cost = calculate_shipping(subtotal)
    total = subtotal + shipping_cost

    # 3. Create order (status: pending_payment)
    order = Order(
        user_id=user_id,
        status=OrderStatus.PENDING_PAYMENT,
        shipping_name=data.shipping.name,
        shipping_address=data.shipping.address,
        shipping_city=data.shipping.city,
        shipping_postal=data.shipping.postal,
        shipping_phone=data.shipping.phone,
        subtotal=subtotal,
        shipping_cost=shipping_cost,
        total=total,
    )
    db.add(order)
    await db.flush()

    # 4. Hold stock for each line item
    for li in line_items:
        await hold_stock(db, li["product_id"], order.id, li["quantity"])

    # 5. Create order items
    for li in line_items:
        order_item = OrderItem(
            order_id=order.id,
            **li,
        )
        db.add(order_item)

    # 6. Emit outbox event
    event = OutboxEvent(
        event_type="order.placed",
        payload={
            "order_id": order.id,
            "user_id": user_id,
            "total": total,
            "items": [{"product_id": li["product_id"], "qty": li["quantity"]} for li in line_items],
        },
    )
    db.add(event)

    await db.flush()
    return order


async def cancel_order(
    db: AsyncSession,
    order_id: str,
    user_id: str,
) -> Order:
    """
    Cancel an order. Restores stock exactly once (guards against double-cancel).
    """
    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.user_id == user_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.status in (OrderStatus.CANCELLED, OrderStatus.DELIVERED, OrderStatus.SHIPPED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in '{order.status}' status.",
        )

    # Restore stock for each item (only once — status guard)
    for item in order.items:
        await restore_stock(db, item.product_id, item.quantity)

    # Release any active holds
    from app.inventory.service import release_hold
    await release_hold(db, order.id)

    order.status = OrderStatus.CANCELLED
    db.add(order)

    # Emit outbox event
    event = OutboxEvent(
        event_type="order.cancelled",
        payload={
            "order_id": order.id,
            "user_id": user_id,
        },
    )
    db.add(event)

    await db.flush()
    return order


async def confirm_payment(
    db: AsyncSession,
    order_id: str,
    payment_reference: str,
) -> Order:
    """
    Confirm payment for an order: move from pending_payment to paid,
    commit held stock, emit outbox event.
    """
    result = await db.execute(
        select(Order).where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.status != OrderStatus.PENDING_PAYMENT:
        raise HTTPException(
            status_code=400,
            detail=f"Order is in '{order.status}' status, expected 'pending_payment'.",
        )

    # Commit held stock
    from app.inventory.service import commit_hold
    await commit_hold(db, order.id)

    order.status = OrderStatus.PAID
    order.payment_reference = payment_reference
    db.add(order)

    # Emit outbox event
    event = OutboxEvent(
        event_type="order.paid",
        payload={
            "order_id": order.id,
            "user_id": order.user_id,
            "total": order.total,
            "payment_reference": payment_reference,
        },
    )
    db.add(event)

    await db.flush()
    return order
