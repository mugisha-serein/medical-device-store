"""Disposable-file tests for explicit initialization, readiness and recovery."""
import asyncio
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.sqlite_database import initialize_database, copy_database
from app.core.database import check_database_ready, configure_sqlite_engine


def sync_url(path):
    return "sqlite:///" + path.as_posix()


def test_initialization_requires_explicit_creation(tmp_path):
    path = tmp_path / "application.sqlite3"
    with pytest.raises(RuntimeError, match="--create"):
        initialize_database(sync_url(path))
    assert not path.exists()


def test_repeat_initialization_preserves_records(tmp_path):
    path = tmp_path / "application.sqlite3"
    initialize_database(sync_url(path), create=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO categories (id, slug, name, created_at) VALUES ('saved', 'saved', 'Saved', CURRENT_TIMESTAMP)")
        conn.commit()
    initialize_database(sync_url(path))
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT name FROM categories WHERE id='saved'").fetchone() == ("Saved",)
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_initialization_rejects_an_unversioned_existing_database(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE saved (id INTEGER)")
        conn.commit()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="unversioned"):
        initialize_database(sync_url(path))
    assert path.read_bytes() == before


def test_backup_includes_committed_wal_data_and_restore_uses_new_file(tmp_path):
    source, backup, restored = [tmp_path / name for name in ("live.sqlite3", "backup.sqlite3", "restored.sqlite3")]
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE saved (value TEXT)")
        conn.execute("INSERT INTO saved VALUES ('preserved')")
        conn.commit()
        assert Path(str(source) + "-wal").exists()
        copy_database(source, backup)
        assert conn.execute("SELECT value FROM saved").fetchone() == ("preserved",)
    copy_database(backup, restored)
    with closing(sqlite3.connect(restored)) as conn:
        assert conn.execute("SELECT value FROM saved").fetchone() == ("preserved",)
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_backup_never_overwrites_existing_destination(tmp_path):
    source, target = tmp_path / "source.sqlite3", tmp_path / "target.sqlite3"
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("CREATE TABLE data (id INTEGER)")
    target.write_bytes(b"preserve existing backup")
    with pytest.raises(RuntimeError, match="exists"):
        copy_database(source, target)
    assert target.read_bytes() == b"preserve existing backup"


def test_backup_missing_source_does_not_create_empty_database(tmp_path):
    source, target = tmp_path / "missing.sqlite3", tmp_path / "backup.sqlite3"
    with pytest.raises(RuntimeError, match="source"):
        copy_database(source, target)
    assert not source.exists()
    assert not target.exists()


@pytest.mark.asyncio
async def test_startup_rejects_missing_database_without_creating_it(tmp_path):
    path = tmp_path / "missing.sqlite3"
    engine = create_async_engine("sqlite+aiosqlite:///" + path.as_posix())
    configure_sqlite_engine(engine.sync_engine)
    try:
        with pytest.raises(RuntimeError, match="initialize"):
            await check_database_ready(engine)
        assert not path.exists()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_startup_rejects_uninitialized_existing_database(tmp_path):
    path = tmp_path / "empty.sqlite3"
    path.touch()
    engine = create_async_engine("sqlite+aiosqlite:///" + path.as_posix())
    configure_sqlite_engine(engine.sync_engine)
    try:
        with pytest.raises(RuntimeError, match="migration"):
            await check_database_ready(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_startup_rejects_an_ephemeral_application_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        with pytest.raises(RuntimeError, match="Persistent"):
            await check_database_ready(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_foreign_keys_enabled_on_each_new_connection(tmp_path):
    from sqlalchemy import text
    from sqlalchemy.pool import NullPool
    engine = create_async_engine("sqlite+aiosqlite:///" + (tmp_path / "connections.sqlite3").as_posix(), poolclass=NullPool)
    configure_sqlite_engine(engine.sync_engine)
    try:
        for _ in range(2):
            async with engine.connect() as connection:
                assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        await engine.dispose()


def test_startup_and_persistence_across_process_restarts(tmp_path):
    path = tmp_path / "restart.sqlite3"
    initialize_database(sync_url(path), create=True)
    backend = Path(__file__).resolve().parents[1]
    env = dict(os.environ, DATABASE_URL="sqlite+aiosqlite:///" + path.as_posix(), DATABASE_URL_SYNC=sync_url(path))
    env.pop("TEST_DATABASE_URL", None)
    code = """
import asyncio, sys
from sqlalchemy import text
from app.main import app
from app.core.database import engine
from httpx import AsyncClient, ASGITransport
async def run():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/api/v1/health')).status_code == 200
        async with engine.begin() as conn:
            if sys.argv[1] == 'write':
                await conn.execute(text("INSERT INTO categories (id, slug, name, created_at) VALUES ('restart', 'restart', 'Restart', CURRENT_TIMESTAMP)"))
            else:
                assert await conn.scalar(text("SELECT count(*) FROM categories WHERE id='restart'")) == 1
asyncio.run(run())
"""
    for action in ("write", "read"):
        result = subprocess.run([sys.executable, "-c", code, action], cwd=backend, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, "Application lifecycle failed in disposable restart test"


@pytest.mark.asyncio
async def test_sql_logging_hides_bound_parameters(setup_db, caplog):
    from app.core.database import engine
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    assert engine.sync_engine.hide_parameters is True
    assert engine.echo is False
    sentinel = "synthetic-private-sql-parameter"
    async with engine.begin() as connection:
        with pytest.raises(OperationalError) as error:
            await connection.execute(text("SELECT :private FROM deliberately_missing_table"), {"private": sentinel})
    assert sentinel not in str(error.value)
    assert sentinel not in caplog.text


def test_sqlite_files_and_sidecars_are_ignored_by_git():
    root = Path(__file__).resolve().parents[2]
    files = ["backend/probe.sqlite3", "backend/probe.sqlite3-wal", "backend/probe.sqlite3-shm", "backend/probe.sqlite3-journal"]
    result = subprocess.run(["git", "check-ignore", "--", *files], cwd=root, capture_output=True, text=True, check=True)
    assert set(result.stdout.splitlines()) == set(files)


def test_no_database_drivers_or_database_service_remain():
    root = Path(__file__).resolve().parents[2]
    requirements = (root / "backend/requirements.txt").read_text(encoding="utf-8").lower()
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8").lower()
    assert "aiosqlite==" in requirements
    assert all(driver not in requirements for driver in ("asyncpg", "psycopg"))
    assert "postgres:" not in compose
    assert "postgres_data:" not in compose
