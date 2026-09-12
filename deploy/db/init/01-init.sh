#!/bin/bash
# deploy/db/init/01-init.sh — runs once on first volume init (architecture §3.3).
# The migrator (POSTGRES_USER) owns the schema; kinetic_agent is the app's
# least-privilege role. P0 note: the runtime connects AS kinetic_agent (db module).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION migrator;

  CREATE ROLE kinetic_agent LOGIN PASSWORD '${DB_PASSWORD}'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;

  GRANT USAGE ON SCHEMA app TO kinetic_agent;
  ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE ON TABLES TO kinetic_agent;
  ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT SELECT, INSERT ON TABLES TO kinetic_agent; -- audit_log is append-only via role grants
EOSQL

echo "01-init.sh: kinetic_agent role created."
