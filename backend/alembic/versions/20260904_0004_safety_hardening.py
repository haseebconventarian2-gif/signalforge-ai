"""Add concurrency protection for managed open positions.

Revision ID: 20260904_0004
Revises: 99458cd8c635
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260904_0004"
down_revision: str | None = "99458cd8c635"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("exit_reason", sa.String(length=32), nullable=True))
    op.add_column(
        "risk_decisions", sa.Column("contract_symbol", sa.String(length=64), nullable=True)
    )
    op.create_index(
        "uq_positions_open_contract",
        "positions",
        ["contract_symbol"],
        unique=True,
        postgresql_where="status = 'OPEN'",
    )


def downgrade() -> None:
    op.drop_index("uq_positions_open_contract", table_name="positions")
    op.drop_column("orders", "exit_reason")
    op.drop_column("risk_decisions", "contract_symbol")
