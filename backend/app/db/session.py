from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        # Background jobs write from their own threads; wait on a lock instead of failing.
        _engine = create_engine(
            f"sqlite:///{settings.db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def migrate(engine: Engine) -> None:
    """Create missing tables and add missing nullable columns to existing ones.

    SQLite's create_all never alters an existing table, so new columns added to the models
    in later phases are added here. Columns are only ever added, never changed or dropped.
    """
    from sqlalchemy import inspect, text

    from app.db.models import Base

    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    kind = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {kind}'))


def get_session() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    with _SessionLocal() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session for jobs and scripts, outside a request."""
    yield from get_session()


# FastAPI dependency: `session: DbSession` in a route signature gets a request-scoped session.
DbSession = Annotated[Session, Depends(get_session)]
