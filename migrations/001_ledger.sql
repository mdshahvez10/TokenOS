-- Apply once via PostgreSQL image initialization, or scripts/migrate.py.
CREATE TABLE IF NOT EXISTS tokenos_runs (
    run_id UUID PRIMARY KEY,
    spec JSONB NOT NULL,
    budget_tokens BIGINT NOT NULL CHECK (budget_tokens > 0),
    spent_tokens BIGINT NOT NULL DEFAULT 0 CHECK (spent_tokens >= 0),
    reserved_tokens BIGINT NOT NULL DEFAULT 0 CHECK (reserved_tokens >= 0),
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tokenos_reservations (
    run_id UUID NOT NULL REFERENCES tokenos_runs(run_id),
    reservation_id UUID NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reserved','dispatched','unknown','settled','released')),
    snapshot JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, reservation_id)
);
CREATE INDEX IF NOT EXISTS tokenos_unresolved_idx
    ON tokenos_reservations(updated_at) WHERE state IN ('dispatched','unknown');

CREATE TABLE IF NOT EXISTS tokenos_events (
    event_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES tokenos_runs(run_id),
    reservation_id UUID,
    version BIGINT NOT NULL CHECK (version >= 0),
    kind TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    UNIQUE (run_id, version),
    FOREIGN KEY (run_id, reservation_id)
        REFERENCES tokenos_reservations(run_id, reservation_id)
);
-- No constraint spent+reserved<=budget: unexpected real usage must remain recordable.
-- The application service enforces admission; the run row serializes all mutations.
