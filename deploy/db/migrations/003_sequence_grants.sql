-- 003_sequence_grants.sql — bigserial INSERTs need USAGE on the sequence;
-- ALTER DEFAULT PRIVILEGES in 01-init.sh covered TABLES only (§3.3).
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO kinetic_agent;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO kinetic_agent;