from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DB_URL

_engine_kwargs = {}
if DB_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}

engine = create_engine(DB_URL, **_engine_kwargs)


# SQLite-only: enable WAL + 30s busy-timeout so the orchestrator (background
# pipeline thread) and the email_sync poller / FastAPI request handlers can
# write concurrently without "database is locked" errors. WAL gives concurrent
# readers + one writer with no blocking on reads; busy-timeout has SQLite wait
# up to 30s for a write lock instead of failing immediately.
if DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_concurrency(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA wal_autocheckpoint=1000")
        finally:
            cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
