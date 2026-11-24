-- For databases created before minutes_played became fractional.
-- Fresh databases get this from schema.sql and do not need it.
ALTER TABLE player_match_stats      ALTER COLUMN minutes_played TYPE NUMERIC(7,2);
ALTER TABLE player_tournament_stats ALTER COLUMN minutes_played TYPE NUMERIC(7,2);
