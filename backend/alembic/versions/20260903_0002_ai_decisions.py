"""Add schema-validated AI decision audit records.

Revision ID: 20260903_0002
Revises: 20260903_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_0002"
down_revision: str | None = "20260903_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_decisions",
        sa.Column("symbol", sa.String(length=15), nullable=False),
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("candidate_snapshot", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("provider_response_id", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_characters", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_decisions"),
    )
    op.create_index(
        "ix_ai_decisions_candidate_fingerprint", "ai_decisions", ["candidate_fingerprint"]
    )
    op.create_index("ix_ai_decisions_symbol_created_at", "ai_decisions", ["symbol", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_decisions_symbol_created_at", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_candidate_fingerprint", table_name="ai_decisions")
    op.drop_table("ai_decisions")
