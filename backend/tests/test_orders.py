import pytest
from httpx import AsyncClient

from app.catalog.models import Category, Product
from app.inventory.models import Inventory


async def seed_product(db_session) -> tuple[str, str]:
    """Seed a category, product, and inventory. Returns (category_id, product_id)."""
    cat = Category(slug="diagnostic", name="Diagnostic")
    db_session.add(cat)
    await db_session.flush()

    product = Product(sku="dg-001", name="Stethoscope", price=100.00, category_id=cat.id)
    db_session.add(product)
    await db_session.flush()

    inventory = Inventory(product_id=product.id, quantity_total=10)
    db_session.add(inventory)
    await db_session.commit()

    return cat.id, product.id


@pytest.mark.asyncio
async def test_place_order(client: AsyncClient, auth_headers: dict, db_session):
    cat_id, product_id = await seed_product(db_session)

    response = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 2}],
            "shipping": {
                "name": "John Doe",
                "address": "123 Medical Rd",
                "city": "Kigali",
                "postal": "00000",
                "phone": "+250788000000",
            },
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending_payment"
    assert data["subtotal"] == 200.00
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_order_server_side_pricing(client: AsyncClient, auth_headers: dict, db_session):
    """Server must re-price items, not trust client-sent prices."""
    cat_id, product_id = await seed_product(db_session)

    response = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 1}],
            "shipping": {
                "name": "John Doe",
                "address": "123 Medical Rd",
                "city": "Kigali",
                "phone": "+250788000000",
            },
        },
    )
    assert response.status_code == 201
    # Server-computed price must match product price, not anything client sent
    assert response.json()["subtotal"] == 100.00


@pytest.mark.asyncio
async def test_order_insufficient_stock(client: AsyncClient, auth_headers: dict, db_session):
    cat_id, product_id = await seed_product(db_session)

    response = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 100}],
            "shipping": {
                "name": "John Doe",
                "address": "123 Medical Rd",
                "city": "Kigali",
                "phone": "+250788000000",
            },
        },
    )
    assert response.status_code == 409  # Insufficient stock


@pytest.mark.asyncio
async def test_list_orders(client: AsyncClient, auth_headers: dict, db_session):
    cat_id, product_id = await seed_product(db_session)

    # Place an order
    await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 1}],
            "shipping": {
                "name": "John Doe",
                "address": "123 Medical Rd",
                "city": "Kigali",
                "phone": "+250788000000",
            },
        },
    )

    response = await client.get("/api/v1/orders", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_get_order_detail(client: AsyncClient, auth_headers: dict, db_session):
    cat_id, product_id = await seed_product(db_session)

    place_response = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 1}],
            "shipping": {
                "name": "John Doe",
                "address": "123 Medical Rd",
                "city": "Kigali",
                "phone": "+250788000000",
            },
        },
    )
    order_id = place_response.json()["id"]

    response = await client.get(f"/api/v1/orders/{order_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == order_id


@pytest.mark.asyncio
async def test_cancel_order(client: AsyncClient, auth_headers: dict, db_session):
    cat_id, product_id = await seed_product(db_session)

    place_response = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 1}],
            "shipping": {
                "name": "John Doe",
                "address": "123 Medical Rd",
                "city": "Kigali",
                "phone": "+250788000000",
            },
        },
    )
    order_id = place_response.json()["id"]

    response = await client.post(f"/api/v1/orders/{order_id}/cancel", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    # Verify stock was restored
    inv_response = await client.get(f"/api/v1/inventory/products/{product_id}")
    assert inv_response.json()["quantity_held"] == 0


@pytest.mark.asyncio
async def test_cannot_cancel_twice(client: AsyncClient, auth_headers: dict, db_session):
    cat_id, product_id = await seed_product(db_session)

    place_response = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product_id, "quantity": 1}],
            "shipping": {
                "name": "John Doe",
                "address": "123 Medical Rd",
                "city": "Kigali",
                "phone": "+250788000000",
            },
        },
    )
    order_id = place_response.json()["id"]

    # First cancel succeeds
    await client.post(f"/api/v1/orders/{order_id}/cancel", headers=auth_headers)

    # Second cancel fails
    response = await client.post(f"/api/v1/orders/{order_id}/cancel", headers=auth_headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_shipping_free_over_threshold(client: AsyncClient, auth_headers: dict, db_session):
    cat = Category(slug="homecare", name="Homecare")
    db_session.add(cat)
    await db_session.flush()

    product = Product(sku="hc-001", name="Bed Frame", price=300.00, category_id=cat.id)
    db_session.add(product)
    await db_session.flush()

    inventory = Inventory(product_id=product.id, quantity_total=5)
    db_session.add(inventory)
    await db_session.commit()

    response = await client.post(
        "/api/v1/orders",
        headers=auth_headers,
        json={
            "items": [{"product_id": product.id, "quantity": 1}],
            "shipping": {
                "name": "John Doe",
                "address": "123 Medical Rd",
                "city": "Kigali",
                "phone": "+250788000000",
            },
        },
    )
    assert response.status_code == 201
    assert response.json()["shipping_cost"] == 0.0  # Existing free-shipping threshold: RWF 250
    assert response.json()["total"] == 300.00


@pytest.mark.asyncio
async def test_created_order_serializes_without_an_open_session(db_session, test_user):
    """Serialization must not require implicit async ORM I/O."""
    from app.orders.service import place_order
    from app.orders.schemas import OrderCreate, OrderResponse

    _, product_id = await seed_product(db_session)
    data = OrderCreate.model_validate({
        "items": [{"product_id": product_id, "quantity": 2}],
        "shipping": {"name": "Buyer", "address": "Kigali", "city": "Kigali", "phone": "+250788000000"},
    })
    order = await place_order(db_session, test_user.id, data)
    await db_session.commit()
    await db_session.close()
    response = OrderResponse.model_validate(order)
    assert response.items[0].product_id == product_id
    assert response.items[0].quantity == 2
    assert response.total == 212.50


@pytest.mark.asyncio
async def test_failed_order_rolls_back_all_stock_and_outbox_changes(client, auth_headers, db_session):
    from sqlalchemy import text
    _, product_id = await seed_product(db_session)
    response = await client.post("/api/v1/orders", headers=auth_headers, json={
        "items": [{"product_id": product_id, "quantity": 6}, {"product_id": product_id, "quantity": 6}],
        "shipping": {"name": "Buyer", "address": "Kigali", "city": "Kigali", "phone": "+250788000000"},
    })
    assert response.status_code == 409
    for table in ("orders", "order_items", "stock_holds", "outbox_events"):
        assert await db_session.scalar(text(f"SELECT count(*) FROM {table}")) == 0
    assert await db_session.scalar(text("SELECT quantity_held FROM inventory")) == 0


@pytest.mark.asyncio
async def test_order_lifecycle_preserves_items_and_ownership(client, auth_headers, db_session):
    from app.core.security import create_access_token
    from app.identity.models import User
    _, product_id = await seed_product(db_session)
    other = User(email="other@example.com", name="Other", password_hash="unused-test-hash")
    db_session.add(other)
    await db_session.commit()
    other_headers = {"Authorization": "Bearer " + create_access_token({"sub": other.id})}
    payload = {
        "items": [{"product_id": product_id, "quantity": 2}],
        "shipping": {"name": "Buyer", "address": "Kigali", "city": "Kigali", "phone": "+250788000000"},
    }
    placed = await client.post("/api/v1/orders", headers=auth_headers, json=payload)
    assert placed.status_code == 201
    data = placed.json()
    order_id = data["id"]
    assert data["items"][0]["unit_price"] == 100.0
    detail = await client.get(f"/api/v1/orders/{order_id}", headers=auth_headers)
    assert detail.json() == data
    listed = await client.get("/api/v1/orders", headers=auth_headers)
    assert listed.json() == [data]
    assert (await client.get(f"/api/v1/orders/{order_id}", headers=other_headers)).status_code == 404
    assert (await client.post(f"/api/v1/orders/{order_id}/cancel", headers=other_headers)).status_code == 404
    assert (await client.get("/api/v1/orders", headers=other_headers)).json() == []
    cancelled = await client.post(f"/api/v1/orders/{order_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["items"] == data["items"]
    assert cancelled.json()["total"] == data["total"]
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_listing_orders_batches_item_loading(client, auth_headers, db_session):
    from sqlalchemy import event
    from app.core.database import engine
    _, product_id = await seed_product(db_session)
    payload = {
        "items": [{"product_id": product_id, "quantity": 1}],
        "shipping": {"name": "Buyer", "address": "Kigali", "city": "Kigali", "phone": "+250788000000"},
    }
    for _ in range(5):
        assert (await client.post("/api/v1/orders", headers=auth_headers, json=payload)).status_code == 201
    item_queries = []

    def count_items(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM order_items" in statement:
            item_queries.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count_items)
    try:
        response = await client.get("/api/v1/orders", headers=auth_headers)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_items)
    assert response.status_code == 200
    assert len(response.json()) == 5
    assert 1 <= len(item_queries) <= 2
