"""Baseline the complete v0.22.0 application schema.

Revision ID: 20260710_0001
Revises:
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260710_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pool_url", sa.String(), nullable=False),
        sa.Column("time_window", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_runs_id", "analysis_runs", ["id"], unique=False)

    op.create_table(
        "wallet_ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_address", sa.String(), nullable=False),
        sa.Column("time_window", sa.String(), nullable=False),
        sa.Column("custom_start", sa.DateTime(), nullable=True),
        sa.Column("custom_end", sa.DateTime(), nullable=True),
        sa.Column("data_mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_surfaces_json", sa.Text(), nullable=False),
        sa.Column("provider_summary_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wallet_ingestion_runs_id",
        "wallet_ingestion_runs",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_ingestion_runs_wallet_address",
        "wallet_ingestion_runs",
        ["wallet_address"],
        unique=False,
    )

    op.create_table(
        "wallet_transfers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(), nullable=True),
        sa.Column("logical_time", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=True),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("counterparty", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("source_status", sa.String(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["wallet_ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wallet_transfers_id", "wallet_transfers", ["id"], unique=False
    )
    op.create_index(
        "ix_wallet_transfers_logical_time",
        "wallet_transfers",
        ["logical_time"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_transfers_run_id",
        "wallet_transfers",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_transfers_tx_hash",
        "wallet_transfers",
        ["tx_hash"],
        unique=False,
    )

    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(), nullable=False),
        sa.Column("logical_time", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("fee_ton", sa.Numeric(38, 18), nullable=True),
        sa.Column("success", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("source_status", sa.String(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["wallet_ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wallet_transactions_id", "wallet_transactions", ["id"], unique=False
    )
    op.create_index(
        "ix_wallet_transactions_logical_time",
        "wallet_transactions",
        ["logical_time"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_transactions_run_id",
        "wallet_transactions",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_transactions_tx_hash",
        "wallet_transactions",
        ["tx_hash"],
        unique=False,
    )

    op.create_table(
        "wallet_swaps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("dex", sa.String(), nullable=True),
        sa.Column("token_in", sa.String(), nullable=True),
        sa.Column("amount_in", sa.Numeric(38, 18), nullable=True),
        sa.Column("token_out", sa.String(), nullable=True),
        sa.Column("amount_out", sa.Numeric(38, 18), nullable=True),
        sa.Column("estimated_usd", sa.Numeric(24, 8), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("source_status", sa.String(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["wallet_ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wallet_swaps_id", "wallet_swaps", ["id"], unique=False)
    op.create_index(
        "ix_wallet_swaps_run_id", "wallet_swaps", ["run_id"], unique=False
    )
    op.create_index(
        "ix_wallet_swaps_tx_hash", "wallet_swaps", ["tx_hash"], unique=False
    )

    op.create_table(
        "wallet_balance_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("balance", sa.Numeric(38, 18), nullable=True),
        sa.Column("balance_usd", sa.Numeric(24, 8), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("source_status", sa.String(), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["wallet_ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wallet_balance_snapshots_id",
        "wallet_balance_snapshots",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_balance_snapshots_run_id",
        "wallet_balance_snapshots",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "wallet_ingestion_warnings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["wallet_ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wallet_ingestion_warnings_id",
        "wallet_ingestion_warnings",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_ingestion_warnings_run_id",
        "wallet_ingestion_warnings",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading the baseline would destroy persisted application data and "
        "is intentionally unsupported. Restore a verified backup instead."
    )
