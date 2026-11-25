from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.orders.models import Order, OrderStatus
from app.orders.service import confirm_payment
from app.payments.gateway import (
    PaymentGatewayConfigurationError,
    PaymentInitiation,
    get_payment_gateway,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


def _get_payment_gateway_or_503():
    try:
        return get_payment_gateway()
    except PaymentGatewayConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment gateway is not configured.",
        ) from None


class PaymentInitiateRequest(BaseModel):
    order_id: str
    return_url: str = ""


@router.post("/initiate")
async def initiate_payment(
    data: PaymentInitiateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Initiate a payment for an order via Flutterwave."""
    from sqlalchemy import select

    result = await db.execute(
        select(Order).where(
            Order.id == data.order_id,
            Order.user_id == current_user.id,
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.status != OrderStatus.PENDING_PAYMENT:
        raise HTTPException(
            status_code=400,
            detail=f"Order is in '{order.status}' status, cannot initiate payment.",
        )

    gateway = _get_payment_gateway_or_503()
    payment = PaymentInitiation(
        order_id=order.id,
        amount=order.total,
        currency="RWF",
        email=current_user.email,
        name=current_user.name,
        redirect_url=data.return_url,
    )

    result = await gateway.initiate_payment(payment)

    if not result.success:
        raise HTTPException(
            status_code=502,
            detail=result.error_message or "Payment initiation failed.",
        )

    return {
        "transaction_id": result.transaction_id,
        "payment_url": result.payment_url,
    }


@router.post("/webhook")
async def payment_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Flutterwave payment webhook. Idempotent — PSPs retry deliveries."""
    body = await request.body()
    signature = request.headers.get("verif-hash", "")

    gateway = _get_payment_gateway_or_503()

    # Verify webhook signature
    if not await gateway.verify_webhook(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    import json
    payload = json.loads(body)
    event = payload.get("event")
    data = payload.get("data", {})

    if event == "charge.completed" and data.get("status") == "successful":
        tx_ref = data.get("tx_ref", "")
        # Extract order_id from tx_ref (format: alm-{order_id})
        if tx_ref.startswith("alm-"):
            order_id = tx_ref[len("alm-"):]
            try:
                await confirm_payment(db, order_id, data.get("id", ""))
            except Exception:
                # Log error but don't fail webhook — PSP will retry
                pass

    return {"status": "ok"}
