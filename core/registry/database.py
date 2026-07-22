from __future__ import annotations

import os
from pathlib import Path
from sqlite3 import Connection as SQLite3Connection

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import ROOT

DB_PATH = os.environ.get("KH_DATABASE_URL")
if DB_PATH and DB_PATH.startswith("sqlite:///"):
    DB_PATH = DB_PATH.replace("sqlite:///", "")
elif DB_PATH and DB_PATH.startswith("postgresql"):
    pass
elif DB_PATH:
    DB_PATH = DB_PATH
else:
    DB_PATH = str(ROOT / "data" / "registry.db")

_engine = create_engine(
    f"sqlite:///{DB_PATH}" if not DB_PATH.startswith("postgresql") else DB_PATH,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in DB_PATH else {},
)


@event.listens_for(_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, SQLite3Connection):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


class Base(DeclarativeBase):
    pass


def get_session() -> Session:
    return _SessionLocal()


def init_db():
    Base.metadata.create_all(bind=_engine)
