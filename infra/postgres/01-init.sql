-- Runs once, on first initialisation of an empty data volume.
-- Alembic owns the schema; this only prepares extensions it depends on.

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Trigram index support for fast ILIKE '%INFY%' instrument search.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Query statistics — the first thing worth having when a scan gets slow.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
