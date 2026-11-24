import pytest

from minutes import compute_appearances, seconds_played

HOME, AWAY = 1, 2


def mmss(text: str) -> float:
    m, s = text.split(":")
    return int(m) * 60 + float(s)


def starting_xi(team_id, player_ids):
    lineup = [{"player": {"id": pid, "name": f"P{pid}"}} for pid in player_ids]
    return {"period": 1, "t": 0.0, "type": "Starting XI", "player_id": None,
            "team_id": team_id, "extra": {"tactics": {"lineup": lineup}}}


def sub(period, t, team_id, off_id, on_id):
    return {"period": period, "t": mmss(t), "type": "Substitution", "player_id": off_id,
            "team_id": team_id,
            "extra": {"substitution_replacement_id": float(on_id),
                      "substitution_replacement": f"P{on_id}"}}


def event(period, t, type_, player_id, team_id=HOME, **extra):
    return {"period": period, "t": mmss(t), "type": type_, "player_id": player_id,
            "team_id": team_id, "extra": extra}


def minutes_by_player(events, lengths):
    return {a.player_id: seconds_played(a) / 60 for a in compute_appearances(events, lengths)}


# Brazil v Belgium 2018 period lengths: 46:15.660 and 50:03.600
BRA_BEL = {1: mmss("46:15.660"), 2: mmss("50:03.600")}


def test_first_half_stoppage_counts_and_halftime_sub():
    events = [
        starting_xi(HOME, [10, 11]),
        sub(2, "00:00", HOME, off_id=11, on_id=12),
    ]
    m = minutes_by_player(events, BRA_BEL)
    assert m[10] == pytest.approx(96.3210)          # 96:19.260
    assert m[11] == pytest.approx(46.2610)          # whole first half incl. stoppage
    assert m[12] == pytest.approx(50.0600)          # whole second half


def test_extra_time_counted_and_shootout_ignored():
    lengths = {1: mmss("46:00"), 2: mmss("49:00"), 3: mmss("16:00"), 4: mmss("17:00"), 5: mmss("12:00")}
    events = [
        starting_xi(HOME, [10, 11]),
        sub(3, "05:00", HOME, off_id=11, on_id=12),
        event(5, "03:00", "Player Off", 10),     # shootout events must not end anyone's match
    ]
    m = minutes_by_player(events, lengths)
    assert m[10] == pytest.approx(128.0)
    assert m[11] == pytest.approx(46 + 49 + 5)
    assert m[12] == pytest.approx(11 + 17)


def test_straight_red_and_second_yellow():
    events = [
        starting_xi(HOME, [10, 11, 12]),
        event(1, "30:00", "Foul Committed", 10, foul_committed_card="Red Card"),
        event(2, "10:30", "Bad Behaviour", 11, bad_behaviour_card="Second Yellow"),
        event(2, "20:00", "Foul Committed", 12, foul_committed_card="Yellow Card"),
    ]
    m = minutes_by_player(events, BRA_BEL)
    assert m[10] == pytest.approx(30.0)
    assert m[11] == pytest.approx(46.2610 + 10.5)
    assert m[12] == pytest.approx(96.3210)          # a single yellow does not end a match


def test_substitute_with_no_individual_events_still_appears():
    events = [
        starting_xi(HOME, [10]),
        sub(2, "49:00", HOME, off_id=10, on_id=99),  # 99 never touches the ball
    ]
    m = minutes_by_player(events, BRA_BEL)
    assert 99 in m
    assert m[99] == pytest.approx(1.06)


def test_permanent_injury_exit_vs_temporary_stoppage():
    events = [
        starting_xi(HOME, [10, 11]),
        event(1, "20:00", "Player Off", 10),
        event(1, "21:00", "Player On", 10),          # treated and returned
        event(2, "40:00", "Player Off", 11),         # never returns, no replacement
    ]
    m = minutes_by_player(events, BRA_BEL)
    assert m[10] == pytest.approx(96.3210)
    assert m[11] == pytest.approx(46.2610 + 40)


def test_enter_and_leave_within_the_same_minute():
    events = [
        starting_xi(HOME, [10]),
        sub(2, "40:10", HOME, off_id=10, on_id=20),
        sub(2, "40:50", HOME, off_id=20, on_id=21),
    ]
    m = minutes_by_player(events, BRA_BEL)
    assert m[20] == pytest.approx(40 / 60)          # 40 seconds, not 0 or 1 minute
    assert m[20] > 0
