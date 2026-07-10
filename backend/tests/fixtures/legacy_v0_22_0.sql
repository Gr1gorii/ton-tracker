PRAGMA foreign_keys = ON;

CREATE TABLE analysis_runs (
    id INTEGER NOT NULL,
    pool_url VARCHAR NOT NULL,
    time_window VARCHAR NOT NULL,
    created_at DATETIME NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE wallet_ingestion_runs (
    id INTEGER NOT NULL,
    wallet_address VARCHAR NOT NULL,
    time_window VARCHAR NOT NULL,
    custom_start DATETIME,
    custom_end DATETIME,
    data_mode VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    requested_surfaces_json TEXT NOT NULL,
    provider_summary_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE wallet_transfers (
    id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    tx_hash VARCHAR,
    logical_time VARCHAR,
    timestamp DATETIME,
    asset VARCHAR NOT NULL,
    amount NUMERIC(38, 18),
    direction VARCHAR NOT NULL,
    counterparty VARCHAR,
    provider VARCHAR NOT NULL,
    source_status VARCHAR NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(run_id) REFERENCES wallet_ingestion_runs (id)
);

CREATE TABLE wallet_transactions (
    id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    tx_hash VARCHAR NOT NULL,
    logical_time VARCHAR,
    timestamp DATETIME,
    fee_ton NUMERIC(38, 18),
    success VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    source_status VARCHAR NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(run_id) REFERENCES wallet_ingestion_runs (id)
);

CREATE TABLE wallet_swaps (
    id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    tx_hash VARCHAR,
    timestamp DATETIME,
    dex VARCHAR,
    token_in VARCHAR,
    amount_in NUMERIC(38, 18),
    token_out VARCHAR,
    amount_out NUMERIC(38, 18),
    estimated_usd NUMERIC(24, 8),
    provider VARCHAR NOT NULL,
    source_status VARCHAR NOT NULL,
    raw_json TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(run_id) REFERENCES wallet_ingestion_runs (id)
);

CREATE TABLE wallet_balance_snapshots (
    id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    asset VARCHAR NOT NULL,
    balance NUMERIC(38, 18),
    balance_usd NUMERIC(24, 8),
    provider VARCHAR NOT NULL,
    source_status VARCHAR NOT NULL,
    snapshot_at DATETIME,
    raw_json TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(run_id) REFERENCES wallet_ingestion_runs (id)
);

CREATE TABLE wallet_ingestion_warnings (
    id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    severity VARCHAR NOT NULL,
    provider VARCHAR,
    message TEXT NOT NULL,
    evidence_key VARCHAR,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(run_id) REFERENCES wallet_ingestion_runs (id)
);

CREATE INDEX ix_analysis_runs_id ON analysis_runs (id);
CREATE INDEX ix_wallet_ingestion_runs_id ON wallet_ingestion_runs (id);
CREATE INDEX ix_wallet_ingestion_runs_wallet_address
    ON wallet_ingestion_runs (wallet_address);
CREATE INDEX ix_wallet_transfers_id ON wallet_transfers (id);
CREATE INDEX ix_wallet_transfers_run_id ON wallet_transfers (run_id);
CREATE INDEX ix_wallet_transfers_tx_hash ON wallet_transfers (tx_hash);
CREATE INDEX ix_wallet_transfers_logical_time ON wallet_transfers (logical_time);
CREATE INDEX ix_wallet_transactions_id ON wallet_transactions (id);
CREATE INDEX ix_wallet_transactions_run_id ON wallet_transactions (run_id);
CREATE INDEX ix_wallet_transactions_tx_hash ON wallet_transactions (tx_hash);
CREATE INDEX ix_wallet_transactions_logical_time
    ON wallet_transactions (logical_time);
CREATE INDEX ix_wallet_swaps_id ON wallet_swaps (id);
CREATE INDEX ix_wallet_swaps_run_id ON wallet_swaps (run_id);
CREATE INDEX ix_wallet_swaps_tx_hash ON wallet_swaps (tx_hash);
CREATE INDEX ix_wallet_balance_snapshots_id ON wallet_balance_snapshots (id);
CREATE INDEX ix_wallet_balance_snapshots_run_id
    ON wallet_balance_snapshots (run_id);
CREATE INDEX ix_wallet_ingestion_warnings_id ON wallet_ingestion_warnings (id);
CREATE INDEX ix_wallet_ingestion_warnings_run_id
    ON wallet_ingestion_warnings (run_id);

INSERT INTO analysis_runs (
    id, pool_url, time_window, created_at, result_json
) VALUES (
    41,
    'https://www.geckoterminal.com/ton/pools/legacy-fixture',
    '7d',
    '2026-06-01 09:00:00.000000',
    '{"fixture":"legacy","unicode":"данные"}'
);

INSERT INTO wallet_ingestion_runs (
    id,
    wallet_address,
    time_window,
    custom_start,
    custom_end,
    data_mode,
    status,
    requested_surfaces_json,
    provider_summary_json,
    created_at,
    updated_at
) VALUES (
    7,
    'EQlegacyWallet',
    'custom',
    '2026-05-01 00:00:00.000000',
    '2026-06-01 00:00:00.000000',
    'real',
    'success',
    '["transfers","transactions","swaps","balances"]',
    '{"message":"legacy fixture","provider_evidence":[],"unavailable_surfaces":[]}',
    '2026-06-01 09:01:00.000000',
    '2026-06-01 09:02:00.000000'
);

INSERT INTO wallet_transfers (
    id,
    run_id,
    tx_hash,
    logical_time,
    timestamp,
    asset,
    amount,
    direction,
    counterparty,
    provider,
    source_status,
    raw_json
) VALUES (
    101,
    7,
    'legacy-transfer-hash',
    '46000000000001',
    '2026-05-02 10:00:00.000000',
    'TON',
    123.450000000000000000,
    'in',
    'EQlegacyCounterparty',
    'tonapi',
    'live',
    '{"surface":"transfers","memo":"сохранить"}'
);

INSERT INTO wallet_transactions (
    id,
    run_id,
    tx_hash,
    logical_time,
    timestamp,
    fee_ton,
    success,
    provider,
    source_status,
    raw_json
) VALUES (
    102,
    7,
    'legacy-transaction-hash',
    '46000000000002',
    '2026-05-02 10:01:00.000000',
    0.004200000000000000,
    'success',
    'tonapi',
    'live',
    '{"surface":"transactions","sequence":2}'
);

INSERT INTO wallet_swaps (
    id,
    run_id,
    tx_hash,
    timestamp,
    dex,
    token_in,
    amount_in,
    token_out,
    amount_out,
    estimated_usd,
    provider,
    source_status,
    raw_json
) VALUES (
    103,
    7,
    'legacy-event-id',
    '2026-05-02 10:02:00.000000',
    'STON.fi',
    'TON',
    12.500000000000000000,
    'LEGACY',
    9876.543210000000000000,
    42.12500000,
    'tonapi',
    'live',
    '{"event_id":"legacy-event-id","token_out_address":"EQlegacyJetton"}'
);

INSERT INTO wallet_balance_snapshots (
    id,
    run_id,
    asset,
    balance,
    balance_usd,
    provider,
    source_status,
    snapshot_at,
    raw_json
) VALUES (
    104,
    7,
    'LEGACY',
    8765.432100000000000000,
    NULL,
    'tonapi',
    'live',
    '2026-06-01 09:01:30.000000',
    '{"jetton_address":"EQlegacyJetton","unpriced":true}'
);

INSERT INTO wallet_ingestion_warnings (
    id,
    run_id,
    severity,
    provider,
    message,
    evidence_key,
    created_at
) VALUES (
    105,
    7,
    'warning',
    NULL,
    'Legacy warning must survive migration.',
    'legacy_fixture',
    '2026-06-01 09:03:00.000000'
);
