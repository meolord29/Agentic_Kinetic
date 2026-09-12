-- 001_init.sql — P0 schema (derived from data-model.md; auth tables deferred to P1)
CREATE TABLE IF NOT EXISTS app.users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name  text NOT NULL,
  language      text NOT NULL DEFAULT 'en',
  timezone      text NOT NULL DEFAULT 'Europe/Vienna',
  registered_at timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.badge_defs (
  n     int PRIMARY KEY,
  label text NOT NULL,
  copy  text NOT NULL
);

CREATE TABLE IF NOT EXISTS app.gamification_state (
  user_id    uuid PRIMARY KEY REFERENCES app.users(id),
  checkins   int NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.checkins (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES app.users(id),
  kind            text NOT NULL DEFAULT 'dose',
  answer          text NOT NULL,
  channel         text NOT NULL DEFAULT 'chip',
  dose_at         timestamptz NOT NULL DEFAULT now(),
  logged_at       timestamptz NOT NULL DEFAULT now(),
  client_event_id text UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS app.care_questions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES app.users(id),
  text        text NOT NULL, -- VERBATIM
  status      text NOT NULL DEFAULT 'draft', -- draft|approved|waiting|answered
  answer      text,
  answered_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.temperature_requests (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES app.users(id),
  reason         text NOT NULL DEFAULT 'scheduled',
  requested_at   timestamptz NOT NULL DEFAULT now(),
  fulfilled_at   timestamptz,
  cancelled_at   timestamptz
);

CREATE TABLE IF NOT EXISTS app.bookings (
  id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id  uuid NOT NULL REFERENCES app.users(id),
  test_name text NOT NULL,
  for_date date NOT NULL,
  fasting  bool NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.reminders (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES app.users(id),
  kind       text NOT NULL,
  text       text NOT NULL,
  fire_at    timestamptz NOT NULL,
  delivered_at timestamptz,
  acked_at   timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.audit_log (
  id         bigserial PRIMARY KEY,
  actor_type text NOT NULL,
  actor_id   text,
  user_id    uuid,
  action     text NOT NULL,
  fields     text[] NOT NULL DEFAULT '{}',
  purpose    text NOT NULL,
  at         timestamptz NOT NULL DEFAULT now()
);

INSERT INTO app.badge_defs (n, label, copy) VALUES
  (1,   'First check-in', 'Your first honest check-in. That is a clear picture for your care team.'),
  (7,   'First week',     'Seven honest check-ins. That is a clear picture for your care team.'),
  (30,  'First month',    'Thirty honest check-ins. That''s a clear picture for your care team.'),
  (100, 'Hundred club',   'A hundred honest check-ins. That is a clear picture for your care team.'),
  (365, 'First year',     'A year of honest check-ins. That is a clear picture for your care team.')
ON CONFLICT (n) DO NOTHING;

-- P0 demo patient: Elena, 31 check-ins (matches the prototype's default scenario)
INSERT INTO app.users (id, display_name, registered_at)
VALUES ('00000000-0000-4000-8000-0000000000e1', 'Elena', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO app.gamification_state (user_id, checkins)
VALUES ('00000000-0000-4000-8000-0000000000e1', 31)
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO app.care_questions (user_id, text, status)
VALUES ('00000000-0000-4000-8000-0000000000e1', 'Did you start any new medicine this week?', 'waiting')
ON CONFLICT DO NOTHING;
