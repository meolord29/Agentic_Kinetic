-- 002_p1_mutations.sql — P1: mutation-path tables (§7.2 subset; no auth — single demo user, §3.1)

CREATE TABLE IF NOT EXISTS app.temperature_readings (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES app.users(id),
  bucket          text NOT NULL CHECK (bucket IN ('v36_5','v37_0','v37_5','v38_plus','not_measured')),
  reason          text NOT NULL DEFAULT 'scheduled' CHECK (reason IN ('scheduled','sick_day')),
  taken_at        timestamptz NOT NULL DEFAULT now(),
  client_event_id text UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS app.badges_earned (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id   uuid NOT NULL REFERENCES app.users(id),
  n         int NOT NULL REFERENCES app.badge_defs(n),
  earned_at timestamptz NOT NULL DEFAULT now()
);

-- kinetic_agent grants: role-level grants in 001 only covered tables existing then.
GRANT SELECT, INSERT, UPDATE ON app.temperature_readings, app.badges_earned TO kinetic_agent;