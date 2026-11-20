from alembic import context

from app import models
from app.db import Base, engine


def owned_object(obj, name, type_, reflected, compare_to):
    # The checkpoint saver and dedicated FTS migration own these database objects.
    if type_ == "table" and name in {"checkpoints", "checkpoint_writes", "checkpoint_blobs", "checkpoint_migrations"}:
        return False
    return not (type_ == "index" and name == "ix_passage_search")


def run():
    if context.is_offline_mode():
        context.configure(url=engine.url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, include_object=owned_object)
        with context.begin_transaction():
            context.run_migrations()


run()
