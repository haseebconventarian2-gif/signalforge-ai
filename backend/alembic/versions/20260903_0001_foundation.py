"""Create foundation tables.

Revision ID: 20260903_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_configurations",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("strategy", sa.JSON(), nullable=False),
        sa.Column("risk", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_configurations"),
        sa.UniqueConstraint("version", name="uq_agent_configurations_version"),
    )
    op.create_table(
        "system_controls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("desired_state", sa.String(length=32), nullable=False),
        sa.Column(
            "kill_switch_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("changed_by", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_system_controls"),
    )
    op.create_table(
        "agent_runs",
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidates_discovered", sa.Integer(), server_default="0", nullable=False),
        sa.Column("candidates_approved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("orders_submitted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id"],
            ["agent_configurations.id"],
            name="fk_agent_runs_configuration_id_agent_configurations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs"),
    )
    op.create_index("ix_agent_runs_configuration_id", "agent_runs", ["configuration_id"])
    op.create_table(
        "journal_events",
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_journal_events_run_id_agent_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_journal_events"),
    )
    op.create_index("ix_journal_events_created_at", "journal_events", ["created_at"])
    op.create_index("ix_journal_events_correlation_id", "journal_events", ["correlation_id"])
    op.create_index("ix_journal_events_run_id", "journal_events", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_journal_events_run_id", table_name="journal_events")
    op.drop_index("ix_journal_events_correlation_id", table_name="journal_events")
    op.drop_index("ix_journal_events_created_at", table_name="journal_events")
    op.drop_table("journal_events")
    op.drop_index("ix_agent_runs_configuration_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_table("system_controls")
    op.drop_table("agent_configurations")
