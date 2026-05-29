-- ============================================================================
-- migration.sql
--
-- Declarative target schema for the Mewi backend. Only tables that the active
-- Python repositories read or write live here. Legacy identity / perception /
-- microlog / decision tables were dropped from this file because nothing in
-- app/ references them anymore — keep the migration aligned with what the code
-- actually expects.
--
-- Mapping (table → repository):
--   agent_memory_raw_events       app/repositories/memory_repo.py
--   agent_short_term_memories     app/repositories/memory_repo.py
--   agent_place_memories          app/repositories/place_memory_repo.py
--   agent_place_memory_state      app/repositories/place_memory_repo.py
--   attachment_raw_events         app/repositories/attachment_repo.py
--   attachment_session_features   app/repositories/attachment_repo.py
--   attachment_results            app/repositories/attachment_repo.py
--
-- This file is idempotent (CREATE TABLE IF NOT EXISTS) and safe to re-run.
-- It does NOT drop the legacy tables from existing databases — drop them
-- manually if you want a clean slate. See "Manual cleanup" at the bottom.
-- ============================================================================


-- ============================================================================
-- Agent Cat Memory
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_memory_raw_events (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  creature_id text NOT NULL,
  tick        integer NOT NULL,
  request_id  text DEFAULT '',
  source      text NOT NULL DEFAULT 'python',
  event_type  text NOT NULL,
  payload     jsonb NOT NULL DEFAULT '{}',
  created_at  timestamptz DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_raw_creature_tick
  ON agent_memory_raw_events(creature_id, tick DESC, created_at DESC);


CREATE TABLE IF NOT EXISTS agent_short_term_memories (
  id           uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  raw_event_id uuid REFERENCES agent_memory_raw_events(id) ON DELETE SET NULL,
  creature_id  text NOT NULL,
  tick         integer NOT NULL,
  request_id   text DEFAULT '',
  memory_kind  text NOT NULL DEFAULT 'working',
  aspect       text NOT NULL DEFAULT 'general',
  text         text NOT NULL,
  salience     float DEFAULT 0.0,
  evidence     jsonb NOT NULL DEFAULT '{}',
  created_at   timestamptz DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_short_term_creature_tick
  ON agent_short_term_memories(creature_id, tick DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_short_term_kind_aspect
  ON agent_short_term_memories(creature_id, memory_kind, aspect, tick DESC);


-- ============================================================================
-- Place Memory (per-creature zone coverage)
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_place_memories (
  id                       uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  creature_id              text NOT NULL,
  zone_id                  text NOT NULL,
  visit_count              integer DEFAULT 0,
  last_visited_at          float,
  last_seen_at             float DEFAULT 0.0,
  familiarity              float DEFAULT 0.0,
  last_arrival_request_id  text DEFAULT '',
  created_at               timestamptz DEFAULT now() NOT NULL,
  updated_at               timestamptz DEFAULT now() NOT NULL,
  UNIQUE(creature_id, zone_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_place_memories_seen
  ON agent_place_memories(creature_id, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_place_memories_visits
  ON agent_place_memories(creature_id, visit_count, last_visited_at DESC);


CREATE TABLE IF NOT EXISTS agent_place_memory_state (
  creature_id       text PRIMARY KEY,
  last_zone_id      text DEFAULT '',
  last_observed_at  float DEFAULT 0.0,
  last_request_id   text DEFAULT '',
  updated_at        timestamptz DEFAULT now() NOT NULL
);


-- ============================================================================
-- Attachment Research Pipeline
-- ============================================================================

CREATE TABLE IF NOT EXISTS attachment_raw_events (
  id                 uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  session_id         uuid NOT NULL,
  cat_id             text NOT NULL,
  cat_assigned_type  text NOT NULL,
  event              text NOT NULL,
  t                  float NOT NULL,
  distance           float,
  meta               jsonb DEFAULT '{}',
  created_at         timestamptz DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attachment_raw_session
  ON attachment_raw_events(session_id, cat_id, t);


CREATE TABLE IF NOT EXISTS attachment_session_features (
  id                         uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  session_id                 uuid NOT NULL,
  cat_id                     text NOT NULL,
  cat_assigned_type          text NOT NULL,
  reapproach_latency_mean    float DEFAULT 0.0,
  pursuit_ratio              float DEFAULT 0.0,
  time_near_ratio            float DEFAULT 0.0,
  reunion_response           float DEFAULT 0.0,
  withdrawal_tolerance       float DEFAULT 0.0,
  n_events                   integer DEFAULT 0,
  created_at                 timestamptz DEFAULT now() NOT NULL,
  UNIQUE(session_id, cat_id)
);


CREATE TABLE IF NOT EXISTS attachment_results (
  id                          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  session_id                  uuid NOT NULL,
  cat_id                      text NOT NULL,
  cat_assigned_type           text NOT NULL,
  player_attachment_estimate  text NOT NULL,
  scores                      jsonb DEFAULT '{}',
  confidence                  text DEFAULT 'low',
  n_events                    integer DEFAULT 0,
  features                    jsonb DEFAULT '{}',
  rule_trace                  jsonb DEFAULT '[]',
  created_at                  timestamptz DEFAULT now() NOT NULL,
  UNIQUE(session_id, cat_id)
);

CREATE INDEX IF NOT EXISTS idx_attachment_results_session
  ON attachment_results(session_id, cat_id);


-- ============================================================================
-- Utility: Python RPC tunnel
--   Used by app/core/supabase/schema_manager.py to apply migrations from code.
-- ============================================================================

CREATE OR REPLACE FUNCTION exec_sql(query text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  EXECUTE query;
END;
$$;


-- ============================================================================
-- Manual cleanup (legacy tables — run if you want to drop them from an
-- existing database; nothing in current app/ references them):
--
--   DROP TABLE IF EXISTS users CASCADE;
--   DROP TABLE IF EXISTS creatures CASCADE;
--   DROP TABLE IF EXISTS user_creature_relations CASCADE;
--   DROP TABLE IF EXISTS creature_states CASCADE;
--   DROP TABLE IF EXISTS zones CASCADE;
--   DROP TABLE IF EXISTS perception_snapshots CASCADE;
--   DROP TABLE IF EXISTS behavior_decisions CASCADE;
--   DROP TABLE IF EXISTS action_logs CASCADE;
--   DROP TABLE IF EXISTS micrologs CASCADE;
--   DROP TABLE IF EXISTS memory_summaries CASCADE;
--   DROP TABLE IF EXISTS agent_tick_history CASCADE;  -- code-defined but unused
--   DROP EXTENSION IF EXISTS vector;                  -- only used by dropped tables
-- ============================================================================
