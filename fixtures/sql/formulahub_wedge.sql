-- FormulaHub LOCAL wedge — Mac / CI Postgres DDL
-- DB: formulahub_wedge
-- Classification: LOCAL only — not LIVE_EXTERNAL
--
-- Apply:
--   psql -d formulahub_wedge -f fixtures/sql/formulahub_wedge.sql
--   # or via scripts/START-POSTGRES.command

CREATE TABLE IF NOT EXISTS customers_wedge (
    customer_id   text NOT NULL,
    email         text,
    signup_date   text,
    loaded_at     text,
    PRIMARY KEY (customer_id)
);

COMMENT ON TABLE customers_wedge IS
  'LOCAL_PROVEN wedge target (Mac Homebrew Postgres). Not a cloud LIVE table.';
