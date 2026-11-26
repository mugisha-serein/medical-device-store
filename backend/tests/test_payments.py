"""RWF-only payment integration without contacting a payment provider."""
import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.payments.gateway import PaymentInitiation, MockPaymentGateway
from tests.test_orders import seed_product


class VerifiedWebhookGateway(MockPaymentGateway):
    def __init__(self, verified=None, error=None):
        self.verified = verified
        self.error = error
        self.verified_ids = []

    async def verify_transaction(self, transaction_id):
        self.verified_ids.append(transaction_id)
        if self.error:
            raise self.error
        return self.verified


async def create_payment_order(client, auth_headers, db_session, product_id=None, *, items=None):
    if product_id is None:
        _, product_id = await seed_product(db_session)
    response = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": items if items is not None else [{"product_id": product_id, "quantity": 1}],
            "shipping": {"name": "Buyer", "address": "Kigali", "city": "Kigali", "phone": "+250788000000"},
        },
    )
    assert response.status_code == 201
    return response.json(), product_id


async def payment_state(db_session, order_id, product_id):
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
    outbox = (await db_session.execute(text("SELECT event_type, payload FROM outbox_events ORDER BY id"))).all()
    state = order, inventory, holds, outbox
    await db_session.commit()
    return state


def verified_transaction(order, transaction_id=12345, **overrides):
    data = {
        "id": transaction_id,
        "tx_ref": f"alm-{order['id']}",
        "amount": order["total"],
        "currency": "RWF",
        "status": "successful",
    }
    data.update(overrides)
    return data


def install_verification_gateway(monkeypatch, gateway):
    import app.payments.router as router
    monkeypatch.setattr(router, "get_payment_gateway", lambda: gateway)


async def send_payment_webhook(client, transaction_id=12345, *, order_id, **claims):
    data = {"id": transaction_id, "tx_ref": f"alm-{order_id}", "status": "successful", "amount": 0, "currency": "USD"}
    data.update(claims)
    return await client.post(
        "/api/v1/payments/webhook",
        headers={"verif-hash": "fixture-signature"},
        json={"event": "charge.completed", "data": data},
    )


async def complete_stock_snapshot(db):
    snapshot = {}
    for table in ("orders", "inventory", "stock_holds", "outbox_events"):
        snapshot[table] = (await db.execute(text(f"SELECT * FROM {table} ORDER BY id"))).all()
    await db.rollback()
    return snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", [
    "missing", "partial", "quantity", "wrong-order", "wrong-product", "elapsed",
    "released", "committed", "expired", "held-counter", "oversubscribed", "negative-committed",
])
async def test_invalid_reservations_block_verified_payment(
    client, auth_headers, db_session, monkeypatch, defect
):
    from app.catalog.models import Product
    from app.inventory.models import HoldStatus, Inventory, StockHold
    from sqlalchemy import delete

    category_id, product_id = await seed_product(db_session)
    other_product = Product(sku="other-payment-item", name="Other item", category_id=category_id, price=50)
    db_session.add(other_product)
    await db_session.flush()
    other_inventory = Inventory(product_id=other_product.id, quantity_total=10)
    db_session.add(other_inventory)
    await db_session.commit()
    order, _ = await create_payment_order(client, auth_headers, db_session, product_id, items=[
        {"product_id": product_id, "quantity": 1},
        {"product_id": product_id, "quantity": 2},
    ])
    order_id = order["id"]
    if defect == "missing":
        await db_session.execute(delete(StockHold).where(StockHold.order_id == order_id))
    else:
        hold = (await db_session.execute(
            select(StockHold).where(StockHold.order_id == order_id, StockHold.quantity == 2)
        )).scalar_one()
        inventory = await db_session.get(Inventory, hold.inventory_id)
        if defect == "partial":
            await db_session.delete(hold)
        elif defect == "quantity":
            hold.quantity = 1
        elif defect == "wrong-order":
            hold.order_id = str(uuid4())
        elif defect == "wrong-product":
            hold.inventory_id = other_inventory.id
        elif defect == "elapsed":
            hold.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif defect in {"released", "committed", "expired"}:
            hold.status = HoldStatus(defect)
        elif defect == "held-counter":
            inventory.quantity_held += 1
        elif defect == "oversubscribed":
            inventory.quantity_total = 2
        elif defect == "negative-committed":
            inventory.quantity_committed = -1
    await db_session.commit()
    before = await complete_stock_snapshot(db_session)
    gateway = VerifiedWebhookGateway(verified_transaction(order))
    install_verification_gateway(monkeypatch, gateway)

    response = await send_payment_webhook(client, order_id=order_id)

    assert response.status_code == 503
    assert gateway.verified_ids == [12345]
    assert await complete_stock_snapshot(db_session) == before


@pytest.mark.asyncio
async def test_multi_item_stock_commit_rolls_back_then_retries_once(
    client, auth_headers, db_session, monkeypatch
):
    from app.catalog.models import Product
    from app.inventory.models import Inventory

    category_id, first_id = await seed_product(db_session)
    second = Product(sku="second-payment-item", name="Second item", category_id=category_id, price=50)
    db_session.add(second)
    await db_session.flush()
    second_id = second.id
    db_session.add(Inventory(product_id=second_id, quantity_total=10))
    await db_session.commit()
    order, _ = await create_payment_order(client, auth_headers, db_session, first_id, items=[
        {"product_id": first_id, "quantity": 1},
        {"product_id": first_id, "quantity": 2},
        {"product_id": second_id, "quantity": 1},
    ])
    order_id = order["id"]
    before = await complete_stock_snapshot(db_session)
    gateway = VerifiedWebhookGateway(verified_transaction(order))
    install_verification_gateway(monkeypatch, gateway)
    # Allow the first hold update to reach SQLite before rejecting the next one.
    await db_session.execute(text("""
        CREATE TRIGGER fail_second_hold BEFORE UPDATE ON stock_holds
        WHEN NEW.status = 'COMMITTED' AND EXISTS (
            SELECT 1 FROM stock_holds WHERE order_id = NEW.order_id AND status = 'COMMITTED'
        )
        BEGIN SELECT RAISE(ABORT, 'test failure during stock update'); END
    """))
    await db_session.commit()
    try:
        failed = await send_payment_webhook(client, order_id=order_id)
    finally:
        await db_session.execute(text("DROP TRIGGER fail_second_hold"))
        await db_session.commit()

    assert failed.status_code == 503
    assert await complete_stock_snapshot(db_session) == before
    assert (await send_payment_webhook(client, order_id=order_id)).status_code == 200
    assert (await send_payment_webhook(client, order_id=order_id)).status_code == 200
    saved_order, inventory, holds, outbox = await payment_state(db_session, order_id, first_id)
    assert saved_order == ("PAID", "12345")
    assert inventory == (0, 3)
    assert (await payment_state(db_session, order_id, second_id))[1] == (0, 1)
    assert sorted(holds) == [(1, "COMMITTED"), (1, "COMMITTED"), (2, "COMMITTED")]
    assert sum(entry.event_type == "order.paid" for entry in outbox) == 1
    assert gateway.verified_ids == [12345, 12345, 12345]


@pytest.mark.asyncio
async def test_missing_inventory_rejects_confirmation_and_rolls_back(client, auth_headers, db_session):
    from app.inventory.service import StockReservationError
    from app.orders.service import confirm_payment

    order, product_id = await create_payment_order(client, auth_headers, db_session)
    before = await complete_stock_snapshot(db_session)
    # Simulate a dangling reference only inside a transaction that must roll back.
    with pytest.raises(StockReservationError):
        async with db_session.begin():
            await db_session.execute(text("PRAGMA defer_foreign_keys=ON"))
            await db_session.execute(
                text("DELETE FROM inventory WHERE product_id = :id"), {"id": product_id}
            )
            await confirm_payment(db_session, order["id"], "12345")
    assert await complete_stock_snapshot(db_session) == before


@pytest.mark.asyncio
async def test_webhook_confirms_only_independently_verified_flutterwave_details(
    client, auth_headers, db_session, monkeypatch
):
    order, product_id = await create_payment_order(client, auth_headers, db_session)
    gateway = VerifiedWebhookGateway(verified_transaction(order))
    install_verification_gateway(monkeypatch, gateway)

    # The webhook's asserted status, amount and currency are intentionally false.
    response = await send_payment_webhook(client, order_id=order["id"], status="failed")

    assert response.status_code == 200
    assert gateway.verified_ids == [12345]
    assert (await payment_state(db_session, order["id"], product_id))[0] == ("PAID", "12345")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": 1},
        {"currency": "USD"},
        {"tx_ref": "alm-some-other-order"},
        {"status": "pending"},
        {"id": 54321},
    ],
    ids=["amount", "currency", "order-reference", "unsuccessful", "transaction-id"],
)
async def test_unmatched_verified_transaction_leaves_payment_inventory_and_outbox_unchanged(
    client, auth_headers, db_session, monkeypatch, overrides
):
    order, product_id = await create_payment_order(client, auth_headers, db_session)
    before = await payment_state(db_session, order["id"], product_id)
    gateway = VerifiedWebhookGateway(verified_transaction(order, **overrides))
    install_verification_gateway(monkeypatch, gateway)

    response = await send_payment_webhook(client, order_id=order["id"])

    assert response.status_code == 200
    assert gateway.verified_ids == [12345]
    assert await payment_state(db_session, order["id"], product_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("transaction_id", [None, "", "not-an-id", True, False, 0, -1, 1.5, 2**31])
async def test_malformed_webhook_transaction_id_is_rejected_before_provider_lookup(
    client, auth_headers, db_session, monkeypatch, transaction_id
):
    order, product_id = await create_payment_order(client, auth_headers, db_session)
    before = await payment_state(db_session, order["id"], product_id)
    gateway = VerifiedWebhookGateway(verified_transaction(order))
    install_verification_gateway(monkeypatch, gateway)

    response = await send_payment_webhook(client, transaction_id, order_id=order["id"])

    assert response.status_code == 200
    assert gateway.verified_ids == []
    assert await payment_state(db_session, order["id"], product_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_failure", ["timeout", "connection", "unavailable", "exception"])
async def test_provider_verification_failure_leaves_payment_state_unchanged(
    client, auth_headers, db_session, monkeypatch, provider_failure
):
    order, product_id = await create_payment_order(client, auth_headers, db_session)
    before = await payment_state(db_session, order["id"], product_id)
    from app.payments.gateway import FlutterwaveAdapter

    private_detail = "private provider detail"
    private_key = "fixture-provider-key"
    requests = []
    if provider_failure == "exception":
        gateway = VerifiedWebhookGateway(error=RuntimeError(private_detail))
    else:
        gateway = FlutterwaveAdapter()
        gateway.secret_key = private_key

        async def verify_request(request):
            requests.append(request)
            if len(requests) > 1:
                return httpx.Response(200, json={"status": "success", "data": verified_transaction(order)})
            if provider_failure == "timeout":
                raise httpx.ReadTimeout(private_detail, request=request)
            if provider_failure == "connection":
                raise httpx.ConnectError(private_detail, request=request)
            return httpx.Response(503, json={"message": private_detail})

        async def accept_fixture_signature(payload, signature):
            return signature == "fixture-signature"

        async_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda: async_client(transport=httpx.MockTransport(verify_request)))
        monkeypatch.setattr(gateway, "verify_webhook", accept_fixture_signature)
    install_verification_gateway(monkeypatch, gateway)

    response = await send_payment_webhook(client, order_id=order["id"])

    assert response.status_code == 503
    assert private_detail not in response.text
    assert private_key not in response.text
    assert await payment_state(db_session, order["id"], product_id) == before

    if provider_failure == "exception":
        gateway.error = None
        gateway.verified = verified_transaction(order)
    retry = await send_payment_webhook(client, order_id=order["id"])
    assert retry.status_code == 200
    assert (await payment_state(db_session, order["id"], product_id))[0] == ("PAID", "12345")
    if provider_failure == "exception":
        assert gateway.verified_ids == [12345, 12345]
    else:
        assert len(requests) == 2
        for request in requests:
            assert request.url.path.endswith("/transactions/12345/verify")
            assert request.headers["Authorization"] == f"Bearer {private_key}"


@pytest.mark.asyncio
async def test_invalid_webhook_signature_never_reaches_payment_verification(
    client, auth_headers, db_session, monkeypatch
):
    order, product_id = await create_payment_order(client, auth_headers, db_session)
    before = await payment_state(db_session, order["id"], product_id)
    gateway = VerifiedWebhookGateway(verified_transaction(order))

    async def reject_signature(payload, signature):
        return False

    monkeypatch.setattr(gateway, "verify_webhook", reject_signature)
    install_verification_gateway(monkeypatch, gateway)
    response = await send_payment_webhook(client, order_id=order["id"])

    assert response.status_code == 401
    assert gateway.verified_ids == []
    assert await payment_state(db_session, order["id"], product_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["before-mutation", "order-mutation", "stock-hold", "outbox", "commit"])
async def test_webhook_processing_failure_rolls_back_and_can_be_retried(
    client, auth_headers, db_session, monkeypatch, failure
):
    from app.inventory import service as inventory_service
    from app.orders.models import Order, OrderStatus, OutboxEvent
    import app.payments.router as router

    order, product_id = await create_payment_order(client, auth_headers, db_session)
    order_id = order["id"]
    before = await payment_state(db_session, order_id, product_id)
    gateway = VerifiedWebhookGateway(verified_transaction(order))
    install_verification_gateway(monkeypatch, gateway)
    private_detail = "private database failure"

    async def fail_confirmation(db, order_id, reference):
        if failure == "order-mutation":
            saved_order = await db.get(Order, order_id)
            saved_order.status = OrderStatus.PAID
            saved_order.payment_reference = reference
        raise RuntimeError(private_detail)

    commit_hold = inventory_service.commit_hold

    async def fail_stock_hold(db, order_id, order_items):
        await commit_hold(db, order_id, order_items)
        raise RuntimeError(private_detail)

    def fail_write(*args):
        raise RuntimeError(private_detail)

    with monkeypatch.context() as faults:
        if failure in {"before-mutation", "order-mutation"}:
            faults.setattr(router, "confirm_payment", fail_confirmation)
        elif failure == "stock-hold":
            faults.setattr(inventory_service, "commit_hold", fail_stock_hold)
        else:
            target, hook = (OutboxEvent, "before_insert") if failure == "outbox" else (Session, "before_commit")
            event.listen(target, hook, fail_write)
        try:
            failed = await send_payment_webhook(client, order_id=order_id)
        finally:
            if failure in {"outbox", "commit"}:
                event.remove(target, hook, fail_write)

    assert failed.status_code == 503
    assert private_detail not in failed.text
    assert order_id not in failed.text
    assert await payment_state(db_session, order_id, product_id) == before

    retry = await send_payment_webhook(client, order_id=order_id)
    replay = await send_payment_webhook(client, order_id=order_id)
    assert retry.status_code == replay.status_code == 200
    assert gateway.verified_ids == [12345, 12345, 12345]
    saved_order, inventory, holds, outbox = await payment_state(db_session, order_id, product_id)
    assert saved_order == ("PAID", "12345")
    assert inventory == (0, 1)
    assert holds == [(1, "COMMITTED")]
    assert sum(entry.event_type == "order.paid" for entry in outbox) == 1


@pytest.mark.asyncio
async def test_replayed_and_concurrent_webhooks_commit_stock_and_outbox_once(
    client, auth_headers, monkeypatch, tmp_path
):
    from app.core.database import Base, configure_sqlite_engine
    from app.catalog.models import Category, Product
    from app.identity.models import User
    from app.inventory.models import HoldStatus, Inventory, StockHold
    from app.orders.models import Order, OrderItem, OrderStatus, OutboxEvent
    import app.payments.router as router

    database_path = tmp_path / "concurrent-payments.sqlite3"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    configure_sqlite_engine(test_engine.sync_engine)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    user_id, category_id, product_id, order_id, inventory_id = [str(uuid4()) for _ in range(5)]
    now = datetime.now(timezone.utc)
    order = {"id": order_id, "total": 112.5}
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as session:
        session.add_all([
            User(id=user_id, email="concurrency@example.test", name="Buyer", password_hash="test"),
            Category(id=category_id, slug="concurrent", name="Concurrent"),
            Product(id=product_id, sku="concurrent-1", name="Device", price=100, category_id=category_id),
            Inventory(id=inventory_id, product_id=product_id, quantity_total=10, quantity_held=1),
            Order(
                id=order_id, user_id=user_id, status=OrderStatus.PENDING_PAYMENT,
                subtotal=100, shipping_cost=12.5, total=112.5,
                shipping_name="Buyer", shipping_address="Kigali", shipping_city="Kigali",
            ),
            OrderItem(
                id=str(uuid4()), order_id=order_id, product_id=product_id,
                product_name="Device", product_sku="concurrent-1", quantity=1,
                unit_price=100, line_total=100,
            ),
            StockHold(
                id=str(uuid4()), inventory_id=inventory_id, order_id=order_id,
                quantity=1, status=HoldStatus.ACTIVE,
                expires_at=now + timedelta(minutes=30),
            ),
        ])
        await session.commit()

    Session = async_sessionmaker(test_engine, expire_on_commit=False)

    monkeypatch.setattr(router, "async_session_factory", Session)
    gateway = VerifiedWebhookGateway(verified_transaction(order))
    install_verification_gateway(monkeypatch, gateway)

    responses = await asyncio.gather(
        send_payment_webhook(client, order_id=order["id"]),
        send_payment_webhook(client, order_id=order["id"]),
    )
    replay = await send_payment_webhook(client, order_id=order["id"])
    async with Session() as session:
        saved_order = await session.get(Order, order_id)
        inventory = (await session.execute(select(Inventory).where(Inventory.product_id == product_id))).scalar_one()
        hold = (await session.execute(select(StockHold).where(StockHold.order_id == order_id))).scalar_one()
        outbox_count = (await session.execute(select(OutboxEvent))).scalars().all()

    assert all(response.status_code == 200 for response in [*responses, replay])
    assert saved_order.status == OrderStatus.PAID
    assert saved_order.payment_reference == "12345"
    assert (inventory.quantity_held, inventory.quantity_committed) == (0, 1)
    assert hold.status == HoldStatus.COMMITTED
    assert sum(event.event_type == "order.paid" for event in outbox_count) == 1
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_verified_transaction_cannot_be_reused_for_another_order(
    client, auth_headers, db_session, monkeypatch
):
    first, first_product_id = await create_payment_order(client, auth_headers, db_session)
    second, second_product_id = await create_payment_order(
        client, auth_headers, db_session, product_id=first_product_id
    )
    gateway = VerifiedWebhookGateway(verified_transaction(first, transaction_id=12345))
    install_verification_gateway(monkeypatch, gateway)
    first_response = await send_payment_webhook(client, order_id=first["id"])
    before = await payment_state(db_session, second["id"], second_product_id)
    gateway.verified = verified_transaction(second, transaction_id=12345)

    response = await send_payment_webhook(client, order_id=second["id"])

    assert first_response.status_code == 200
    assert response.status_code == 200
    assert await payment_state(db_session, second["id"], second_product_id) == before


@pytest.mark.asyncio
async def test_cancelled_order_is_not_reactivated_by_verified_payment(
    client, auth_headers, db_session, monkeypatch
):
    from sqlalchemy import update
    from app.orders.models import Order, OrderStatus

    order, product_id = await create_payment_order(client, auth_headers, db_session)
    await db_session.execute(update(Order).where(Order.id == order["id"]).values(status=OrderStatus.CANCELLED))
    await db_session.commit()
    before = await payment_state(db_session, order["id"], product_id)
    gateway = VerifiedWebhookGateway(verified_transaction(order))
    install_verification_gateway(monkeypatch, gateway)

    response = await send_payment_webhook(client, order_id=order["id"])

    assert response.status_code == 200
    assert await payment_state(db_session, order["id"], product_id) == before


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
