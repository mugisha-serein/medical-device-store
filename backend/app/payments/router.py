import json
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, get_db
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
):
    """Handle Flutterwave payment webhook. Idempotent — PSPs retry deliveries."""
    body = await request.body()
    signature = request.headers.get("verif-hash", "")

    gateway = _get_payment_gateway_or_503()

    # Verify webhook signature
    if not await gateway.verify_webhook(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    payload = json.loads(body)
    event = payload.get("event")
    data = payload.get("data", {})

    if event == "charge.completed":
        if not isinstance(data, dict):
            return {"status": "ok"}

        # Flutterwave documents transaction IDs as positive int32 values. Do not
        # coerce strings, booleans, floats, or out-of-range values into IDs.
        transaction_id = data.get("id")
        if (
            isinstance(transaction_id, bool)
            or not isinstance(transaction_id, int)
            or transaction_id <= 0
            or transaction_id > 2_147_483_647
        ):
            return {"status": "ok"}

        webhook_reference = data.get("tx_ref")
        if not isinstance(webhook_reference, str) or not webhook_reference.startswith("alm-"):
            return {"status": "ok"}
        order_id = webhook_reference[len("alm-"):]
        try:
            if str(uuid.UUID(order_id)) != order_id:
                raise ValueError
        except (ValueError, AttributeError):
            return {"status": "ok"}
        expected_reference = f"alm-{order_id}"
        if webhook_reference != expected_reference:
            return {"status": "ok"}

        try:
            verified = await gateway.verify_transaction(transaction_id)
        except Exception:
            raise HTTPException(status_code=503, detail="Payment verification unavailable.") from None
        if not isinstance(verified, dict):
            # The adapter returns None for upstream failures as well as missing verification data.
            raise HTTPException(status_code=503, detail="Payment verification unavailable.")

        # Flutterwave v3's transaction verification response contains id,
        # tx_ref, amount, currency, and status in its `data` object.
        verified_id = verified.get("id")
        verified_amount = verified.get("amount")
        if (
            verified.get("status") != "successful"
            or isinstance(verified_id, bool)
            or not isinstance(verified_id, int)
            or verified_id != transaction_id
            or verified.get("tx_ref") != expected_reference
            or webhook_reference != expected_reference
            or verified.get("currency") != "RWF"
            or isinstance(verified_amount, bool)
            or not isinstance(verified_amount, (int, float))
        ):
            return {"status": "ok"}

        try:
            # Resolve commit or rollback before acknowledging the delivery.
            async with async_session_factory.begin() as db:
                result = await db.execute(select(Order).where(Order.id == order_id))
                order = result.scalar_one_or_none()
                if order is None:
                    return {"status": "ok"}

                try:
                    provider_amount = Decimal(str(verified_amount))
                    expected_amount = Decimal(str(order.total))
                except (InvalidOperation, ValueError, TypeError):
                    return {"status": "ok"}
                if not provider_amount.is_finite() or provider_amount != expected_amount:
                    return {"status": "ok"}

                payment_reference = str(transaction_id)
                reused = await db.execute(
                    select(Order.id).where(
                        Order.payment_reference == payment_reference,
                        Order.id != order_id,
                    )
                )
                if reused.scalar_one_or_none() is not None:
                    return {"status": "ok"}

                if order.status == OrderStatus.PAID and order.payment_reference == payment_reference:
                    # A verified replay is acknowledged without repeating stock or outbox work.
                    return {"status": "ok"}
                if order.status != OrderStatus.PENDING_PAYMENT:
                    return {"status": "ok"}

                await confirm_payment(db, order_id, payment_reference)
        except Exception:
            raise HTTPException(status_code=503, detail="Payment processing unavailable.") from None

    return {"status": "ok"}
