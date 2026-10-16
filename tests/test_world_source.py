from app.history.sources import parse_world_txt, world_url

SAMPLE = """= Test League 2024/25

# Teams 4

▪ Matchday 1
  Thu Aug 22 2024
    19:10  Al Taawoun              v Al Fayha                 1-0 (0-0)
           Al Nassr                v Al Ra'ed                 1-1 (1-0)
  Fri Aug 23
    19:10  Damac FC                v Al Khaleej               0-1
    21:00  Postponed FC            v Other FC                 [postponed]

▪ Matchday 2
  Wed Jan 14
    16:00  A FC                    v B FC                     2-3 a.e.t. (1-1)
  08.09.
    16:00  Abia FC                 v Remo FC                  0-2 (0-0)
"""


def test_parse_world_txt_dates_scores_and_skips():
    rows = parse_world_txt(SAMPLE, code="x1", season=2024, tz="UTC", today_iso="2030-01-01")
    got = {(r["home"], r["away"]): r for r in rows}
    assert len(rows) == 4                                   # hoãn / kéo dài bị bỏ
    r = got[("Al Taawoun", "Al Fayha")]
    assert (r["home_score"], r["away_score"], r["home_ht"]) == (1, 0, 0)
    assert r["utc_date"].startswith("2024-08-22T19:10")
    assert got[("Al Nassr", "Al Ra'ed")]["utc_date"].startswith("2024-08-22T19:10")   # dòng không giờ dùng giờ dòng trước
    assert got[("Damac FC", "Al Khaleej")]["utc_date"].startswith("2024-08-23")
    assert got[("Abia FC", "Remo FC")]["utc_date"].startswith("2024-09-08")            # kiểu dd.mm. không thứ


def test_parse_world_txt_future_unplayed_is_scheduled():
    txt = "▪ Matchday 1\n  Sat Mar 8 2031\n    15:00  A FC   v B FC\n"
    rows = parse_world_txt(txt, code="x1", season=2030, tz="UTC", today_iso="2030-01-01")
    assert rows[0]["status"] == "SCHEDULED" and rows[0]["home_score"] is None


def test_world_url():
    w = {"path": "africa/kenya", "code": "ke1"}
    assert world_url(w, 2025, False).endswith("/africa/kenya/2025-26_ke1.txt")
    assert world_url({"path": "asia/china", "code": "cn1"}, 2025, True).endswith("/asia/china/2025_cn1.txt")
