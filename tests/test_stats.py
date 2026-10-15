from app.analytics.stats import head_to_head, summarize, team_form, team_games, venue_stats
from tests.conftest import mk

KICKOFF = "2025-11-20T12:00:00Z"


def sample():
    return [
        mk(1, "2025-10-01T12:00:00Z", 1, 2, 2, 0),   # đội 1 thắng nhà
        mk(2, "2025-10-08T12:00:00Z", 3, 1, 1, 1),   # đội 1 hòa sân khách
        mk(3, "2025-10-15T12:00:00Z", 1, 4, 0, 3),   # đội 1 thua nhà
        mk(4, "2025-10-22T12:00:00Z", 5, 1, 0, 2),   # đội 1 thắng sân khách, giữ sạch lưới
        mk(5, "2025-10-29T12:00:00Z", 1, 6, 3, 1),   # thắng nhà
        mk(6, "2025-11-05T12:00:00Z", 7, 1, 2, 1),   # thua sân khách
        mk(7, "2025-11-12T12:00:00Z", 1, 8, 1, 1),   # hòa nhà
    ]


def test_form_picks_last_5_finished_before_kickoff_in_order():
    f = team_form(sample(), 1, KICKOFF, 5)
    assert [g["match_id"] for g in f["games"]] == [7, 6, 5, 4, 3]
    assert f["form_string"] == "DLWWL"
    s = f["summary"]
    assert (s["wins"], s["draws"], s["losses"]) == (2, 1, 2)
    assert s["points"] == 7
    assert s["goals_for"] == 1 + 1 + 3 + 2 + 0 and s["goals_against"] == 1 + 2 + 1 + 0 + 3
    assert s["avg_goals_for"] == 1.4 and s["avg_goals_against"] == 1.4
    assert s["clean_sheets"] == 1
    assert f["home_games"] == 3 and f["away_games"] == 2


def test_unfinished_and_future_matches_are_excluded():
    matches = sample() + [
        mk(8, "2025-11-15T12:00:00Z", 1, 9, None, None, status="SCHEDULED"),   # chưa đá
        mk(9, "2025-11-16T12:00:00Z", 1, 9, 1, 0, status="IN_PLAY"),           # đang đá
        mk(10, "2025-11-17T12:00:00Z", 1, 9, None, None, status="POSTPONED"),  # hoãn
        mk(11, "2025-11-25T12:00:00Z", 1, 9, 5, 0),                            # SAU giờ bóng lăn (tương lai)
        mk(12, KICKOFF, 1, 9, 4, 0),                                           # đúng giờ bóng lăn: không tính
    ]
    ids = [g["match_id"] for g in team_form(matches, 1, KICKOFF, 5)["games"]]
    assert ids == [7, 6, 5, 4, 3]


def test_exclude_the_analysed_match_itself():
    games = team_games(sample(), 1, "2025-12-01T00:00:00Z", exclude_id=7)
    assert 7 not in [g["id"] for g in games]


def test_fewer_than_n_games_is_reported_honestly():
    f = team_form(sample()[:2], 1, KICKOFF, 5)
    assert f["available"] == 2 and f["requested"] == 5


def test_no_games_gives_none_averages():
    s = summarize([])
    assert s["played"] == 0 and s["avg_goals_for"] is None and s["points_per_game"] is None


def test_venue_split():
    home = venue_stats(sample(), 1, "home", KICKOFF, 10)["summary"]
    away = venue_stats(sample(), 1, "away", KICKOFF, 10)["summary"]
    assert home["played"] == 4 and away["played"] == 3
    assert home["wins"] == 2 and home["losses"] == 1 and home["draws"] == 1
    assert away["wins"] == 1 and away["draws"] == 1 and away["losses"] == 1
    assert home["clean_sheet_rate"] == 25.0 and home["clean_sheets"] == 1 and away["clean_sheets"] == 1


def test_head_to_head_summary_and_limit():
    ms = [
        mk(1, "2024-01-01T12:00:00Z", 1, 2, 2, 1),
        mk(2, "2024-06-01T12:00:00Z", 2, 1, 0, 0),
        mk(3, "2025-01-01T12:00:00Z", 2, 1, 3, 1),
        mk(4, "2025-05-01T12:00:00Z", 1, 2, 1, 0),
        mk(5, "2025-06-01T12:00:00Z", 1, 3, 9, 9),                       # không phải đối đầu
        mk(6, "2026-01-01T12:00:00Z", 1, 2, 4, 0),                       # tương lai
        mk(7, "2025-08-01T12:00:00Z", 1, 2, None, None, status="SCHEDULED"),
    ]
    h = head_to_head(ms, 1, 2, KICKOFF)
    assert h["available"] == 4
    s = h["summary"]
    assert (s["a_wins"], s["draws"], s["b_wins"]) == (2, 1, 1)
    assert (s["a_goals"], s["b_goals"]) == (2 + 0 + 1 + 1, 1 + 0 + 3 + 0)
    assert [g["match_id"] for g in h["games"]] == [4, 3, 2, 1]
    assert [g["winner"] for g in h["games"]] == ["A", "B", "D", "A"]
    assert head_to_head(ms, 1, 2, KICKOFF, limit=2)["available"] == 2


def test_head_to_head_never_invents_matches():
    h = head_to_head([], 1, 2, KICKOFF)
    assert h["available"] == 0 and h["games"] == [] and h["summary"]["played"] == 0
