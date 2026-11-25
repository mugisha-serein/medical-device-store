"""
PaymentGateway port (hexagonal boundary) with Flutterwave adapter.

The port defines the interface; the adapter implements it against Flutterwave's API.
A second provider can be added without touching domain code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import get_settings


@dataclass
class PaymentInitiation:
    """Data needed to initiate a payment."""
    order_id: str
    amount: float
    currency: str = "RWF"
    email: str = ""
    name: str = ""
    phone: str = ""
    redirect_url: str = ""

    def __post_init__(self):
        if self.currency != "RWF":
            raise ValueError("Only RWF payments are supported.")


@dataclass
class PaymentResult:
    """Result of a payment initiation."""
    success: bool
    transaction_id: Optional[str] = None
    payment_url: Optional[str] = None
    error_message: Optional[str] = None


class PaymentGateway(ABC):
    """Port interface for payment providers."""

    @abstractmethod
    async def initiate_payment(self, payment: PaymentInitiation) -> PaymentResult:
        """Initiate a payment and return the payment URL for redirect."""
        ...

    @abstractmethod
    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Verify that a webhook payload is authentic."""
        ...

    @abstractmethod
    async def verify_transaction(self, transaction_id: int) -> Optional[dict]:
        """Verify a transaction's status with the PSP."""
        ...


class PaymentGatewayConfigurationError(RuntimeError):
    """Raised when the real payment provider is not configured."""


class FlutterwaveAdapter(PaymentGateway):
    """Flutterwave payment adapter implementation."""

    def __init__(self):
        settings = get_settings()
        self.secret_key = settings.FLW_SECRET_KEY
        self.base_url = settings.FLW_BASE_URL
        self.webhook_secret = settings.FLW_WEBHOOK_SECRET

    async def initiate_payment(self, payment: PaymentInitiation) -> PaymentResult:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/payments",
                    headers={
                        "Authorization": f"Bearer {self.secret_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "tx_ref": f"alm-{payment.order_id}",
                        "amount": str(payment.amount),
                        "currency": payment.currency,
                        "redirect_url": payment.redirect_url,
                        "customer": {
                            "email": payment.email,
                            "name": payment.name,
                        },
                        "meta": {
                            "order_id": payment.order_id,
                        },
                    },
                    timeout=30.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return PaymentResult(
                            success=True,
                            transaction_id=data["data"].get("id"),
                            payment_url=data["data"].get("link"),
                        )
                    return PaymentResult(
                        success=False,
                        error_message=data.get("message", "Payment initiation failed"),
                    )
                return PaymentResult(
                    success=False,
                    error_message=f"Flutterwave API error: {response.status_code}",
                )
            except httpx.RequestError as e:
                return PaymentResult(
                    success=False,
                    error_message=f"Network error: {str(e)}",
                )

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Verify Flutterwave webhook signature using HMAC."""
        import hmac
        import hashlib

        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def verify_transaction(self, transaction_id: int) -> Optional[dict]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/transactions/{transaction_id}/verify",
                    headers={
                        "Authorization": f"Bearer {self.secret_key}",
                    },
                    timeout=30.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return data.get("data")
                return None
            except httpx.RequestError:
                return None


class MockPaymentGateway(PaymentGateway):
    """Mock payment gateway for development/testing."""

    async def initiate_payment(self, payment: PaymentInitiation) -> PaymentResult:
        return PaymentResult(
            success=True,
            transaction_id=f"mock-tx-{payment.order_id}",
            payment_url=f"/checkout/confirm?order={payment.order_id}",
        )

    async def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return True

    async def verify_transaction(self, transaction_id: int) -> Optional[dict]:
        return {"status": "successful", "id": transaction_id}


def get_payment_gateway() -> PaymentGateway:
    """Return the configured real gateway; never fall back to an unsafe mock."""
    settings = get_settings()
    secret_key = settings.FLW_SECRET_KEY
    webhook_secret = settings.FLW_WEBHOOK_SECRET
    if (
        not isinstance(secret_key, str)
        or not secret_key.strip()
        or not isinstance(webhook_secret, str)
        or not webhook_secret.strip()
    ):
        raise PaymentGatewayConfigurationError("Payment gateway is not configured.")
    return FlutterwaveAdapter()
