-- Schema for Phase 0/1 measurement storage
CREATE TABLE IF NOT EXISTS targets (
    id SERIAL PRIMARY KEY,
    target_ip INET NOT NULL UNIQUE,
    source TEXT DEFAULT 'static',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS measurements (
    id SERIAL PRIMARY KEY,
    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    tool TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    raw_output TEXT,
    enriched BOOLEAN NOT NULL DEFAULT FALSE,
    enriched_at TIMESTAMPTZ,
    graph_built BOOLEAN NOT NULL DEFAULT FALSE,
    graph_built_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS hops (
    id SERIAL PRIMARY KEY,
    measurement_id INTEGER NOT NULL REFERENCES measurements(id) ON DELETE CASCADE,
    hop_number INTEGER NOT NULL,
    hop_ip INET,
    rtt_ms DOUBLE PRECISION,
    asn INTEGER,
    prefix CIDR,
    org_name TEXT,
    country_code VARCHAR(2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_measurements_target_id ON measurements(target_id);
CREATE INDEX IF NOT EXISTS idx_hops_measurement_id ON hops(measurement_id);
CREATE INDEX IF NOT EXISTS idx_hops_hop_number ON hops(measurement_id, hop_number);
CREATE INDEX IF NOT EXISTS idx_hops_asn ON hops(asn);
