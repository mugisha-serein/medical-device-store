"""SQLite configuration, isolation, migration and integrity regressions."""
import os
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import text
from tests.db_isolation import IsolationError, configure_test_database, validate_test_url, guarded_schema_change


def test_valid_test_selection(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DATABASE_URL", "unused-application-value")
    configure_test_database()
    assert os.environ["DATABASE_URL"] == "sqlite+aiosqlite:///:memory:"
    assert os.environ["DEBUG"] == "false"


def test_missing_test_configuration(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(IsolationError, match="TEST_DATABASE_URL is required"):
        configure_test_database()


def test_preinitialized_file_engine_is_rejected(monkeypatch):
    import sys
    from types import SimpleNamespace
    from sqlalchemy.engine import make_url
    monkeypatch.setenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    module = SimpleNamespace(engine=SimpleNamespace(url=make_url("sqlite+aiosqlite:///application.sqlite3")))
    monkeypatch.setitem(sys.modules, "app.core.database", module)
    with pytest.raises(IsolationError, match="already initialized"):
        configure_test_database()


@pytest.mark.parametrize("value", ["", "invalid", "sqlite:///app.sqlite3", "sqlite+aiosqlite:///app.sqlite3", "postgresql://localhost/activelifemedical", "sqlite+aiosqlite:///:memory:?uri=true"])
def test_unsafe_test_urls_rejected(value):
    with pytest.raises(IsolationError):
        validate_test_url(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("databases", [[(0,"main","application.sqlite3")], [], [(0,"main",""),(2,"attached","other.sqlite3")]])
async def test_schema_changes_blocked_when_identity_is_unsafe(databases):
    conn = AsyncMock()
    result = Mock()
    result.all.return_value = databases
    conn.execute.return_value = result
    with pytest.raises(IsolationError):
        await guarded_schema_change(conn, Mock())
    conn.run_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_inaccessible_database_fails_closed():
    conn = AsyncMock()
    conn.execute.side_effect = OSError("private details")
    with pytest.raises(IsolationError, match="identity could not be verified") as error:
        await guarded_schema_change(conn, Mock())
    assert "private" not in str(error.value)
    conn.run_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_schema_setup_and_teardown(setup_db):
    from app.core.database import engine
    from tests.db_isolation import verify_connection
    async with engine.begin() as conn:
        await verify_connection(conn)
        assert await conn.scalar(text("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='users'")) == 1


def test_sqlite_defaults_and_matching_sync_url(monkeypatch):
    from app.core.config import Settings
    from sqlalchemy.engine import make_url
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "unit-test-signing-key-abcdefghijklmnopqrstuvwxyz")
    settings = Settings(_env_file=None)
    assert make_url(settings.DATABASE_URL).drivername == "sqlite+aiosqlite"
    assert make_url(settings.DATABASE_URL).database == make_url(settings.DATABASE_URL_SYNC).database


@pytest.mark.parametrize("async_url,sync_url", [
    ("postgresql://localhost/activelifemedical", "sqlite:///app.sqlite3"),
    ("sqlite+aiosqlite:///one.sqlite3", "sqlite:///other.sqlite3"),
    ("sqlite+aiosqlite:///one.sqlite3?uri=true", "sqlite:///one.sqlite3"),
])
def test_application_configuration_requires_matching_sqlite_targets(monkeypatch, async_url, sync_url):
    from app.core.config import Settings
    from pydantic import ValidationError
    monkeypatch.setenv("JWT_SECRET_KEY", "unit-test-signing-key-abcdefghijklmnopqrstuvwxyz")
    with pytest.raises(ValidationError, match="SQLite"):
        Settings(_env_file=None, DATABASE_URL=async_url, DATABASE_URL_SYNC=sync_url)


def test_backend_environment_template_is_usable(monkeypatch):
    from pathlib import Path
    from app.core.config import Settings
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    settings = Settings(
        _env_file=Path(__file__).resolve().parents[1] / ".env.example",
        JWT_SECRET_KEY="unit-test-signing-key-abcdefghijklmnopqrstuvwxyz",
    )
    assert settings.DATABASE_URL.startswith("sqlite+aiosqlite:")


@pytest.mark.asyncio
@pytest.mark.parametrize("reuse_request_identity", [False, True], ids=["rapid", "reused-id"])
async def test_isolated_cache_preserves_login_rate_limit(client, monkeypatch, reuse_request_identity):
    from types import SimpleNamespace

    from app.core import rate_limit

    path = "/api/v1/auth/login"
    first_ip, other_ip = "192.0.2.10", "192.0.2.11"
    first_key, other_key = f"rl:{first_ip}:{path}", f"rl:{other_ip}:{path}"
    start = 1_700_000_000
    now = start
    monkeypatch.setattr(rate_limit, "_TRUSTED_PROXIES", {"127.0.0.1", "192.0.2.20"})
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(time=lambda: now))
    if reuse_request_identity:
        monkeypatch.setattr(rate_limit, "id", lambda request: 42, raising=False)
    cache = await rate_limit._get_redis()

    async def login(index, ip=first_ip):
        return await client.post(
            path,
            headers={"X-Forwarded-For": f"192.0.2.99, {ip}, 192.0.2.20"},
            json={"email": f"absent{index}@example.com", "password": "unit-test-invalid-password"},
        )

    responses = [await login(index) for index in range(6)]
    assert [response.status_code for response in responses] == [401] * 5 + [429]
    assert responses[-1].headers["Retry-After"] == "60"
    records = await cache.zrange(first_key, 0, -1, withscores=True)
    assert len({member for member, _ in records}) == 6
    assert {score for _, score in records} == {start}

    assert (await login(6, ip=other_ip)).status_code == 401
    other_records = await cache.zrange(other_key, 0, -1, withscores=True)
    assert len(other_records) == 1
    assert await cache.zrange(first_key, 0, -1, withscores=True) == records

    now = start + 59
    assert (await login(7)).status_code == 429
    assert await cache.zcard(first_key) == 7

    now = start + 60
    assert (await login(8)).status_code == 401
    surviving = await cache.zrange(first_key, 0, -1, withscores=True)
    assert [score for _, score in surviving] == [start + 59, start + 60]
    assert await cache.zrange(other_key, 0, -1, withscores=True) == other_records


@pytest.mark.asyncio
async def test_untrusted_login_peer_ignores_forwarded_addresses(client, monkeypatch):
    from app.core import rate_limit

    bypass = "192.0.2.20"
    monkeypatch.setattr(rate_limit, "_TRUSTED_PROXIES", {bypass})
    monkeypatch.setattr(rate_limit, "_BYPASS_IPS", {bypass}, raising=False)
    path = "/api/v1/auth/login"
    responses = []
    for index, claimed_ip in enumerate([bypass, *(f"192.0.2.{n}" for n in range(21, 26))]):
        responses.append(await client.post(
            path,
            headers={"X-Forwarded-For": claimed_ip, "Forwarded": f"for={claimed_ip}"},
            json={"email": f"absent{index}@example.com", "password": "unit-test-invalid-password"},
        ))

    assert [response.status_code for response in responses] == [401] * 5 + [429]
    cache = await rate_limit._get_redis()
    assert await cache.keys(f"rl:*:{path}") == [f"rl:127.0.0.1:{path}"]
    assert await cache.zcard(f"rl:127.0.0.1:{path}") == 6


@pytest.mark.parametrize(("headers", "expected"), [
    ([], "192.0.2.20"),
    ([(b"forwarded", b"for=192.0.2.10")], "192.0.2.20"),
    ([(b"x-forwarded-for", b"")], "192.0.2.20"),
    ([(b"x-forwarded-for", b"192.0.2.10, ")], "192.0.2.20"),
    ([(b"x-forwarded-for", b"invalid, 192.0.2.10")], "192.0.2.20"),
    ([(b"x-forwarded-for", b"192.0.2.10:123")], "192.0.2.20"),
    ([(b"x-forwarded-for", b"192.0.2.10"), (b"x-forwarded-for", b"192.0.2.11")], "192.0.2.20"),
    ([(b"x-forwarded-for", b"192.0.2.21")], "192.0.2.20"),
    ([(b"x-forwarded-for", b"192.0.2.10")], "192.0.2.10"),
    ([(b"x-forwarded-for", b"192.0.2.99, ::ffff:192.0.2.10, 192.0.2.21")], "192.0.2.10"),
])
def test_trusted_proxy_forwarding_chain(headers, expected, monkeypatch):
    from starlette.requests import Request

    from app.core import rate_limit

    monkeypatch.setattr(rate_limit, "_TRUSTED_PROXIES", {"192.0.2.20", "192.0.2.21"})
    request = Request({"type": "http", "client": ("192.0.2.20", 1234), "headers": headers})
    assert rate_limit._get_client_ip(request) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("peer", "forwarded", "counted_ip"), [
    ("192.0.2.10", None, None),
    ("192.0.2.20", None, "192.0.2.20"),
    ("192.0.2.20", "192.0.2.10", "192.0.2.10"),
])
async def test_rate_limit_bypass_requires_an_exempt_direct_client(peer, forwarded, counted_ip, monkeypatch):
    from starlette.requests import Request
    from starlette.responses import Response

    from app.core import rate_limit

    monkeypatch.setattr(rate_limit, "_TRUSTED_PROXIES", {"192.0.2.20"})
    monkeypatch.setattr(rate_limit, "_BYPASS_IPS", {"192.0.2.10", "192.0.2.20"})
    path = "/api/v1/auth/login"
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    request = Request({
        "type": "http", "client": (peer, 1234), "path": path, "headers": headers,
    })
    response = Response()
    await rate_limit.RateLimiter("5/minute")(request, response)

    cache = await rate_limit._get_redis()
    assert await cache.keys(f"rl:*:{path}") == ([f"rl:{counted_ip}:{path}"] if counted_ip else [])
    if counted_ip:
        assert response.headers["X-RateLimit-Limit"] == "5"
        assert response.headers["X-RateLimit-Remaining"] == "4"
        assert "X-RateLimit-Reset" in response.headers


@pytest.mark.asyncio
async def test_sqlite_foreign_keys_enforced(setup_db):
    from app.core.database import engine
    from sqlalchemy.exc import IntegrityError
    async with engine.begin() as conn:
        assert await conn.scalar(text("PRAGMA foreign_keys")) == 1
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            await conn.execute(text("INSERT INTO products (id, sku, name, price, category_id, created_at, updated_at, requires_prescription, is_active) VALUES ('invalid', 'invalid', 'invalid', 1, 'missing', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, 1)"))


@pytest.mark.asyncio
async def test_timestamps_preserve_utc_after_reload(db_session, test_user):
    from datetime import timezone
    await db_session.refresh(test_user)
    assert test_user.created_at.tzinfo == timezone.utc


def test_sqlite_migration_round_trip(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings
    from pathlib import Path
    import sqlite3

    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "migration.sqlite3"
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + target.as_posix())
    monkeypatch.setenv("DATABASE_URL_SYNC", "sqlite:///" + target.as_posix())
    get_settings.cache_clear()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    try:
        command.upgrade(config, "head")
        with sqlite3.connect(target) as conn:
            assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='users'").fetchone()[0] == 1
        command.downgrade(config, "base")
        with sqlite3.connect(target) as conn:
            assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='users'").fetchone()[0] == 0
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_guard_preserves_existing_file_database(tmp_path):
    import sqlite3
    from sqlalchemy.ext.asyncio import create_async_engine
    target = tmp_path / "application.sqlite3"
    with sqlite3.connect(target) as conn:
        conn.execute("CREATE TABLE sentinel (value TEXT)")
        conn.execute("INSERT INTO sentinel VALUES ('preserve')")
    isolated = create_async_engine("sqlite+aiosqlite:///" + target.as_posix())
    try:
        async with isolated.begin() as conn:
            with pytest.raises(IsolationError):
                await guarded_schema_change(conn, lambda sync: sync.exec_driver_sql("DROP TABLE sentinel"))
        with sqlite3.connect(target) as conn:
            assert conn.execute("SELECT value FROM sentinel").fetchone() == ("preserve",)
    finally:
        await isolated.dispose()


@pytest.mark.asyncio
async def test_guarded_schema_is_removed_after_teardown():
    from sqlalchemy import MetaData, Table, Column, Integer
    from sqlalchemy.ext.asyncio import create_async_engine
    isolated = create_async_engine("sqlite+aiosqlite:///:memory:")
    metadata = MetaData()
    Table("probe", metadata, Column("id", Integer, primary_key=True))
    try:
        async with isolated.begin() as conn:
            await guarded_schema_change(conn, metadata.create_all)
            assert await conn.scalar(text("SELECT count(*) FROM sqlite_master WHERE name='probe'")) == 1
            await guarded_schema_change(conn, metadata.drop_all)
            assert await conn.scalar(text("SELECT count(*) FROM sqlite_master WHERE name='probe'")) == 0
    finally:
        await isolated.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["decrement", "hold"])
async def test_concurrent_stock_reservations_cannot_oversell(tmp_path, operation):
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.core.database import Base, configure_sqlite_engine
    from app.catalog.models import Category, Product
    from app.inventory.models import Inventory
    from app.inventory.service import decrement_stock, hold_stock
    from fastapi import HTTPException

    isolated = create_async_engine("sqlite+aiosqlite:///" + (tmp_path / "stock.sqlite3").as_posix())
    configure_sqlite_engine(isolated.sync_engine)
    sessions = async_sessionmaker(isolated, expire_on_commit=False)
    try:
        async with isolated.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            category = Category(slug="concurrency", name="Concurrency")
            session.add(category)
            await session.flush()
            product = Product(sku="concurrency", name="Concurrency", price=1, category_id=category.id)
            session.add(product)
            await session.flush()
            session.add(Inventory(product_id=product.id, quantity_total=1))
            await session.commit()

        async def reserve():
            async with sessions() as session:
                if operation == "hold":
                    try:
                        await hold_stock(session, product.id, "concurrency-order", 1)
                        result = True
                    except HTTPException as error:
                        assert error.status_code == 409
                        await session.rollback()
                        return False
                else:
                    result = await decrement_stock(session, product.id, 1)
                await asyncio.sleep(0.05)
                await session.commit()
                return result

        assert sorted(await asyncio.gather(reserve(), reserve())) == [False, True]
        async with isolated.begin() as conn:
            field = "quantity_held" if operation == "hold" else "quantity_committed"
            assert await conn.scalar(text(f"SELECT {field} FROM inventory")) == 1
    finally:
        await isolated.dispose()
