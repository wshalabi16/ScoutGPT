"""
Playing-time model.

Convention: minutes played = elapsed playing time, including stoppage time,
excluding half-time/extra-time breaks and the penalty shootout (period 5).

StatsBomb's `minute` resets to a nominal value at each period start (45, 90, 105)
and so drops stoppage time. Instead, each event's `timestamp` is the time elapsed
within its period, so an event's elapsed match time is the summed length of the
earlier periods plus its own timestamp. Seconds are kept; rounding happens on output.
"""

from dataclasses import dataclass

RED_CARDS = {"Red Card", "Second Yellow"}
CARD_FIELDS = ("foul_committed_card", "bad_behaviour_card")


@dataclass
class Appearance:
    player_id: int
    player_name: str
    team_id: int
    on_s: float
    off_s: float | None = None


def period_offsets(period_lengths: dict[int, float]) -> tuple[dict[int, float], float]:
    """Return each playing period's start in elapsed seconds, and total playing time."""
    offsets: dict[int, float] = {}
    total = 0.0
    for period in sorted(p for p in period_lengths if 1 <= p <= 4):
        offsets[period] = total
        total += period_lengths[period]
    return offsets, total


def compute_appearances(events: list[dict], period_lengths: dict[int, float]) -> list[Appearance]:
    """
    Build one Appearance per player who took part in a match.

    `events` must be one match's events in `index` order, each a dict with
    period, t (seconds into the period), type, player_id, team_id, extra.
    """
    offsets, total = period_offsets(period_lengths)
    apps: dict[int, Appearance] = {}
    exits: dict[int, float] = {}
    pending_off: dict[int, float] = {}  # "Player Off" not yet followed by "Player On"

    def leave(player_id, at):
        if player_id is not None and player_id not in exits:
            exits[player_id] = at

    for e in events:
        if e["period"] not in offsets:
            continue
        at = offsets[e["period"]] + e["t"]
        extra = e.get("extra") or {}

        if e["type"] == "Starting XI":
            for slot in extra.get("tactics", {}).get("lineup", []):
                pid = int(slot["player"]["id"])
                apps[pid] = Appearance(pid, slot["player"].get("name", ""), e["team_id"], 0.0)

        elif e["type"] == "Substitution":
            leave(e["player_id"], at)
            pid = int(extra["substitution_replacement_id"])
            apps[pid] = Appearance(pid, extra.get("substitution_replacement", ""), e["team_id"], at)

        elif e["type"] == "Player Off":
            pending_off[e["player_id"]] = at

        elif e["type"] == "Player On":
            pending_off.pop(e["player_id"], None)

        if any(extra.get(f) in RED_CARDS for f in CARD_FIELDS):
            leave(e["player_id"], at)

    for pid, at in pending_off.items():
        leave(pid, at)

    for pid, app in apps.items():
        app.off_s = exits.get(pid, total)
    return list(apps.values())


def seconds_played(app: Appearance) -> float:
    return max(app.off_s - app.on_s, 0.0)
