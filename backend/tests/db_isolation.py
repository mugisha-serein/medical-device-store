"""Fail-closed, test-only SQLite selection and connection checks."""
import os
import sys
from sqlalchemy import text

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


class IsolationError(RuntimeError):
    """Errors must not expose private connection configuration."""


def validate_test_url(value):
    if value != TEST_DATABASE_URL:
        raise IsolationError("TEST_DATABASE_URL must select the isolated SQLite in-memory database.")
    return value


def configure_test_database():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        raise IsolationError("TEST_DATABASE_URL is required; application database fallback is forbidden.")
    validate_test_url(value)
    initialized = sys.modules.get("app.core.database")
    if initialized is not None and str(initialized.engine.url) != TEST_DATABASE_URL:
        raise IsolationError("Application engine was already initialized with an unsafe test target.")
    os.environ["DATABASE_URL"] = value
    os.environ["DATABASE_URL_SYNC"] = "sqlite:///:memory:"
    os.environ["DEBUG"] = "false"


async def verify_connection(conn):
    try:
        result = await conn.execute(text("PRAGMA database_list"))
        databases = [tuple(row) for row in result.all()]
    except Exception:
        raise IsolationError("Test database identity could not be verified; schema changes forbidden.") from None
    if databases not in ([(0, "main", "")], [(0, "main", ""), (1, "temp", "")]):
        raise IsolationError("Connection is not an isolated in-memory database; schema changes forbidden.")


async def guarded_schema_change(conn, operation):
    await verify_connection(conn)
    await conn.run_sync(operation)
