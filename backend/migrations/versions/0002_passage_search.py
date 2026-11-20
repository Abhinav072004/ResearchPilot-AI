"""Add a PostgreSQL passage index for lexical candidate selection."""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute("CREATE INDEX ix_passage_search ON passages USING gin (to_tsvector('simple', text))")


def downgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP INDEX ix_passage_search")
