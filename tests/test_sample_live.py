import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sample_live", ROOT / "scripts" / "sample_live.py")
sample_live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sample_live)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
LEAGUE = {"slug": "eng.1", "name": "Premier League (Anh)", "featured": True}
META = {
    "espn_event_id": "401879254", "league_slug": "eng.1", "league_name": "Premier League (Anh)",
    "home": "Crystal Palace", "away": "Newcastle United", "home_score": 1, "away_score": 1,
    "start_iso": "2026-10-26T11:00:00Z", "clock": "67'", "minute": 67, "status_detail": "Second half",
}


def fake_summary(home_pct="52.6", away_pct="47.4"):
    def team(side, pct):
        return {"homeAway": side, "team": {"displayName": side},
                "statistics": [{"name": "possessionPct", "displayValue": pct},
                               {"name": "totalShots", "displayValue": "9"}]}
    return {"boxscore": {"teams": [team("home", home_pct), team("away", away_pct)]}}


def fake_scoreboard(state="in"):
    return {"events": [{
        "id": 401879254, "date": "2026-10-26T11:00:00Z",
        "status": {"displayClock": "67'", "clock": {"value": 4020},
                   "type": {"state": state, "shortDetail": "67'"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": "1", "team": {"displayName": "Crystal Palace"}},
            {"homeAway": "away", "score": "1", "team": {"displayName": "Newcastle United"}},
        ]}],
    }]}


def make_sample(minutes=0, pct=52.6):
    return sample_live.extract_possession_sample(
        fake_summary(str(pct), str(round(100 - pct, 1))), META, NOW + timedelta(minutes=minutes))


def make_sample_seconds(seconds=0, pct=52.6):
    return sample_live.extract_possession_sample(
        fake_summary(str(pct), str(round(100 - pct, 1))), META, NOW + timedelta(seconds=seconds))


def test_extract_live_events_only_in_play():
    events = sample_live.extract_live_events(fake_scoreboard("in"), LEAGUE)
    assert len(events) == 1
    assert events[0]["espn_event_id"] == "401879254"
    assert events[0]["minute"] == 67 and events[0]["clock"] == "67'"
    assert sample_live.extract_live_events(fake_scoreboard("post"), LEAGUE) == []
    assert sample_live.extract_live_events(fake_scoreboard("pre"), LEAGUE) == []


def test_extract_live_events_accepts_numeric_clock_field():
    board = fake_scoreboard("in")
    board["events"][0]["status"] = {"displayClock": "67'", "clock": 4020,
                                    "type": {"state": "in", "shortDetail": "67'"}}
    events = sample_live.extract_live_events(board, LEAGUE)
    assert events[0]["minute"] == 67 and events[0]["clock"] == "67'"


def test_extract_possession_sample_from_fake_summary():
    s = sample_live.extract_possession_sample(fake_summary(), META, NOW)
    assert s["possession_home_pct"] == 52.6 and s["possession_away_pct"] == 47.4
    assert s["espn_event_id"] == "401879254" and s["league_slug"] == "eng.1"
    assert s["minute"] == 67 and s["clock"] == "67'"
    assert s["ts_utc"] == "2026-10-26T12:00:00Z"


def test_extract_possession_sample_missing_or_bad_data():
    no_poss = {"boxscore": {"teams": [{"homeAway": "home", "statistics": []},
                                      {"homeAway": "away", "statistics": []}]}}
    assert sample_live.extract_possession_sample(no_poss, META, NOW) is None
    assert sample_live.extract_possession_sample(fake_summary("abc", "47.4"), META, NOW) is None
    assert sample_live.extract_possession_sample(fake_summary("120", "-20"), META, NOW) is None


def test_parse_clock_stoppage_and_seconds():
    assert sample_live.parse_clock("45'+2'") == ("45'+2'", 47)
    assert sample_live.parse_clock("", 4020) == ("67'", 67)
    assert sample_live.parse_clock("") == ("", None)


def test_merge_payload_appends_and_builds_event_meta():
    out = sample_live.merge_payload(None, META, make_sample())
    assert out["event"]["home"] == "Crystal Palace" and out["event"]["league_slug"] == "eng.1"
    assert len(out["samples"]) == 1
    out2 = sample_live.merge_payload(out, META, make_sample(11))
    assert len(out2["samples"]) == 2
    assert out2["samples"][0]["ts_utc"] < out2["samples"][1]["ts_utc"]


def test_merge_payload_dedupes_same_five_minute_bucket():
    first = sample_live.merge_payload(None, META, make_sample(0))
    again = sample_live.merge_payload(first, META, make_sample(3))   # cùng xô 5 phút với mẫu đầu
    assert len(again["samples"]) == 1
    later = sample_live.merge_payload(again, META, make_sample(6))   # xô kế tiếp
    assert len(later["samples"]) == 2


def test_merge_payload_caps_at_40_samples():
    payload = None
    for i in range(45):
        payload = sample_live.merge_payload(payload, META, make_sample(i * 6))
    assert len(payload["samples"]) == sample_live.MAX_SAMPLES_PER_MATCH == 40
    # giữ 40 mẫu MỚI nhất
    assert payload["samples"][0]["ts_utc"] == make_sample(5 * 6)["ts_utc"]


def test_loop_merge_payload_dedupes_under_45_seconds_not_five_minute_bucket():
    kwargs = {"max_samples": sample_live.LOOP_MAX_SAMPLES_PER_MATCH,
              "min_interval_seconds": sample_live.LOOP_DEDUPE_SECONDS}
    first = sample_live.merge_payload(None, META, make_sample_seconds(0), **kwargs)
    too_close = sample_live.merge_payload(first, META, make_sample_seconds(30), **kwargs)
    assert len(too_close["samples"]) == 1          # <45 giây: trùng
    at_threshold = sample_live.merge_payload(too_close, META, make_sample_seconds(45), **kwargs)
    assert len(at_threshold["samples"]) == 2       # đúng 45 giây: mẫu mới
    # Mẫu sau 3 phút vẫn được giữ ở chế độ vòng lặp — đây là điểm khác xô 5 phút của chế độ chạy một lần.
    later = sample_live.merge_payload(at_threshold, META, make_sample_seconds(180), **kwargs)
    assert len(later["samples"]) == 3


def test_loop_merge_payload_caps_at_130_samples():
    kwargs = {"max_samples": sample_live.LOOP_MAX_SAMPLES_PER_MATCH,
              "min_interval_seconds": sample_live.LOOP_DEDUPE_SECONDS}
    payload = None
    for i in range(135):
        payload = sample_live.merge_payload(payload, META, make_sample_seconds(i * 90), **kwargs)
    assert len(payload["samples"]) == sample_live.LOOP_MAX_SAMPLES_PER_MATCH == 130
    assert payload["samples"][0]["ts_utc"] == make_sample_seconds(5 * 90)["ts_utc"]


def test_sampler_cli_defaults_are_single_pass_at_90_second_interval():
    args = sample_live.build_parser().parse_args([])
    assert args.loop_minutes == 0 and args.interval_seconds == 90 and not args.dry_run
    args = sample_live.build_parser().parse_args(["--loop-minutes", "52", "--interval-seconds", "90"])
    assert args.loop_minutes == 52 and args.interval_seconds == 90


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_run_loop_sleeps_only_remainder_of_interval():
    clock = FakeClock()
    calls = []

    def cycle():
        calls.append(clock.now)
        clock.now += 10          # mỗi chu kỳ chạy 10 giây -> chỉ ngủ 80 giây còn lại

    cycles = sample_live.run_loop(cycle, loop_minutes=4.5, interval_seconds=90,
                                  monotonic=clock.monotonic, sleep=clock.sleep, log=lambda _: None)
    assert cycles == 4
    assert calls == [0, 90, 180, 270]
    assert clock.sleeps == [80, 80, 80]


def test_run_loop_overrun_continues_immediately_and_logs():
    clock = FakeClock()
    logs = []

    def cycle():
        clock.now += 120         # chu kỳ chạy quá 90 giây

    cycles = sample_live.run_loop(cycle, loop_minutes=4, interval_seconds=90,
                                  monotonic=clock.monotonic, sleep=clock.sleep, log=logs.append)
    assert cycles == 2
    assert clock.sleeps == []
    assert logs and "bắt đầu chu kỳ kế tiếp ngay" in logs[0]


def test_merge_payload_tolerates_malformed_existing():
    out = sample_live.merge_payload({"samples": [{"no_ts": 1}, "junk"]}, META, make_sample())
    assert len(out["samples"]) == 1


def test_load_leagues_matches_web_live_js():
    leagues = sample_live.load_leagues()
    slugs = {lg["slug"] for lg in leagues}
    assert {"uefa.champions", "eng.1", "jpn.1", "ksa.1", "usa.1", "conmebol.libertadores"} <= slugs
    assert len(leagues) >= 40
    assert leagues[0]["slug"] == "uefa.champions"
