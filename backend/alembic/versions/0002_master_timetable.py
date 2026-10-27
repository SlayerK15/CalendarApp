"""Separate master reader credentials and a shared parsed timetable cache."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("auth_flows", sa.Column("purpose", sa.String(30), nullable=False, server_default="login"))
    op.create_table(
        "master_timetable_accounts",
        sa.Column("email", sa.String(320), primary_key=True),
        sa.Column("subject", sa.String(64), nullable=False),
        sa.Column("tokens", sa.Text(), nullable=False),
    )
    op.create_table(
        "timetable_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("timetable_snapshots")
    op.drop_table("master_timetable_accounts")
    op.drop_column("auth_flows", "purpose")
