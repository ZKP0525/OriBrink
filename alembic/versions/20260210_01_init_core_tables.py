"""init core week2 tables

Revision ID: 20260210_01
Revises: 
Create Date: 2026-02-10 15:10:00

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260210_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create schema if not exists md")
    op.execute("create schema if not exists sys")

    op.create_table(
        "symbol_master",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("delist_date", sa.Date(), nullable=True),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("is_st", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("symbol", name="uq_symbol_master_symbol"),
        schema="md",
    )
    op.create_index("idx_symbol_master_active", "symbol_master", ["is_active"], unique=False, schema="md")
    op.create_index("idx_symbol_master_sector", "symbol_master", ["sector"], unique=False, schema="md")

    op.create_table(
        "symbol_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(12, 4), nullable=False),
        sa.Column("high", sa.Numeric(12, 4), nullable=False),
        sa.Column("low", sa.Numeric(12, 4), nullable=False),
        sa.Column("close", sa.Numeric(12, 4), nullable=False),
        sa.Column("prev_close", sa.Numeric(12, 4), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("turnover_rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("adj_factor", sa.Numeric(16, 8), nullable=True),
        sa.Column("is_limit_up", sa.Boolean(), nullable=True),
        sa.Column("is_limit_down", sa.Boolean(), nullable=True),
        sa.Column("data_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("symbol", "trade_date", "data_version", name="uq_symbol_daily_symbol_date_version"),
        schema="md",
    )
    op.create_index("idx_daily_symbol_date", "symbol_daily", ["symbol", "trade_date"], unique=False, schema="md")
    op.create_index("idx_daily_date", "symbol_daily", ["trade_date"], unique=False, schema="md")
    op.create_index("idx_daily_version", "symbol_daily", ["data_version"], unique=False, schema="md")

    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("run_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("run_key", name="uq_job_runs_run_key"),
        schema="sys",
    )
    op.create_index("idx_job_runs_name_time", "job_runs", ["job_name", "started_at"], unique=False, schema="sys")


def downgrade() -> None:
    op.drop_index("idx_job_runs_name_time", table_name="job_runs", schema="sys")
    op.drop_table("job_runs", schema="sys")

    op.drop_index("idx_daily_version", table_name="symbol_daily", schema="md")
    op.drop_index("idx_daily_date", table_name="symbol_daily", schema="md")
    op.drop_index("idx_daily_symbol_date", table_name="symbol_daily", schema="md")
    op.drop_table("symbol_daily", schema="md")

    op.drop_index("idx_symbol_master_sector", table_name="symbol_master", schema="md")
    op.drop_index("idx_symbol_master_active", table_name="symbol_master", schema="md")
    op.drop_table("symbol_master", schema="md")
