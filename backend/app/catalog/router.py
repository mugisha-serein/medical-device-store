from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.catalog.models import Category, Product
from app.catalog.schemas import (
    CategoryResponse,
    ProductCreate,
    ProductUpdate,
    ProductResponse,
)

router = APIRouter(prefix="/catalog", tags=["Catalog"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


# ── Public endpoints ──────────────────────────────────────────────────────────

@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).order_by(Category.name))
    return [CategoryResponse.model_validate(c) for c in result.scalars().all()]


@router.get("/categories/{slug}", response_model=CategoryResponse)
async def get_category(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).where(Category.slug == slug))
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found.")
    return CategoryResponse.model_validate(category)


@router.get("/products", response_model=list[ProductResponse])
async def list_products(
    category: Optional[str] = Query(None, description="Filter by category slug"),
    search: Optional[str] = Query(None, description="Search in name and description"),
    sort_by: str = Query("name", description="Sort field: name, price, created_at"),
    sort_order: str = Query("asc", description="Sort direction: asc, desc"),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(Product).where(Product.is_active == True)

    if category:
        query = query.join(Category).where(Category.slug == category)

    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Product.name.ilike(search_term),
                Product.description.ilike(search_term),
            )
        )

    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)

    # Sorting
    sort_column = {
        "name": Product.name,
        "price": Product.price,
        "created_at": Product.created_at,
    }.get(sort_by, Product.name)

    if sort_order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    products = result.scalars().all()

    response = []
    for p in products:
        stock = p.inventory.quantity_available if p.inventory else 0
        response.append(
            ProductResponse(
                id=p.id,
                sku=p.sku,
                name=p.name,
                description=p.description,
                price=p.price,
                category_id=p.category_id,
                category_name=p.category.name if p.category else None,
                specs=p.specs,
                requires_prescription=p.requires_prescription,
                certification_refs=p.certification_refs,
                is_active=p.is_active,
                stock=stock,
                created_at=p.created_at,
            )
        )
    return response


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Product).where(Product.id == product_id, Product.is_active == True))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    stock = product.inventory.quantity_available if product.inventory else 0
    return ProductResponse(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        price=product.price,
        category_id=product.category_id,
        category_name=product.category.name if product.category else None,
        specs=product.specs,
        requires_prescription=product.requires_prescription,
        certification_refs=product.certification_refs,
        is_active=product.is_active,
        stock=stock,
        created_at=product.created_at,
    )


# ── Admin endpoints ───────────────────────────────────────────────────────────

@router.post("/admin/products", response_model=ProductResponse, status_code=201)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # Verify category exists
    cat_result = await db.execute(select(Category).where(Category.id == data.category_id))
    if not cat_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Invalid category_id.")

    # Check duplicate SKU
    sku_result = await db.execute(select(Product).where(Product.sku == data.sku))
    if sku_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A product with this SKU already exists.")

    product = Product(**data.model_dump())
    db.add(product)
    await db.flush()

    return ProductResponse(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        price=product.price,
        category_id=product.category_id,
        category_name=None,
        specs=product.specs,
        requires_prescription=product.requires_prescription,
        certification_refs=product.certification_refs,
        is_active=product.is_active,
        stock=0,
        created_at=product.created_at,
    )


@router.put("/admin/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    update_data = data.model_dump(exclude_unset=True)
    if "category_id" in update_data:
        cat_result = await db.execute(
            select(Category).where(Category.id == update_data["category_id"])
        )
        if not cat_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Invalid category_id.")

    for field, value in update_data.items():
        setattr(product, field, value)

    db.add(product)
    await db.flush()

    stock = product.inventory.quantity_available if product.inventory else 0
    return ProductResponse(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        price=product.price,
        category_id=product.category_id,
        category_name=product.category.name if product.category else None,
        specs=product.specs,
        requires_prescription=product.requires_prescription,
        certification_refs=product.certification_refs,
        is_active=product.is_active,
        stock=stock,
        created_at=product.created_at,
    )


@router.delete("/admin/products/{product_id}", status_code=204)
async def delete_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    product.is_active = False
    db.add(product)
