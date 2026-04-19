CREATE EXTENSION IF NOT EXISTS vector;

-- Cleanup
DROP TABLE IF EXISTS user_creature_relations CASCADE;
DROP TABLE IF EXISTS micrologs CASCADE;
DROP TABLE IF EXISTS creatures CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY, -- Auto-generate UUID
  aura text,
  movement text,
  identity text,
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Independent memory storage
CREATE TABLE micrologs (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  content text NOT NULL,
  valence float DEFAULT 0.0,
  arousal float DEFAULT 0.0,
  image_url text,
  video_url text,
  voice_url text,
  -- Embedding for OpenAI (1536 dimensions)
  embedding vector(1536), 
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Index for optimized user-specific queries
CREATE INDEX idx_micrologs_user_id ON micrologs(user_id);

CREATE TABLE creatures (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  temperament text,
  global_traits text[],
  learned_fears text[],
  _wisdom text,
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Joint Table
CREATE TABLE user_creature_relations (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  creature_id uuid REFERENCES creatures(id) ON DELETE CASCADE,
  bond_score integer DEFAULT 0,
  episodic_memories text[],
  emotional_tags text[],
  last_seen_at timestamp with time zone,
  UNIQUE(user_id, creature_id)
);

-- 1. Upgrade creatures (Base info)
ALTER TABLE creatures ADD COLUMN IF NOT EXISTS species text DEFAULT 'cat';
ALTER TABLE creatures ADD COLUMN IF NOT EXISTS name text;

-- 2. Create creature_states (The "Inner State" layer)
CREATE TABLE IF NOT EXISTS creature_states (
    creature_id uuid REFERENCES creatures(id) ON DELETE CASCADE PRIMARY KEY,
    hunger float DEFAULT 0.0,
    energy float DEFAULT 1.0,
    mood float DEFAULT 0.0,
    curiosity float DEFAULT 0.5,
    fear float DEFAULT 0.0,
    updated_at timestamptz DEFAULT now()
);

-- 3. Create zones (The "Territory" layer)
CREATE TABLE IF NOT EXISTS zones (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    name text NOT NULL,          -- e.g., 'feeding_area', 'user_desk'
    zone_type text,              -- e.g., 'safe', 'social', 'resource'
    metadata jsonb DEFAULT '{}'
);

-- 4. Create perception_snapshots (The "Environment" layer)
CREATE TABLE IF NOT EXISTS perception_snapshots (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    creature_id uuid REFERENCES creatures(id) ON DELETE CASCADE,
    zone_id uuid REFERENCES zones(id) ON DELETE SET NULL,
    user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    user_distance float,
    user_velocity float,
    time_of_day integer,
    noise_level float DEFAULT 0.0,
    pos_x float, pos_y float, pos_z float,
    features jsonb DEFAULT '{}', -- 存儲動態環境特徵
    created_at timestamptz DEFAULT now()
);

-- 5. Create behavior_decisions (The "Decision" layer)
CREATE TABLE IF NOT EXISTS behavior_decisions (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    creature_id uuid REFERENCES creatures(id) ON DELETE CASCADE,
    snapshot_id uuid REFERENCES perception_snapshots(id),
    decision_type text NOT NULL, -- approach, avoid, idle, explore
    confidence float,
    reasoning text,
    status text DEFAULT 'pending', -- 'pending' | 'executing' | 'completed'
    executed_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- 6. Create action_logs (The "Action" layer)
CREATE TABLE IF NOT EXISTS action_logs (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    decision_id uuid REFERENCES behavior_decisions(id) ON DELETE CASCADE,
    action_type text NOT NULL,
    duration float,
    parameters jsonb DEFAULT '{}',
    outcome text,                  -- 'success' | 'failed'
    completed_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- 7. Create memory_summaries (Long-term reflection)
CREATE TABLE IF NOT EXISTS memory_summaries (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    creature_id uuid REFERENCES creatures(id) ON DELETE CASCADE,
    zone_id uuid REFERENCES zones(id),
    period_start timestamptz NOT NULL,
    period_end timestamptz NOT NULL,
    summary_text text NOT NULL,
    dominant_mood float,
    dominant_behavior text,
    interaction_count integer DEFAULT 0,
    created_at timestamptz DEFAULT now()
);

-- ==========================================
-- Optimizations: Indexes
-- ==========================================
CREATE INDEX IF NOT EXISTS idx_perception_creature_time ON perception_snapshots(creature_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_creature_time ON behavior_decisions(creature_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_pending ON behavior_decisions(status) WHERE status = 'pending';

-- 1. Upgrade micrologs (Long-term Contextual Memory)
-- This allows the cat to remember "Why" something happened, not just "What"
ALTER TABLE micrologs 
ADD COLUMN IF NOT EXISTS creature_id uuid REFERENCES creatures(id) ON DELETE CASCADE, -- Link memory to the cat
ADD COLUMN IF NOT EXISTS contextual_summary text,     -- LLM-generated background story
ADD COLUMN IF NOT EXISTS importance_score float4 DEFAULT 0.0, -- Priority for RAG retrieval
ADD COLUMN IF NOT EXISTS session_id uuid;             -- Grouping for developer debugging

-- 2. Upgrade perception_snapshots (Environmental Raw Data)
-- Ensures Unity developers can audit exactly what the cat perceived
ALTER TABLE perception_snapshots 
ADD COLUMN IF NOT EXISTS raw_data jsonb DEFAULT '{}', -- Full original JSON payload from Unity
ADD COLUMN IF NOT EXISTS session_id uuid;             -- Link snapshots to a specific play session

-- 3. Upgrade behavior_decisions (Brain Reasoning Trace)
-- Captures the actual structured output from the LLM
ALTER TABLE behavior_decisions 
ADD COLUMN IF NOT EXISTS raw_brain_output jsonb DEFAULT '{}';

-- 4. Optimizations: Spatial and Importance Indexes
-- Helps find memories near the cat's current position quickly
CREATE INDEX IF NOT EXISTS idx_perception_spatial ON perception_snapshots (pos_x, pos_y, pos_z);
-- Prioritizes high-value memories during RAG retrieval
CREATE INDEX IF NOT EXISTS idx_micrologs_importance ON micrologs(importance_score DESC);
-- Allows grouping all logs by a specific session for debugging
CREATE INDEX IF NOT EXISTS idx_micrologs_session ON micrologs(session_id);

-- tunnel for Python 透過 RPC 執行任何 SQL 語句
create or replace function exec_sql(query text)
returns void
language plpgsql
security definer
as $$
begin
  execute query;
end;
$$;