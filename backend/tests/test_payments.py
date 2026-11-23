"""RWF-only payment integration without contacting a payment provider."""
import pytest
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
