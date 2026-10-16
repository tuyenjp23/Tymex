from app.history.audit import audit, format_audit
from app.history.importer import import_matches
from app.history.leagues import BY_CODE
from app.history.teams import TeamResolver
from app.utils import utcnow

SPEC = BY_CODE["KE1"]


def row(home, away, utc, status="FINISHED", hg=1, ag=0, eid=None):
    return {"external_id": eid or f"t:{home}:{away}:{utc}", "season": 2025, "matchday": 1, "utc_date": utc, "status": status,
            "home": home, "away": away, "home_score": hg if status == "FINISHED" else None, "away_score": ag if status == "FINISHED" else None,
            "home_ht": None, "away_ht": None, "winner": "HOME_TEAM" if status == "FINISHED" else None, "odds": None, "odds_source": None}


def test_postponed_match_updates_old_row_instead_of_duplicating(repo):
    res = TeamResolver(repo)
    import_matches(repo, source="s1", spec=SPEC, matches=[row("Gor Mahia FC", "Tusker FC", "2025-03-01T12:00:00Z", status="SCHEDULED")], resolver=res)
    out = import_matches(repo, source="s2", spec=SPEC, matches=[row("Gor Mahia FC", "Tusker FC", "2025-04-20T12:00:00Z")], resolver=res)
    assert out["added"] == 0 and out["duplicates"] == 1
    with repo.db.connect() as c:
        rows = c.execute("SELECT status, utc_date FROM matches").fetchall()
    assert len(rows) == 1 and rows[0]["status"] == "FINISHED" and rows[0]["utc_date"].startswith("2025-04-20")


def test_future_second_fixture_is_not_merged(repo):
    res = TeamResolver(repo)
    import_matches(repo, source="s1", spec=SPEC, matches=[row("Gor Mahia FC", "Tusker FC", "2999-03-01T12:00:00Z", status="SCHEDULED")], resolver=res)
    out = import_matches(repo, source="s2", spec=SPEC, matches=[row("Gor Mahia FC", "Tusker FC", "2025-01-20T12:00:00Z")], resolver=res)
    assert out["added"] == 1


def test_audit_finds_split_team(repo):
    res = TeamResolver(repo)
    # hai nguồn viết đối thủ khác nhau: 'Zeta United' và 'Zeta Utd FC Nairobi' không tự ghép được
    import_matches(repo, source="s1", spec=SPEC, matches=[row("Gor Mahia FC", "Zeta United", "2025-03-01T12:00:00Z")], resolver=res)
    import_matches(repo, source="s2", spec=SPEC, matches=[row("Gor Mahia FC", "Qwerty Wanderers", "2025-03-01T13:00:00Z")], resolver=res)
    a = audit(repo, now=utcnow())
    assert len(a["split_teams"]) == 1
    names = {a["split_teams"][0]["a"], a["split_teams"][0]["b"]}
    assert names == {"Zeta United", "Qwerty Wanderers"}
    assert any("<->" in l for l in format_audit(a))


def test_same_score_other_date_is_same_match(repo):
    res = TeamResolver(repo)
    import_matches(repo, source="s1", spec=SPEC, matches=[row("Gor Mahia FC", "Tusker FC", "2025-12-02T19:45:00Z", hg=2, ag=1)], resolver=res)
    out = import_matches(repo, source="s2", spec=SPEC, matches=[row("Gor Mahia FC", "Tusker FC", "2025-12-09T18:45:00Z", hg=2, ag=1)], resolver=res)
    assert out["added"] == 0 and out["duplicates"] == 1
    out = import_matches(repo, source="s2", spec=SPEC, matches=[row("Gor Mahia FC", "Tusker FC", "2025-12-09T18:45:00Z", hg=0, ag=0, eid="other")], resolver=res)
    assert out["added"] == 1                                   # tỷ số khác thì coi là trận khác


def test_hand_alias_beats_directory_ids(repo):
    r = TeamResolver(repo)
    for a, b, c in [("RB Bragantino", "Bragantino", "Brazil"), ("Accrington", "Accrington Stanley", "England"),
                    ("Karagumruk", "Fatih Karagümrük", "Turkey"), ("New York RB", "New York Red Bulls", "USA"),
                    ("San Martin S.J.", "San Martín de San Juan", "Argentina"), ("Gimnasia L.P.", "Gimnasia de La Plata", "Argentina")]:
        assert r.resolve(a, c) == r.resolve(b, c), (a, b)
