"""Explicit SQLite initialization and online backup/restore to new files.

Run from backend: python -m scripts.sqlite_database --help
"""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


def initialize_database(url: str, *, create: bool = False) -> None:
    """Upgrade a versioned database; creating a new file requires --create."""
    from app.core.database import configure_sqlite_engine

    parsed = make_url(url)
    if parsed.drivername != "sqlite" or not parsed.database or parsed.database == ":memory:" or parsed.query:
        raise RuntimeError("Initialization requires a persistent SQLite database.")
    target = Path(parsed.database).resolve()
    if not target.exists():
        if not create:
            raise RuntimeError("Database is missing; use --create only for an intentional new installation.")
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as source:
        names = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if names and "alembic_version" not in names:
            raise RuntimeError("Existing unversioned database requires a reviewed migration; initialization refused.")

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
    configure_sqlite_engine(engine)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def copy_database(source: Path, destination: Path) -> None:
    """Use SQLite's backup API, including committed WAL pages; never overwrite."""
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if not source.is_file():
        raise RuntimeError("SQLite source file does not exist.")
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("Destination already exists; choose a new file.")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        if original.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("SQLite source integrity check failed.")
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with closing(sqlite3.connect(destination.as_uri() + "?mode=rw", uri=True)) as copied:
            original.backup(copied)
            if copied.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("Copied SQLite database integrity check failed.")
            if copied.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Copied SQLite database contains invalid foreign keys.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    initialize = actions.add_parser("initialize", help="Upgrade the configured database without resetting data")
    initialize.add_argument("--create", action="store_true", help="Explicitly permit creating a missing SQLite file")
    for action in ("backup", "restore"):
        operation = actions.add_parser(action, help="Copy a SQLite source to a new destination file")
        operation.add_argument("source", type=Path)
        operation.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "initialize":
            from app.core.config import get_settings
            initialize_database(get_settings().DATABASE_URL_SYNC, create=args.create)
        else:
            copy_database(args.source, args.destination)
    except Exception:
        parser.exit(1, "SQLite operation failed; verify the source, migration state and destination permissions. No existing destination is overwritten.\n")
    print("SQLite operation completed.")


if __name__ == "__main__":
    main()
