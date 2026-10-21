"""
StatsBomb → Postgres ingest pipeline.

statsbombpy.sb.matches() returns a flattened DataFrame:
  - home_team / away_team  → team name strings
  - home_team_id / away_team_id → integer IDs
statsbombpy.sb.events() returns a flattened DataFrame:
  - player_id  → integer ID (NaN when no player attached to event)
  - player     → display name string (not player_name)
  - team_id    → integer ID
  - type       → event type name string
  - location   → Python list [x, y] or NaN when absent

Usage as a CLI:
  python pipeline.py --competition_id 43 --season_id 3   # 2018 World Cup
"""

import argparse
import math
import os

import psycopg
import psycopg.types.json
from dotenv import load_dotenv
from statsbombpy import sb
from tqdm import tqdm

load_dotenv()  # must run before any os.environ reads, including embeddings.py

DATABASE_URL = os.environ["DATABASE_URL"]


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def get_conn() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def _nan_to_none(v):
    """Convert pandas NaN / numpy NaN to None; leave everything else alone."""
    if v is None:
        return None
    try:
        if math.isnan(v):
            return None
    except TypeError:
        pass
    return v


def _clean_extra(row, skip: set) -> dict:
    """
    Build the JSONB extra dict from a flattened events row.
    Drops columns in `skip`, drops None and NaN values, and converts
    any remaining non-JSON-serialisable types to strings so psycopg
    never sees invalid JSON.
    """
    result = {}
    for k, v in row.items():
        if k in skip:
            continue
        v = _nan_to_none(v)
        if v is None:
            continue
        # Lists (e.g. pass_end_location) are fine; dicts shouldn't appear in
        # the flattened frame but guard anyway.
        if isinstance(v, (bool, int, float, str, list)):
            result[k] = v
        else:
            result[k] = str(v)
    return result


# ─────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────


def load_competition(conn: psycopg.Connection, competition_id: int, season_id: int):
    comps = sb.competitions()
    mask = (comps["competition_id"] == competition_id) & (comps["season_id"] == season_id)
    row = comps[mask]
    if row.empty:
        raise ValueError(
            f"Competition {competition_id}/{season_id} not found in StatsBomb open data."
        )
    r = row.iloc[0]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO competitions (competition_id, competition_name, country_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (competition_id) DO NOTHING
            """,
            (int(r["competition_id"]), r["competition_name"], r["country_name"]),
        )
        cur.execute(
            """
            INSERT INTO seasons (season_id, season_name)
            VALUES (%s, %s)
            ON CONFLICT (season_id) DO NOTHING
            """,
            (int(r["season_id"]), r["season_name"]),
        )
        cur.execute(
            """
            INSERT INTO competition_seasons (competition_id, season_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (int(r["competition_id"]), int(r["season_id"])),
        )
    conn.commit()
    return r


def load_matches(conn: psycopg.Connection, competition_id: int, season_id: int) -> list[dict]:
    """
    statsbombpy flattens match JSON so that:
      m["home_team"]    → team name string   (e.g. "England")
      m["home_team_id"] → integer ID
      m["away_team"]    → team name string
      m["away_team_id"] → integer ID
      m["competition_stage"] → stage name string (may be absent)
    """
    matches_df = sb.matches(competition_id=competition_id, season_id=season_id)
    loaded = []
    with conn.cursor() as cur:
        for _, m in matches_df.iterrows():
            home_team_id = int(m["home_team_id"])
            away_team_id = int(m["away_team_id"])
            home_team_name = str(m["home_team"])
            away_team_name = str(m["away_team"])

            cur.execute(
                "INSERT INTO teams (team_id, team_name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (home_team_id, home_team_name),
            )
            cur.execute(
                "INSERT INTO teams (team_id, team_name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (away_team_id, away_team_name),
            )

            stage = _nan_to_none(m.get("competition_stage")) or ""

            cur.execute(
                """
                INSERT INTO matches
                    (match_id, competition_id, season_id, match_date,
                     home_team_id, away_team_id, home_score, away_score, stage)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (match_id) DO NOTHING
                """,
                (
                    int(m["match_id"]),
                    competition_id,
                    season_id,
                    str(m["match_date"]),
                    home_team_id,
                    away_team_id,
                    int(_nan_to_none(m.get("home_score")) or 0),
                    int(_nan_to_none(m.get("away_score")) or 0),
                    str(stage),
                ),
            )
            loaded.append({"match_id": int(m["match_id"])})
    conn.commit()
    return loaded


def load_events_for_match(conn: psycopg.Connection, match_id: int):
    """
    statsbombpy flattens event JSON so that player_id, player_name,
    team_id, team_name, and type are direct scalar columns — not nested dicts.
    location is a Python list [x, y] when present, or NaN when absent.
    """
    events_df = sb.events(match_id=match_id)

    skip = {
        "id", "index", "period", "timestamp", "minute", "second",
        "type", "player_id", "player", "team_id", "team",
        "location", "match_id",
    }

    with conn.cursor() as cur:
        for _, e in events_df.iterrows():
            player_id = _nan_to_none(e.get("player_id"))
            # statsbombpy puts the display name in the "player" column
            player_name = _nan_to_none(e.get("player")) or ""
            team_id = _nan_to_none(e.get("team_id"))
            event_type = str(_nan_to_none(e.get("type")) or "")

            if player_id is not None:
                player_id = int(player_id)
                cur.execute(
                    """
                    INSERT INTO players (player_id, player_name) VALUES (%s, %s)
                    ON CONFLICT (player_id) DO UPDATE
                        SET player_name = EXCLUDED.player_name
                        WHERE players.player_name = ''
                    """,
                    (player_id, player_name),
                )

            if team_id is not None:
                team_id = int(team_id)

            # location is a list [x, y] or NaN
            raw_loc = e.get("location")
            if isinstance(raw_loc, (list, tuple)) and len(raw_loc) >= 2:
                loc_x, loc_y = raw_loc[0], raw_loc[1]
            else:
                loc_x, loc_y = None, None

            extra = _clean_extra(e, skip)

            cur.execute(
                """
                INSERT INTO events
                    (event_id, match_id, index, period, timestamp,
                     minute, second, type, player_id, team_id,
                     location_x, location_y, extra)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    str(e["id"]),
                    match_id,
                    int(e.get("index", 0)),
                    int(e.get("period", 0)),
                    str(e.get("timestamp", "00:00:00.000")),
                    int(e.get("minute", 0)),
                    int(e.get("second", 0)),
                    event_type,
                    player_id,
                    team_id,
                    loc_x,
                    loc_y,
                    psycopg.types.json.Jsonb(extra),
                ),
            )
    conn.commit()


def aggregate_player_stats(conn: psycopg.Connection, competition_id: int, season_id: int):
    """
    Aggregate raw events → player_match_stats → player_tournament_stats.

    StatsBomb field names used here (flattened format):
      - shot_outcome      : "Goal", "Saved", "Off T", etc.
      - shot_statsbomb_xg : float
      - pass_outcome      : NULL means completed, any value means not completed
      - dribble_outcome   : "Complete" or "Incomplete"
      - duel_type         : "Tackle" (tackles are Duel events, not a separate type)
      - period 5          : penalty shootout — excluded from shot/xG counts
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO player_match_stats
                (player_id, match_id, team_id,
                 shots, shots_on_target, goals, xg,
                 passes_attempted, passes_completed, key_passes,
                 dribbles_attempted, dribbles_completed,
                 pressures, tackles, interceptions)
            SELECT
                e.player_id,
                e.match_id,
                e.team_id,

                -- Shots: exclude period 5 (penalty shootout)
                COUNT(*) FILTER (
                    WHERE e.type = 'Shot' AND e.period != 5
                ) AS shots,

                -- Shots on target: Goal or Saved, excluding shootout
                COUNT(*) FILTER (
                    WHERE e.type = 'Shot'
                      AND e.period != 5
                      AND e.extra->>'shot_outcome' IN ('Goal', 'Saved')
                ) AS shots_on_target,

                -- Goals: exclude shootout penalties
                COUNT(*) FILTER (
                    WHERE e.type = 'Shot'
                      AND e.period != 5
                      AND e.extra->>'shot_outcome' = 'Goal'
                ) AS goals,

                -- xG: exclude shootout
                COALESCE(
                    SUM((e.extra->>'shot_statsbomb_xg')::numeric)
                    FILTER (WHERE e.type = 'Shot' AND e.period != 5),
                    0
                ) AS xg,

                COUNT(*) FILTER (WHERE e.type = 'Pass') AS passes_attempted,

                -- Completed passes: pass_outcome is NULL when completed
                COUNT(*) FILTER (
                    WHERE e.type = 'Pass'
                      AND (e.extra->>'pass_outcome') IS NULL
                ) AS passes_completed,

                COUNT(*) FILTER (
                    WHERE e.type = 'Pass'
                      AND e.extra->>'pass_shot_assist' = 'true'
                ) AS key_passes,

                COUNT(*) FILTER (WHERE e.type = 'Dribble') AS dribbles_attempted,

                COUNT(*) FILTER (
                    WHERE e.type = 'Dribble'
                      AND e.extra->>'dribble_outcome' = 'Complete'
                ) AS dribbles_completed,

                COUNT(*) FILTER (WHERE e.type = 'Pressure') AS pressures,

                -- Tackles are Duel events with duel_type = 'Tackle'
                COUNT(*) FILTER (
                    WHERE e.type = 'Duel'
                      AND e.extra->>'duel_type' = 'Tackle'
                ) AS tackles,

                COUNT(*) FILTER (WHERE e.type = 'Interception') AS interceptions

            FROM events e
            JOIN matches m ON m.match_id = e.match_id
            WHERE m.competition_id = %s
              AND m.season_id = %s
              AND e.player_id IS NOT NULL
            GROUP BY e.player_id, e.match_id, e.team_id
            ON CONFLICT (player_id, match_id) DO UPDATE SET
                shots              = EXCLUDED.shots,
                shots_on_target    = EXCLUDED.shots_on_target,
                goals              = EXCLUDED.goals,
                xg                 = EXCLUDED.xg,
                passes_attempted   = EXCLUDED.passes_attempted,
                passes_completed   = EXCLUDED.passes_completed,
                key_passes         = EXCLUDED.key_passes,
                dribbles_attempted = EXCLUDED.dribbles_attempted,
                dribbles_completed = EXCLUDED.dribbles_completed,
                pressures          = EXCLUDED.pressures,
                tackles            = EXCLUDED.tackles,
                interceptions      = EXCLUDED.interceptions
            """,
            (competition_id, season_id),
        )

        cur.execute(
            """
            INSERT INTO player_tournament_stats
                (player_id, competition_id, season_id, team_id,
                 matches_played, shots, shots_on_target, goals, xg,
                 passes_attempted, passes_completed, key_passes,
                 dribbles_attempted, dribbles_completed,
                 pressures, tackles, interceptions)
            SELECT
                pms.player_id,
                m.competition_id,
                m.season_id,
                pms.team_id,
                COUNT(DISTINCT pms.match_id)     AS matches_played,
                SUM(pms.shots)                   AS shots,
                SUM(pms.shots_on_target)         AS shots_on_target,
                SUM(pms.goals)                   AS goals,
                SUM(pms.xg)                      AS xg,
                SUM(pms.passes_attempted)        AS passes_attempted,
                SUM(pms.passes_completed)        AS passes_completed,
                SUM(pms.key_passes)              AS key_passes,
                SUM(pms.dribbles_attempted)      AS dribbles_attempted,
                SUM(pms.dribbles_completed)      AS dribbles_completed,
                SUM(pms.pressures)               AS pressures,
                SUM(pms.tackles)                 AS tackles,
                SUM(pms.interceptions)           AS interceptions
            FROM player_match_stats pms
            JOIN matches m ON m.match_id = pms.match_id
            WHERE m.competition_id = %s AND m.season_id = %s
            GROUP BY pms.player_id, m.competition_id, m.season_id, pms.team_id
            ON CONFLICT (player_id, competition_id, season_id) DO UPDATE SET
                matches_played     = EXCLUDED.matches_played,
                shots              = EXCLUDED.shots,
                shots_on_target    = EXCLUDED.shots_on_target,
                goals              = EXCLUDED.goals,
                xg                 = EXCLUDED.xg,
                passes_attempted   = EXCLUDED.passes_attempted,
                passes_completed   = EXCLUDED.passes_completed,
                key_passes         = EXCLUDED.key_passes,
                dribbles_attempted = EXCLUDED.dribbles_attempted,
                dribbles_completed = EXCLUDED.dribbles_completed,
                pressures          = EXCLUDED.pressures,
                tackles            = EXCLUDED.tackles,
                interceptions      = EXCLUDED.interceptions
            """,
            (competition_id, season_id),
        )
    conn.commit()


# ─────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────


def run_ingest(competition_id: int, season_id: int, embed: bool = True) -> dict:
    print("Connecting to database…")
    conn = get_conn()

    print("Loading competition metadata…")
    load_competition(conn, competition_id, season_id)

    print("Loading matches…")
    matches = load_matches(conn, competition_id, season_id)
    print(f"  {len(matches)} matches found.")

    print("Loading events (this takes a few minutes)…")
    for m in tqdm(matches):
        load_events_for_match(conn, m["match_id"])

    print("Aggregating player stats…")
    aggregate_player_stats(conn, competition_id, season_id)

    if embed:
        from embeddings import generate_profiles_and_embed
        print("Generating embeddings…")
        generate_profiles_and_embed(conn, competition_id, season_id)

    conn.close()
    return {
        "competition_id": competition_id,
        "season_id": season_id,
        "matches_loaded": len(matches),
        "status": "ok",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition_id", type=int, required=True)
    parser.add_argument("--season_id", type=int, required=True)
    parser.add_argument("--no-embed", action="store_true")
    args = parser.parse_args()
    run_ingest(args.competition_id, args.season_id, embed=not args.no_embed)
