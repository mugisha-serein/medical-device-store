from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pathlib import Path
from sqlalchemy import event, text

from app.core.config import get_settings

settings = get_settings()

def configure_sqlite_engine(sync_engine):
    """Enforce references and serialize read/modify/write transactions."""
    if sync_engine.dialect.name != "sqlite":
        raise ValueError("SQLite is required for the application database.")

    @event.listens_for(sync_engine, "connect")
    def on_connect(connection, _):
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    @event.listens_for(sync_engine, "begin")
    def on_begin(connection):
        # SQLite ignores SELECT FOR UPDATE. Lock before inventory reads instead.
        connection.exec_driver_sql("BEGIN IMMEDIATE")


engine = create_async_engine(settings.DATABASE_URL, echo=False, hide_parameters=True)
configure_sqlite_engine(engine.sync_engine)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def check_database_ready(check_engine=engine):
    """Refuse implicit empty replacements or an unapplied migration at startup."""
    from alembic.script import ScriptDirectory

    path = check_engine.url.database
    if not path or path == ":memory:" or not Path(path).is_file():
        raise RuntimeError("Persistent database is missing; initialize explicitly after reviewing existing data.")
    heads = set(ScriptDirectory(str(Path(__file__).resolve().parents[2] / "alembic")).get_heads())
    try:
        async with check_engine.connect() as connection:
            applied = set((await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars())
            if applied != heads:
                raise RuntimeError("Migration revision mismatch")
    except Exception:
        raise RuntimeError("Database migration is missing or invalid; run the reviewed initialization command.") from None


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
