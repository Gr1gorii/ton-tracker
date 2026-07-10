"""Add proof-checked jetton contract relationship evidence.

Revision ID: 20260710_0009
Revises: 20260710_0008
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0009"
down_revision = "20260710_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Jetton contract verification migration requires online validation."
        )
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    required = {"wallet_ingestion_runs", "wallet_balance_snapshots"}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            f"Revision 0009 requires exact revision 0008 tables; missing={missing}."
        )
    table = "wallet_jetton_contract_verifications"
    if table in tables:
        raise RuntimeError(
            "Revision 0009 refuses a pre-existing jetton verification table."
        )
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("wallet_ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "balance_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("wallet_balance_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("contract_version", sa.String(56), nullable=False),
        sa.Column("verifier_name", sa.String(32), nullable=False),
        sa.Column("verifier_version", sa.String(48), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("trust_level", sa.Integer(), nullable=False),
        sa.Column("anchor_workchain", sa.Integer(), nullable=False),
        sa.Column("anchor_shard", sa.String(24), nullable=False),
        sa.Column("anchor_seqno", sa.Integer(), nullable=False),
        sa.Column("anchor_root_hash", sa.String(64), nullable=False),
        sa.Column("anchor_file_hash", sa.String(64), nullable=False),
        sa.Column("owner_account_canonical", sa.String(76), nullable=False),
        sa.Column("jetton_wallet_account_canonical", sa.String(76), nullable=False),
        sa.Column("jetton_master_account_canonical", sa.String(76), nullable=False),
        sa.Column("asset_identity_key", sa.String(128), nullable=False),
        sa.Column("wallet_balance_base_units", sa.String(80), nullable=False),
        sa.Column("total_supply_base_units", sa.String(80), nullable=False),
        sa.Column("mintable", sa.Boolean(), nullable=False),
        sa.Column("wallet_code_boc_hex", sa.Text(), nullable=False),
        sa.Column("wallet_data_boc_hex", sa.Text(), nullable=False),
        sa.Column("master_code_boc_hex", sa.Text(), nullable=False),
        sa.Column("master_data_boc_hex", sa.Text(), nullable=False),
        sa.Column("wallet_code_hash", sa.String(64), nullable=False),
        sa.Column("wallet_data_hash", sa.String(64), nullable=False),
        sa.Column("master_code_hash", sa.String(64), nullable=False),
        sa.Column("master_data_hash", sa.String(64), nullable=False),
        sa.Column("jetton_content_hash", sa.String(64), nullable=False),
        sa.Column("evidence_digest_sha256", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_wallet_jetton_contract_verification_relation",
        table,
        [
            "run_id",
            "jetton_wallet_account_canonical",
            "jetton_master_account_canonical",
            "contract_version",
        ],
        unique=True,
    )
    op.create_index(
        "ix_wallet_jetton_contract_verification_identity",
        table,
        ["asset_identity_key"],
    )
    op.create_index(
        "ix_wallet_jetton_contract_verification_digest",
        table,
        ["evidence_digest_sha256"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Jetton contract verification downgrade would discard proof evidence."
    )
