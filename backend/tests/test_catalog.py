import pytest
from httpx import AsyncClient

from app.catalog.models import Category, Product
from app.inventory.models import Inventory


@pytest.mark.asyncio
async def test_list_categories(client: AsyncClient, db_session):
    # Seed categories
    cat = Category(slug="diagnostic", name="Diagnostic Equipment", tagline="Test")
    db_session.add(cat)
    await db_session.commit()

    response = await client.get("/api/v1/catalog/categories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["slug"] == "diagnostic"


@pytest.mark.asyncio
async def test_list_products(client: AsyncClient, db_session):
    # Seed category and product
    cat = Category(slug="diagnostic", name="Diagnostic Equipment")
    db_session.add(cat)
    await db_session.flush()

    product = Product(
        sku="test-001",
        name="Test Product",
        price=99.99,
        category_id=cat.id,
        specs={"Weight": "100g"},
    )
    db_session.add(product)
    await db_session.flush()

    inventory = Inventory(
        product_id=product.id,
        quantity_total=50,
    )
    db_session.add(inventory)
    await db_session.commit()

    response = await client.get("/api/v1/catalog/products")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_list_products_filter_by_category(client: AsyncClient, db_session):
    cat1 = Category(slug="diagnostic", name="Diagnostic")
    cat2 = Category(slug="mobility", name="Mobility")
    db_session.add_all([cat1, cat2])
    await db_session.flush()

    p1 = Product(sku="dg-001", name="Stethoscope", price=100, category_id=cat1.id)
    p2 = Product(sku="mb-001", name="Wheelchair", price=300, category_id=cat2.id)
    db_session.add_all([p1, p2])
    await db_session.commit()

    response = await client.get("/api/v1/catalog/products?category=diagnostic")
    assert response.status_code == 200
    data = response.json()
    assert all(p["category_name"] == "Diagnostic" for p in data)


@pytest.mark.asyncio
async def test_list_products_search(client: AsyncClient, db_session):
    cat = Category(slug="diagnostic", name="Diagnostic")
    db_session.add(cat)
    await db_session.flush()

    p1 = Product(sku="dg-001", name="Digital Stethoscope", price=100, category_id=cat.id)
    p2 = Product(sku="dg-002", name="LED Otoscope", price=50, category_id=cat.id)
    db_session.add_all([p1, p2])
    await db_session.commit()

    response = await client.get("/api/v1/catalog/products?search=stethoscope")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "Stethoscope" in data[0]["name"]


@pytest.mark.asyncio
async def test_get_product(client: AsyncClient, db_session):
    cat = Category(slug="diagnostic", name="Diagnostic")
    db_session.add(cat)
    await db_session.flush()

    product = Product(sku="dg-001", name="Test Product", price=99.99, category_id=cat.id)
    db_session.add(product)
    await db_session.flush()

    inventory = Inventory(product_id=product.id, quantity_total=10)
    db_session.add(inventory)
    await db_session.commit()

    response = await client.get(f"/api/v1/catalog/products/{product.id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Product"
    assert response.json()["stock"] == 10


@pytest.mark.asyncio
async def test_get_product_not_found(client: AsyncClient):
    response = await client.get("/api/v1/catalog/products/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_create_product(client: AsyncClient, admin_headers: dict, db_session):
    cat = Category(slug="diagnostic", name="Diagnostic")
    db_session.add(cat)
    await db_session.commit()

    response = await client.post(
        "/api/v1/catalog/admin/products",
        headers=admin_headers,
        json={
            "sku": "new-001",
            "name": "New Product",
            "price": 150.00,
            "category_id": cat.id,
            "specs": {"Weight": "200g"},
        },
    )
    assert response.status_code == 201
    assert response.json()["sku"] == "new-001"


@pytest.mark.asyncio
async def test_non_admin_cannot_create_product(client: AsyncClient, auth_headers: dict, db_session):
    cat = Category(slug="diagnostic", name="Diagnostic")
    db_session.add(cat)
    await db_session.commit()

    response = await client.post(
        "/api/v1/catalog/admin/products",
        headers=auth_headers,
        json={
            "sku": "new-002",
            "name": "Should Fail",
            "price": 100,
            "category_id": cat.id,
        },
    )
    assert response.status_code == 403
