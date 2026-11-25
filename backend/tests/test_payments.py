"""RWF-only payment integration without contacting a payment provider."""
import pytest
from types import SimpleNamespace

from sqlalchemy import text

from app.payments.gateway import PaymentInitiation, MockPaymentGateway
from tests.test_orders import seed_product


def test_payment_currency_defaults_to_rwf():
    assert PaymentInitiation(order_id="unit-test", amount=100).currency == "RWF"


@pytest.mark.parametrize("currency", ["USD", "EUR", ""])
def test_payment_rejects_non_rwf_currency(currency):
    with pytest.raises(ValueError, match="RWF"):
        PaymentInitiation(order_id="unit-test", amount=100, currency=currency)


@pytest.mark.asyncio
async def test_payment_initiation_uses_rwf(client, auth_headers, db_session, monkeypatch):
    import app.payments.router as router
    captured = []

    class RecordingGateway(MockPaymentGateway):
        async def initiate_payment(self, payment):
            captured.append(payment)
            return await super().initiate_payment(payment)

    monkeypatch.setattr(router, "get_payment_gateway", RecordingGateway)
    _, product_id = await seed_product(db_session)
    placed = await client.post("/api/v1/orders", headers=auth_headers, json={
        "items": [{"product_id": product_id, "quantity": 1}],
        "shipping": {"name": "Buyer", "address": "Kigali", "city": "Kigali", "phone": "+250788000000"},
    })
    assert placed.status_code == 201
    response = await client.post("/api/v1/payments/initiate", headers=auth_headers, json={"order_id": placed.json()["id"]})
    assert response.status_code == 200
    assert captured[0].currency == "RWF"
    assert captured[0].amount == placed.json()["total"]


@pytest.mark.parametrize(
    ("secret_key", "webhook_secret"),
    [
        (None, "webhook-secret"),
        ("", "webhook-secret"),
        ("   ", "webhook-secret"),
        ("provider-secret", None),
        ("provider-secret", ""),
        ("provider-secret", "   "),
    ],
)
def test_gateway_requires_nonblank_flutterwave_credentials(monkeypatch, secret_key, webhook_secret):
    import app.payments.gateway as gateway

    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            FLW_SECRET_KEY=secret_key,
            FLW_WEBHOOK_SECRET=webhook_secret,
            FLW_BASE_URL="https://api.flutterwave.com/v3",
        ),
    )

    with pytest.raises(RuntimeError, match="Payment gateway is not configured"):
        gateway.get_payment_gateway()


def test_configured_gateway_selects_flutterwave_adapter(monkeypatch):
    import app.payments.gateway as gateway

    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            FLW_SECRET_KEY="test-provider-secret",
            FLW_WEBHOOK_SECRET="test-webhook-secret",
            FLW_BASE_URL="https://api.flutterwave.com/v3",
        ),
    )

    selected = gateway.get_payment_gateway()
    assert isinstance(selected, gateway.FlutterwaveAdapter)
    assert not isinstance(selected, MockPaymentGateway)


@pytest.mark.asyncio
async def test_unconfigured_payment_initiation_returns_safe_error(client, auth_headers, db_session, monkeypatch):
    import app.payments.gateway as gateway

    _, product_id = await seed_product(db_session)
    placed = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 1}],
            "shipping": {"name": "Buyer", "address": "Kigali", "city": "Kigali", "phone": "+250788000000"},
        },
    )
    private_marker = "provider-secret-must-not-be-disclosed"
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            FLW_SECRET_KEY=private_marker,
            FLW_WEBHOOK_SECRET="",
            FLW_BASE_URL="https://api.flutterwave.com/v3",
        ),
    )

    response = await client.post(
        "/api/v1/payments/initiate",
        headers=auth_headers,
        json={"order_id": placed.json()["id"]},
    )

    assert response.status_code == 503
    assert "configured" in response.json()["detail"].lower()
    assert private_marker not in response.text


@pytest.mark.asyncio
async def test_unconfigured_forged_webhook_cannot_change_payment_inventory_or_outbox(
    client, auth_headers, db_session, monkeypatch
):
    import app.payments.gateway as gateway

    _, product_id = await seed_product(db_session)
    placed = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 1}],
            "shipping": {"name": "Buyer", "address": "Kigali", "city": "Kigali", "phone": "+250788000000"},
        },
    )
    assert placed.status_code == 201
    order_id = placed.json()["id"]

    async def state_snapshot():
        order = (
            await db_session.execute(
                text("SELECT status, payment_reference FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            )
        ).one()
        inventory = (
            await db_session.execute(
                text("SELECT quantity_held, quantity_committed FROM inventory WHERE product_id = :product_id"),
                {"product_id": product_id},
            )
        ).one()
        holds = (
            await db_session.execute(
                text("SELECT quantity, status FROM stock_holds WHERE order_id = :order_id ORDER BY id"),
                {"order_id": order_id},
            )
        ).all()
        outbox = (
            await db_session.execute(text("SELECT event_type, payload FROM outbox_events ORDER BY id"))
        ).all()
        return order, inventory, holds, outbox

    before = await state_snapshot()
    private_marker = "provider-secret-must-not-be-disclosed"
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            FLW_SECRET_KEY="",
            FLW_WEBHOOK_SECRET=private_marker,
            FLW_BASE_URL="https://api.flutterwave.com/v3",
        ),
    )

    response = await client.post(
        "/api/v1/payments/webhook",
        headers={"verif-hash": "forged-signature"},
        json={
            "event": "charge.completed",
            "data": {"status": "successful", "tx_ref": f"alm-{order_id}", "id": "forged-tx"},
        },
    )

    assert response.status_code == 503
    assert "configured" in response.json()["detail"].lower()
    assert private_marker not in response.text
    assert await state_snapshot() == before


@pytest.mark.parametrize("task_name", ["send_order_confirmation", "send_payment_received"])
def test_payment_emails_label_amounts_as_rwf(monkeypatch, task_name):
    from app.notifications import tasks
    messages = []

    async def record(to, subject, html):
        messages.append(html)
        return True

    monkeypatch.setattr(tasks, "send_email", record)
    getattr(tasks, task_name).run("unit-test-order", "test@example.com", 100)
    assert "RWF 100.00" in messages[0]
    assert "$" not in messages[0]
