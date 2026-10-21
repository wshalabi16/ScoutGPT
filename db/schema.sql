-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ────────────────────────────────────────────────────────────────
-- Core lookup tables
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS competitions (
    competition_id   INTEGER PRIMARY KEY,
    competition_name TEXT NOT NULL,
    country_name     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seasons (
    season_id   INTEGER PRIMARY KEY,
    season_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS competition_seasons (
    competition_id INTEGER REFERENCES competitions(competition_id),
    season_id      INTEGER REFERENCES seasons(season_id),
    PRIMARY KEY (competition_id, season_id)
);

CREATE TABLE IF NOT EXISTS teams (
    team_id   INTEGER PRIMARY KEY,
    team_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    player_id   INTEGER PRIMARY KEY,
    player_name TEXT NOT NULL,
    nickname    TEXT,
    country     TEXT
);

-- ────────────────────────────────────────────────────────────────
-- Match-level
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS matches (
    match_id       INTEGER PRIMARY KEY,
    competition_id INTEGER REFERENCES competitions(competition_id),
    season_id      INTEGER REFERENCES seasons(season_id),
    match_date     DATE,
    home_team_id   INTEGER REFERENCES teams(team_id),
    away_team_id   INTEGER REFERENCES teams(team_id),
    home_score     INTEGER,
    away_score     INTEGER,
    stage          TEXT
);

-- ────────────────────────────────────────────────────────────────
-- Raw events (one row per StatsBomb event)
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS events (
    event_id    UUID PRIMARY KEY,
    match_id    INTEGER REFERENCES matches(match_id),
    index       INTEGER,
    period      INTEGER,
    timestamp   TIME,
    minute      INTEGER,
    second      INTEGER,
    type        TEXT NOT NULL,
    player_id   INTEGER REFERENCES players(player_id),
    team_id     INTEGER REFERENCES teams(team_id),
    location_x  NUMERIC,
    location_y  NUMERIC,
    extra       JSONB          -- type-specific fields
);

-- ────────────────────────────────────────────────────────────────
-- Derived: per-player per-match stats
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS player_match_stats (
    player_id          INTEGER REFERENCES players(player_id),
    match_id           INTEGER REFERENCES matches(match_id),
    team_id            INTEGER REFERENCES teams(team_id),
    minutes_played     INTEGER DEFAULT 0,
    shots              INTEGER DEFAULT 0,
    shots_on_target    INTEGER DEFAULT 0,
    goals              INTEGER DEFAULT 0,
    xg                 NUMERIC(6,4) DEFAULT 0,
    passes_attempted   INTEGER DEFAULT 0,
    passes_completed   INTEGER DEFAULT 0,
    key_passes         INTEGER DEFAULT 0,
    dribbles_attempted INTEGER DEFAULT 0,
    dribbles_completed INTEGER DEFAULT 0,
    pressures          INTEGER DEFAULT 0,
    tackles            INTEGER DEFAULT 0,
    interceptions      INTEGER DEFAULT 0,
    PRIMARY KEY (player_id, match_id)
);

-- ────────────────────────────────────────────────────────────────
-- Derived: per-player per-tournament totals
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS player_tournament_stats (
    player_id          INTEGER REFERENCES players(player_id),
    competition_id     INTEGER REFERENCES competitions(competition_id),
    season_id          INTEGER REFERENCES seasons(season_id),
    team_id            INTEGER REFERENCES teams(team_id),
    matches_played     INTEGER DEFAULT 0,
    minutes_played     INTEGER DEFAULT 0,
    shots              INTEGER DEFAULT 0,
    shots_on_target    INTEGER DEFAULT 0,
    goals              INTEGER DEFAULT 0,
    xg                 NUMERIC(6,4) DEFAULT 0,
    passes_attempted   INTEGER DEFAULT 0,
    passes_completed   INTEGER DEFAULT 0,
    key_passes         INTEGER DEFAULT 0,
    dribbles_attempted INTEGER DEFAULT 0,
    dribbles_completed INTEGER DEFAULT 0,
    pressures          INTEGER DEFAULT 0,
    tackles            INTEGER DEFAULT 0,
    interceptions      INTEGER DEFAULT 0,
    PRIMARY KEY (player_id, competition_id, season_id)
);

-- ────────────────────────────────────────────────────────────────
-- Player profiles for vector search
-- ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS player_profiles (
    player_id          INTEGER REFERENCES players(player_id),
    competition_id     INTEGER REFERENCES competitions(competition_id),
    season_id          INTEGER REFERENCES seasons(season_id),
    profile_text       TEXT NOT NULL,           -- human-readable summary for embedding
    embedding          vector(1536),            -- text-embedding-3-small dimensions
    updated_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, competition_id, season_id)
);

-- HNSW index for fast approximate nearest-neighbour search
CREATE INDEX IF NOT EXISTS player_profiles_embedding_idx
    ON player_profiles
    USING hnsw (embedding vector_cosine_ops);

-- Partial index to speed up lookups within a single competition/season
CREATE INDEX IF NOT EXISTS player_profiles_comp_season_idx
    ON player_profiles (competition_id, season_id);

-- ────────────────────────────────────────────────────────────────
-- Read-only role used by the SQL query tool
-- ────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'scout_readonly') THEN
        CREATE ROLE scout_readonly LOGIN PASSWORD 'readonly';
    END IF;
END $$;

GRANT CONNECT ON DATABASE scoutgpt TO scout_readonly;
GRANT USAGE ON SCHEMA public TO scout_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO scout_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO scout_readonly;
