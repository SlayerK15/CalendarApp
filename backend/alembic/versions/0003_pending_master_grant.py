"""Bind master reader grants at the first-party ticket exchange."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("auth_flows", sa.Column("pending_tokens", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("auth_flows", "pending_tokens")
