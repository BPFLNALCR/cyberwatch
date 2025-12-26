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

-- ASN metadata table for aggregated ASN intelligence
CREATE TABLE IF NOT EXISTS asns (
    asn INTEGER PRIMARY KEY,
    org_name TEXT,
    country_code VARCHAR(2),
    prefix_count INTEGER DEFAULT 0,
    neighbor_count INTEGER DEFAULT 0,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT DEFAULT 'cymru',  -- cymru, peeringdb, ripe, ipinfo, etc.
    -- PeeringDB specific fields
    peeringdb_id INTEGER,
    facility_count INTEGER DEFAULT 0,
    peering_policy TEXT,  -- 'Open', 'Selective', 'Restrictive', 'No'
    traffic_levels TEXT,  -- Comma-separated: '100-200Gbps', '>1Tbps', etc.
    irr_as_set TEXT,
    -- Aggregate statistics
    total_measurements INTEGER DEFAULT 0,
    avg_rtt_ms DOUBLE PRECISION,
    -- Metadata
    enrichment_attempted_at TIMESTAMPTZ,
    enrichment_completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_asns_org_name ON asns(org_name);
CREATE INDEX IF NOT EXISTS idx_asns_country_code ON asns(country_code);
CREATE INDEX IF NOT EXISTS idx_asns_last_seen ON asns(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_asns_prefix_count ON asns(prefix_count DESC);
CREATE INDEX IF NOT EXISTS idx_asns_neighbor_count ON asns(neighbor_count DESC);
