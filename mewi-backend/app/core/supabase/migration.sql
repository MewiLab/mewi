-- ============================================================================
-- migration.sql
--
-- Declarative target schema for the Mewi backend. Active memory writes now use
-- semantic summaries; older raw/short-term memory tables remain declared for
-- compatibility with existing databases and read fallback during migration.
-- Legacy identity / perception / microlog / decision tables were dropped from
-- this file because nothing in app/ references them anymore — keep the
-- migration aligned with what the code actually expects.
--
-- Mapping (table -> repository):
--   agent_memory_summaries        app/repositories/supabase_memory_store.py
--   agent_place_memories          app/repositories/place_memory_repo.py
--   agent_place_memory_state      app/repositories/place_memory_repo.py
--   actor_relationship            app/social/service.py in Phase 2, Neo4j in Phase 3
--
-- This file is idempotent (CREATE TABLE IF NOT EXISTS) and safe to re-run.
-- It does NOT drop the legacy tables from existing databases — drop them
-- manually if you want a clean slate. See "Manual cleanup" at the bottom.
-- ============================================================================


-- ============================================================================
-- Agent Cat Memory
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS agent_memory_summaries (
  id            uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  creature_id   text NOT NULL,
  aspect        text NOT NULL DEFAULT 'general',
  memory_kind   text NOT NULL DEFAULT 'summary',
  text          text NOT NULL,
  tick_start    integer NOT NULL,
  tick_end      integer NOT NULL,
  source_count  integer NOT NULL DEFAULT 0,
  salience      float DEFAULT 0.0,
  evidence      jsonb NOT NULL DEFAULT '{}',
  is_active        boolean NOT NULL DEFAULT true,
  superseded_by    uuid REFERENCES agent_memory_summaries(id) ON DELETE SET NULL,
  embedding        vector(1536),
  last_active_tick integer,
  updated_at       timestamptz DEFAULT now() NOT NULL,
  created_at    timestamptz DEFAULT now() NOT NULL
);

ALTER TABLE agent_memory_summaries
  ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS superseded_by uuid REFERENCES agent_memory_summaries(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS embedding vector(1536),
  ADD COLUMN IF NOT EXISTS last_active_tick integer,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now() NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_memory_summaries_active
  ON agent_memory_summaries(creature_id, is_active, tick_end DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_memory_summaries_active_aspect
  ON agent_memory_summaries(creature_id, aspect, is_active, tick_end DESC);

CREATE INDEX IF NOT EXISTS idx_agent_memory_summaries_embedding
  ON agent_memory_summaries USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100)
  WHERE embedding IS NOT NULL AND is_active;

CREATE OR REPLACE FUNCTION match_agent_memory_summaries(
  query_embedding vector(1536),
  match_creature_id text,
  match_count integer DEFAULT 5,
  match_aspect text DEFAULT ''
)
RETURNS TABLE (
  id uuid,
  creature_id text,
  aspect text,
  memory_kind text,
  text text,
  tick_start integer,
  tick_end integer,
  source_count integer,
  salience float,
  evidence jsonb,
  is_active boolean,
  superseded_by uuid,
  last_active_tick integer,
  updated_at timestamptz,
  created_at timestamptz,
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    s.id,
    s.creature_id,
    s.aspect,
    s.memory_kind,
    s.text,
    s.tick_start,
    s.tick_end,
    s.source_count,
    s.salience,
    s.evidence,
    s.is_active,
    s.superseded_by,
    s.last_active_tick,
    s.updated_at,
    s.created_at,
    1 - (s.embedding <=> query_embedding) AS similarity
  FROM agent_memory_summaries s
  WHERE s.creature_id = match_creature_id
    AND s.is_active = true
    AND s.embedding IS NOT NULL
    AND (match_aspect = '' OR s.aspect = match_aspect)
  ORDER BY s.embedding <=> query_embedding
  LIMIT match_count;
$$;


CREATE TABLE IF NOT EXISTS actor_relationship (
  creature_id       text NOT NULL,
  target_id         text NOT NULL,
  trust             float NOT NULL DEFAULT 0.0,
  affinity          float NOT NULL DEFAULT 0.0,
  encounters        integer NOT NULL DEFAULT 0,
  last_tick         integer NOT NULL DEFAULT 0,
  evidence          jsonb NOT NULL DEFAULT '{}',
  updated_at        timestamptz DEFAULT now() NOT NULL,
  created_at        timestamptz DEFAULT now() NOT NULL,
  PRIMARY KEY (creature_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_actor_relationship_creature_updated
  ON actor_relationship(creature_id, updated_at DESC);


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
  summary                  text DEFAULT '',
  summary_evidence         jsonb DEFAULT '{}'::jsonb,
  summary_updated_at       float DEFAULT 0.0,
  created_at               timestamptz DEFAULT now() NOT NULL,
  updated_at               timestamptz DEFAULT now() NOT NULL,
  UNIQUE(creature_id, zone_id)
);

ALTER TABLE agent_place_memories
  ADD COLUMN IF NOT EXISTS summary text DEFAULT '',
  ADD COLUMN IF NOT EXISTS summary_evidence jsonb DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS summary_updated_at float DEFAULT 0.0;

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
-- Reload PostgREST schema cache.
--   Must be the LAST statement. After `ADD COLUMN IF NOT EXISTS` lands new
--   columns (e.g. agent_place_memories.summary), PostgREST keeps serving its
--   stale schema cache and rejects writes with PGRST204 ("Could not find the
--   '<col>' column ... in the schema cache"). This NOTIFY tells PostgREST to
--   reload so freshly migrated columns are immediately writable.
-- ============================================================================

NOTIFY pgrst, 'reload schema';


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
--   DROP TABLE IF EXISTS agent_memory_raw_events CASCADE;       -- legacy memory v0
--   DROP TABLE IF EXISTS agent_short_term_memories CASCADE;     -- legacy memory v0
--   DROP TABLE IF EXISTS attachment_raw_events CASCADE;
--   DROP TABLE IF EXISTS attachment_session_features CASCADE;
--   DROP TABLE IF EXISTS attachment_results CASCADE;
--   DROP EXTENSION IF EXISTS vector;                  -- do not drop if graph memory uses pgvector
-- ============================================================================
