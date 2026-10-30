"""Persist administrator-triggered updates across all connected calendars."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sync_batches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_table("sync_batches")
