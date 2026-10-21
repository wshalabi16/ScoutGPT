"""
Generate natural-language player profiles and embed them with OpenAI.
Profiles are stored in player_profiles with a vector(1536) column.
"""

import os
from typing import Optional

import psycopg
from openai import OpenAI
from tqdm import tqdm

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536

# Initialised lazily on first use so that importing this module
# without OPENAI_API_KEY set (e.g. --no-embed) does not crash.
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. "
                "Add it to your .env file or pass --no-embed to skip embedding."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def build_profile_text(row: dict) -> str:
    """Turn a stats row into a human-readable profile for embedding."""
    name = row["player_name"]
    team = row["team_name"]
    matches = row["matches_played"]
    goals = row["goals"]
    xg = float(row["xg"] or 0)
    shots = row["shots"]
    passes_att = row["passes_attempted"]
    passes_comp = row["passes_completed"]
    pass_pct = round(passes_comp / passes_att * 100) if passes_att > 0 else 0
    key_passes = row["key_passes"]
    drib_att = row["dribbles_attempted"]
    pressures = row["pressures"]
    tackles = row["tackles"]
    interceptions = row["interceptions"]

    # Qualitative descriptors based on volume
    shot_desc = (
        "high shot volume" if shots / max(matches, 1) >= 2.5
        else "moderate shot volume" if shots / max(matches, 1) >= 1
        else "low shot output"
    )
    pass_desc = (
        "high pass volume" if passes_att / max(matches, 1) >= 50
        else "moderate passing" if passes_att / max(matches, 1) >= 25
        else "low pass volume"
    )
    press_desc = (
        "high pressing intensity" if pressures / max(matches, 1) >= 20
        else "moderate pressing" if pressures / max(matches, 1) >= 10
        else "low pressing"
    )
    drib_desc = (
        "frequent dribbler" if drib_att / max(matches, 1) >= 3
        else "occasional dribbler" if drib_att / max(matches, 1) >= 1
        else "rare dribbles"
    )
    def_desc = (
        "strong defensive presence" if (tackles + interceptions) / max(matches, 1) >= 4
        else "some defensive contribution" if (tackles + interceptions) / max(matches, 1) >= 2
        else "limited defensive stats"
    )

    return (
        f"{name} plays for {team}. "
        f"Across {matches} match{'es' if matches != 1 else ''}: "
        f"{goals} goal{'s' if goals != 1 else ''} ({xg:.2f} xG), "
        f"{shot_desc}, {pass_desc} ({pass_pct}% pass accuracy), "
        f"{key_passes} key pass{'es' if key_passes != 1 else ''}, "
        f"{drib_desc}, {press_desc}, {def_desc} "
        f"({tackles} tackle{'s' if tackles != 1 else ''}, "
        f"{interceptions} interception{'s' if interceptions != 1 else ''})."
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch embed up to 2048 texts at once."""
    response = _get_client().embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in response.data]


def generate_profiles_and_embed(
    conn: psycopg.Connection, competition_id: int, season_id: int
):
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT
                pts.*,
                p.player_name,
                t.team_name
            FROM player_tournament_stats pts
            JOIN players p ON p.player_id = pts.player_id
            JOIN teams   t ON t.team_id   = pts.team_id
            WHERE pts.competition_id = %s AND pts.season_id = %s
            """,
            (competition_id, season_id),
        )
        rows = cur.fetchall()

    print(f"  Building profiles for {len(rows)} players…")
    profiles = [(row, build_profile_text(row)) for row in rows]

    # Embed in chunks of 100
    chunk_size = 100
    with conn.cursor() as cur:
        for i in tqdm(range(0, len(profiles), chunk_size)):
            chunk = profiles[i : i + chunk_size]
            texts = [p[1] for p in chunk]
            embeddings = embed_texts(texts)

            for (row, profile_text), embedding in zip(chunk, embeddings):
                cur.execute(
                    """
                    INSERT INTO player_profiles
                        (player_id, competition_id, season_id, profile_text, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    ON CONFLICT (player_id, competition_id, season_id) DO UPDATE SET
                        profile_text = EXCLUDED.profile_text,
                        embedding    = EXCLUDED.embedding,
                        updated_at   = NOW()
                    """,
                    (
                        row["player_id"],
                        competition_id,
                        season_id,
                        profile_text,
                        str(embedding),
                    ),
                )
        conn.commit()

    print(f"  Embedded {len(profiles)} profiles.")
