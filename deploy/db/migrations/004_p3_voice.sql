-- 004_p3_voice.sql — P3: voice-chain tables (workflows 07/08/11/12; §5.4/§7.2).
-- Transcripts persist as voice_notes; the only audio anywhere is on-device and
-- deleted immediately after transcription (§5.4) — no audio column exists.

CREATE TABLE IF NOT EXISTS app.voice_notes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES app.users(id),
  kind            text NOT NULL CHECK (kind IN ('health','sick','diary','command')),
  transcript      text NOT NULL, -- VERBATIM (whisper output, client-confirmed)
  noted           jsonb NOT NULL DEFAULT '[]'::jsonb,
  logged_at       timestamptz NOT NULL DEFAULT now(),
  client_event_id text UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS app.handoffs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES app.users(id),
  question        text NOT NULL, -- VERBATIM patient words (workflow-07 §6)
  created_at      timestamptz NOT NULL DEFAULT now(),
  replied_at      timestamptz,
  client_event_id text UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS app.symptom_logs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES app.users(id),
  labels          text[] NOT NULL CHECK (labels <@ ARRAY['Vomiting','Nausea','Fever','Flu-like','Headache','Dizzy','Stomach upset','Tired','Pain']),
  logged_at       timestamptz NOT NULL DEFAULT now(),
  client_event_id text UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS app.vomit_answers (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES app.users(id),
  answer          text NOT NULL CHECK (answer IN ('within_hour','later','didnt_take')),
  answered_at     timestamptz NOT NULL DEFAULT now(),
  client_event_id text UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS app.diary_entries (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES app.users(id),
  text            text NOT NULL, -- VERBATIM entry (workflow-12 §6)
  noted           text[] NOT NULL DEFAULT '{}',
  created_at      timestamptz NOT NULL DEFAULT now(),
  client_event_id text UNIQUE NOT NULL
);

-- 002 pattern: role-level grants in 001 only covered tables existing then.
GRANT SELECT, INSERT, UPDATE ON app.voice_notes, app.handoffs, app.symptom_logs, app.vomit_answers, app.diary_entries TO kinetic_agent;
