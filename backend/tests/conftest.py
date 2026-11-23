import os
from pathlib import Path

from dotenv import load_dotenv
from tests.db_isolation import configure_test_database, guarded_schema_change, IsolationError

# A test-only, ignored file; resolve independently of pytest's working directory.
load_dotenv(Path(__file__).resolve().parents[1] / ".env.test", override=False)
configure_test_database()

os.environ["JWT_SECRET_KEY"] = "unit-test-only-jwt-signing-secret-32-plus-characters"
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import engine, async_session_factory, Base
from app.core.security import hash_password
from app.identity.models import User


@pytest_asyncio.fixture(autouse=True)
async def isolated_security_cache(monkeypatch):
    """Exercise security controls with a fresh, test-only Redis implementation."""
    from fakeredis.aioredis import FakeRedis
    from app.core import rate_limit, brute_force

    cache = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", cache)
    monkeypatch.setattr(brute_force, "_redis", cache)
    yield
    await cache.aclose()


@pytest_asyncio.fixture(scope="function")
async def setup_db():
    """Change schema only after verifying identity on that same connection."""
    try:
        async with engine.begin() as conn:
            await guarded_schema_change(conn, Base.metadata.create_all)
    except Exception:
        raise IsolationError("Test database setup failed; verify private test configuration and database access.") from None
    yield
    try:
        async with engine.begin() as conn:
            await guarded_schema_change(conn, Base.metadata.drop_all)
    except Exception:
        raise IsolationError("Test database teardown failed; no unverified schema cleanup is permitted.") from None
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(setup_db):
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session(setup_db):
    """Database session for testing."""
    async with async_session_factory() as session:
        yield session
        await session.close()


@pytest_asyncio.fixture
async def test_user(db_session):
    """Create a test user."""
    user = User(
        email="test@example.com",
        name="Test User",
        password_hash=hash_password("testpass123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    # Release the fixture transaction before the HTTP client uses the database.
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session):
    """Create an admin user."""
    user = User(
        email="admin@example.com",
        name="Admin User",
        password_hash=hash_password("adminpass123"),
        is_active=True,
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    # Release the fixture transaction before the HTTP client uses the database.
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def auth_headers(client, test_user):
    """Get authentication headers for test user."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "testpass123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_headers(client, admin_user):
    """Get authentication headers for admin user."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "adminpass123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
