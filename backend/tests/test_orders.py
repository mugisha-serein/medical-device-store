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
    assert response.json()["shipping_cost"] == 0.0  # Free shipping over $250
    assert response.json()["total"] == 300.00
