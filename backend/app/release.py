import logging

from alembic import command
from alembic.config import Config

from agents.supervisor import checkpointer
from app.config import settings


def migrate():
    command.upgrade(Config("alembic.ini"), "head")
    if settings().database_url.startswith("postgresql+psycopg://"):
        with checkpointer() as saver:
            saver.setup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
