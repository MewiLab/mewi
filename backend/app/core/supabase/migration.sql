CREATE EXTENSION IF NOT EXISTS vector;

-- ==========================================
-- Cleanup (reverse dependency order)
-- ==========================================
DROP TABLE IF EXISTS action_logs          CASCADE;
DROP TABLE IF EXISTS behavior_decisions   CASCADE;
DROP TABLE IF EXISTS perception_snapshots CASCADE;
DROP TABLE IF EXISTS memory_summaries     CASCADE;
DROP TABLE IF EXISTS creature_states      CASCADE;
DROP TABLE IF EXISTS zones                CASCADE;
DROP TABLE IF EXISTS user_creature_relations CASCADE;
DROP TABLE IF EXISTS micrologs            CASCADE;
DROP TABLE IF EXISTS creatures            CASCADE;
DROP TABLE IF EXISTS users                CASCADE;

-- ==========================================
-- Core Identity Tables
-- ==========================================

CREATE TABLE users (
  id         uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  aura       text,
  movement   text,
  identity   text,
  created_at timestamptz DEFAULT now() NOT NULL
);

CREATE TABLE creatures (
  id             uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  species        text DEFAULT 'cat',
  name           text,
  temperament    text,
  global_traits  text[],
  learned_fears  text[],
  _wisdom        text,
  created_at     timestamptz DEFAULT now() NOT NULL
);

CREATE TABLE user_creature_relations (
  id                uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id           uuid REFERENCES users(id) ON DELETE CASCADE,
  creature_id       uuid REFERENCES creatures(id) ON DELETE CASCADE,
  bond_score        integer DEFAULT 0,
  episodic_memories text[],
  emotional_tags    text[],
  last_seen_at      timestamptz,
  UNIQUE(user_id, creature_id)
);

-- ==========================================
-- Internal State Layer
-- ==========================================

CREATE TABLE creature_states (
  creature_id uuid REFERENCES creatures(id) ON DELETE CASCADE PRIMARY KEY,
  hunger      float DEFAULT 0.0,
  energy      float DEFAULT 1.0,
  mood        float DEFAULT 0.0,  -- scalar: trust - fear
  curiosity   float DEFAULT 0.5,
  fear        float DEFAULT 0.0,
  updated_at  timestamptz DEFAULT now()
);

-- ==========================================
-- Territory Layer
-- ==========================================

CREATE TABLE zones (
  id        uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  name      text NOT NULL,
  zone_type text,
  metadata  jsonb DEFAULT '{}'
);

-- ==========================================
-- Semantic Perception Layer  (X-to-1 compression)
-- ==========================================
-- Each row is ONE aggregated summary of X raw Unity snapshots.
-- creature_id is NOT NULL — every record is anchored to a specific creature
-- for deterministic memory retrieval.

CREATE TABLE perception_snapshots (
  id           uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  creature_id  uuid NOT NULL REFERENCES creatures(id) ON DELETE CASCADE,
  request_id   text,                    -- requestId from the final snapshot in the window
  summary_text text,                    -- Human-readable story from SemanticService
  raw_payloads jsonb DEFAULT '[]',      -- Array of X original Unity JSONs for auditing
  pos_x        float DEFAULT 0.0,
  pos_y        float DEFAULT 0.0,
  pos_z        float DEFAULT 0.0,
  created_at   timestamptz DEFAULT now()
);

-- Composite index optimises per-creature chronological memory retrieval
CREATE INDEX idx_perception_creature_time
  ON perception_snapshots(creature_id, created_at DESC);

-- ==========================================
-- Decision & Action Audit Trail
-- ==========================================

CREATE TABLE behavior_decisions (
  id               uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  creature_id      uuid REFERENCES creatures(id) ON DELETE CASCADE,
  snapshot_id      uuid REFERENCES perception_snapshots(id) ON DELETE SET NULL,
  decision_type    text NOT NULL,
  confidence       float,
  reasoning        text,
  raw_brain_output jsonb DEFAULT '{}',
  status           text DEFAULT 'pending',
  executed_at      timestamptz,
  created_at       timestamptz DEFAULT now()
);

CREATE TABLE action_logs (
  id           uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  decision_id  uuid REFERENCES behavior_decisions(id) ON DELETE CASCADE,
  action_type  text NOT NULL,
  duration     float,
  parameters   jsonb DEFAULT '{}',
  outcome      text,
  completed_at timestamptz,
  created_at   timestamptz DEFAULT now()
);

-- ==========================================
-- Long-term Reflection Layer
-- ==========================================

CREATE TABLE micrologs (
  id                 uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id            uuid REFERENCES users(id) ON DELETE CASCADE,
  creature_id        uuid REFERENCES creatures(id) ON DELETE CASCADE,
  content            text NOT NULL,
  valence            float DEFAULT 0.0,
  arousal            float DEFAULT 0.0,
  image_url          text,
  video_url          text,
  voice_url          text,
  embedding          vector(1536),
  contextual_summary text,
  importance_score   float4 DEFAULT 0.0,
  session_id         uuid,
  created_at         timestamptz DEFAULT now() NOT NULL
);

CREATE TABLE memory_summaries (
  id                uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  creature_id       uuid REFERENCES creatures(id) ON DELETE CASCADE,
  zone_id           uuid REFERENCES zones(id),
  period_start      timestamptz NOT NULL,
  period_end        timestamptz NOT NULL,
  summary_text      text NOT NULL,
  dominant_mood     float,
  dominant_behavior text,
  interaction_count integer DEFAULT 0,
  created_at        timestamptz DEFAULT now()
);

-- ==========================================
-- Performance Indexes
-- ==========================================

CREATE INDEX idx_micrologs_user_id        ON micrologs(user_id);
CREATE INDEX idx_micrologs_creature_id    ON micrologs(creature_id);
CREATE INDEX idx_micrologs_importance     ON micrologs(importance_score DESC);
CREATE INDEX idx_micrologs_session        ON micrologs(session_id);
CREATE INDEX idx_decisions_creature_time  ON behavior_decisions(creature_id, created_at DESC);
CREATE INDEX idx_decisions_pending        ON behavior_decisions(status) WHERE status = 'pending';
CREATE INDEX idx_perception_spatial       ON perception_snapshots(pos_x, pos_y, pos_z);

-- ==========================================
-- Utility: Python RPC tunnel
-- ==========================================

CREATE OR REPLACE FUNCTION exec_sql(query text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  EXECUTE query;
END;
$$;
