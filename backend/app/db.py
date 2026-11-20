from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


url = settings().database_url
if url.startswith("sqlite:///") and not url.endswith(":memory:"):
    Path(url.removeprefix("sqlite:///")).absolute().parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
Session = sessionmaker(engine, expire_on_commit=False)

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")


def db_session():
    with Session() as db:
        yield db
