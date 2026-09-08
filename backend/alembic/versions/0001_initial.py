"""Initial persisted auth, source, events and webhook state."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("tokens", sa.Text(), nullable=False),
    )
    op.create_table(
        "auth_flows",
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column("binding", sa.String(64), nullable=False),
        sa.Column("verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("ticket", sa.String(64), unique=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id")),
        sa.Column("consumed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("spreadsheet_id", sa.String(200), nullable=False),
        sa.Column("sheet_gid", sa.String(40), nullable=False),
        sa.Column("programme", sa.String(200), nullable=False),
        sa.Column("section", sa.String(100), nullable=False),
        sa.Column("calendar_id", sa.String(300)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("pending", sa.Boolean(), nullable=False),
        sa.Column("fingerprint", sa.String(64)),
        sa.Column("last_synced_at", sa.DateTime()),
        sa.Column("last_error", sa.Text()),
        sa.Column("event_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "watches",
        sa.Column("channel_id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("resource_id", sa.String(300)),
        sa.Column("expiration", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_watches_source_id", "watches", ["source_id"])
    op.create_table(
        "events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("row_id", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("source_id", "row_id"),
    )
    op.create_index("ix_events_source_id", "events", ["source_id"])
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_sync_runs_source_id", "sync_runs", ["source_id"])


def downgrade():
    for table in ("sync_runs", "events", "watches", "sources", "sessions", "auth_flows", "users"):
        op.drop_table(table)
