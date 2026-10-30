"""Track one expiring connection notice without renewing its deadline."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_notice_campaigns",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closure_reason", sa.String(30), nullable=True),
        sa.Column("targets", sa.JSON(), nullable=False),
        sa.Column("resolved_user_ids", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("account_notice_campaigns")
