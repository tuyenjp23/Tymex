"""Lớp truy cập dữ liệu. Toàn bộ SQL của ứng dụng nằm ở đây."""
from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

from ..data_providers.base import LeagueDTO, MatchDTO, StandingDTO, TeamDTO
from ..utils import search_key, to_iso, utcnow
from .db import Database

MATCH_SELECT = """
SELECT m.*, l.name AS league_name, l.code AS league_code, l.emblem_url AS league_emblem,
       ht.name AS home_name, ht.short_name AS home_short, ht.crest_url AS home_crest,
       at_.name AS away_name, at_.short_name AS away_short, at_.crest_url AS away_crest
FROM matches m
JOIN leagues l ON l.id = m.league_id
JOIN teams ht ON ht.id = m.home_team_id
JOIN teams at_ ON at_.id = m.away_team_id
"""


def _now() -> str:
    return to_iso(utcnow())


def _dicts(cur) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ giải đấu
    def upsert_league(self, provider: str, dto: LeagueDTO) -> int:
        with self.db.connect() as c:
            c.execute(
                """INSERT INTO leagues (provider, code, name, country, type, emblem_url, current_season, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(provider, code) DO UPDATE SET
                     name=excluded.name, country=COALESCE(excluded.country, leagues.country),
                     type=excluded.type, emblem_url=excluded.emblem_url,
                     current_season=COALESCE(excluded.current_season, leagues.current_season),
                     updated_at=excluded.updated_at""",
                (provider, dto.code, dto.name, dto.country, dto.type, dto.emblem_url, dto.current_season, _now()),
            )
            return c.execute("SELECT id FROM leagues WHERE provider=? AND code=?", (provider, dto.code)).fetchone()["id"]

    def list_leagues(self) -> list[dict]:
        with self.db.connect() as c:
            return _dicts(c.execute("SELECT * FROM leagues ORDER BY name"))

    def get_league(self, league_id: int) -> dict | None:
        with self.db.connect() as c:
            r = c.execute("SELECT * FROM leagues WHERE id=?", (league_id,)).fetchone()
            return dict(r) if r else None

    def get_league_by_code(self, provider: str, code: str) -> dict | None:
        with self.db.connect() as c:
            r = c.execute("SELECT * FROM leagues WHERE provider=? AND code=?", (provider, code)).fetchone()
            return dict(r) if r else None

    # ------------------------------------------------------------------ đội bóng
    def upsert_team(self, provider: str, dto: TeamDTO) -> int:
        with self.db.connect() as c:
            return self._upsert_team(c, provider, dto)

    def _upsert_team(self, c, provider: str, dto: TeamDTO) -> int:
        c.execute(
            """INSERT INTO teams (provider, external_id, name, short_name, tla, crest_url, search_name, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(provider, external_id) DO UPDATE SET
                 name=excluded.name, short_name=excluded.short_name, tla=excluded.tla,
                 crest_url=excluded.crest_url, search_name=excluded.search_name, updated_at=excluded.updated_at""",
            (provider, dto.external_id, dto.name, dto.short_name, dto.tla, dto.crest_url,
             search_key(f"{dto.name} {dto.short_name or ''} {dto.tla or ''}"), _now()),
        )
        return c.execute("SELECT id FROM teams WHERE provider=? AND external_id=?", (provider, dto.external_id)).fetchone()["id"]

    def list_teams(self, league_id: int | None = None, q: str | None = None) -> list[dict]:
        sql = "SELECT t.* FROM teams t"
        where, params = [], []
        if league_id:
            sql += (" JOIN (SELECT home_team_id AS tid FROM matches WHERE league_id=? "
                    "UNION SELECT away_team_id FROM matches WHERE league_id=?) x ON x.tid=t.id")
            params += [league_id, league_id]
        if q:
            where.append("t.search_name LIKE ?")
            params.append(f"%{search_key(q)}%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY t.name"
        with self.db.connect() as c:
            teams = _dicts(c.execute(sql, params))
            if not teams:
                return teams
            ids = [t["id"] for t in teams]
            by_team: dict[int, list[dict]] = {t["id"]: [] for t in teams}
            # Một truy vấn cho mọi đội (thay vì mỗi đội một truy vấn), chia lô để không vượt giới hạn tham số SQLite.
            for i in range(0, len(ids), 400):
                chunk = ids[i:i + 400]
                ph = ",".join("?" * len(chunk))
                rows = c.execute(
                    f"""SELECT x.tid, l.id, l.name FROM (
                           SELECT home_team_id AS tid, league_id FROM matches WHERE home_team_id IN ({ph})
                           UNION SELECT away_team_id, league_id FROM matches WHERE away_team_id IN ({ph})) x
                        JOIN leagues l ON l.id = x.league_id ORDER BY l.name""", chunk + chunk).fetchall()
                for r in rows:
                    by_team[r["tid"]].append({"id": r["id"], "name": r["name"]})
            for t in teams:
                t["leagues"] = by_team[t["id"]]
            return teams

    def get_team(self, team_id: int) -> dict | None:
        with self.db.connect() as c:
            r = c.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
            return dict(r) if r else None

    # ------------------------------------------------------------------ trận đấu
    def upsert_matches(self, provider: str, league_id: int, matches: Iterable[MatchDTO]) -> int:
        n = 0
        with self.db.connect() as c:
            cache: dict[str, int] = {}

            def team_id(t: TeamDTO) -> int:
                if t.external_id not in cache:
                    cache[t.external_id] = self._upsert_team(c, provider, t)
                return cache[t.external_id]

            for m in matches:
                c.execute(
                    """INSERT INTO matches (provider, external_id, league_id, season, matchday, stage, utc_date, status,
                         home_team_id, away_team_id, home_score, away_score, home_ht, away_ht, winner, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(provider, external_id) DO UPDATE SET
                         league_id=excluded.league_id, season=excluded.season, matchday=excluded.matchday,
                         stage=excluded.stage, utc_date=excluded.utc_date, status=excluded.status,
                         home_team_id=excluded.home_team_id, away_team_id=excluded.away_team_id,
                         home_score=excluded.home_score, away_score=excluded.away_score,
                         home_ht=excluded.home_ht, away_ht=excluded.away_ht, winner=excluded.winner,
                         updated_at=excluded.updated_at""",
                    (provider, m.external_id, league_id, m.season, m.matchday, m.stage, m.utc_date, m.status,
                     team_id(m.home), team_id(m.away), m.home_score, m.away_score, m.home_ht, m.away_ht, m.winner, _now()),
                )
                n += 1
        return n

    def has_matches(self, league_id: int, season: int) -> bool:
        with self.db.connect() as c:
            return c.execute("SELECT 1 FROM matches WHERE league_id=? AND season=? LIMIT 1", (league_id, season)).fetchone() is not None

    def get_match(self, match_id: int) -> dict | None:
        with self.db.connect() as c:
            r = c.execute(MATCH_SELECT + " WHERE m.id=?", (match_id,)).fetchone()
            return dict(r) if r else None

    def query_matches(self, *, date_from: str | None = None, date_to: str | None = None,
                      league_id: int | None = None, team_id: int | None = None,
                      statuses: Sequence[str] | None = None, q: str | None = None,
                      order: str = "asc", limit: int = 200) -> list[dict]:
        where, params = [], []
        if date_from:
            where.append("m.utc_date >= ?"); params.append(date_from)
        if date_to:
            where.append("m.utc_date < ?"); params.append(date_to)
        if league_id:
            where.append("m.league_id = ?"); params.append(league_id)
        if team_id:
            where.append("(m.home_team_id = ? OR m.away_team_id = ?)"); params += [team_id, team_id]
        if statuses:
            where.append(f"m.status IN ({','.join('?' * len(statuses))})"); params += list(statuses)
        if q:
            k = f"%{search_key(q)}%"
            where.append("(ht.search_name LIKE ? OR at_.search_name LIKE ?)"); params += [k, k]
        sql = MATCH_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        sql += f" ORDER BY m.utc_date {'DESC' if order == 'desc' else 'ASC'}, m.id LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self.db.connect() as c:
            return _dicts(c.execute(sql, params))

    def finished_matches(self, *, league_id: int | None = None, team_ids: Sequence[int] | None = None,
                         before: str | None = None, since: str | None = None, limit: int | None = None) -> list[dict]:
        """Các trận đã kết thúc thật sự (FINISHED, có tỷ số), mới nhất trước."""
        where = ["m.status = 'FINISHED'", "m.home_score IS NOT NULL", "m.away_score IS NOT NULL"]
        params: list[Any] = []
        if league_id:
            where.append("m.league_id = ?"); params.append(league_id)
        if team_ids:
            ph = ",".join("?" * len(team_ids))
            where.append(f"(m.home_team_id IN ({ph}) OR m.away_team_id IN ({ph}))"); params += list(team_ids) * 2
        if before:
            where.append("m.utc_date < ?"); params.append(before)
        if since:
            where.append("m.utc_date >= ?"); params.append(since)
        sql = MATCH_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY m.utc_date DESC, m.id DESC"
        if limit:
            sql += " LIMIT ?"; params.append(int(limit))
        with self.db.connect() as c:
            return _dicts(c.execute(sql, params))

    def get_match_statistics(self, match_id: int) -> dict | None:
        with self.db.connect() as c:
            r = c.execute("SELECT * FROM match_statistics WHERE match_id=?", (match_id,)).fetchone()
            return dict(r) if r else None

    # ------------------------------------------------------------------ bảng xếp hạng
    def replace_standings(self, league_id: int, provider: str, season: int | None, rows: Iterable[StandingDTO]) -> int:
        n = 0
        with self.db.connect() as c:
            c.execute("DELETE FROM standings WHERE league_id=?", (league_id,))
            for s in rows:
                tid = self._upsert_team(c, provider, s.team)
                c.execute(
                    """INSERT INTO standings (league_id, season, group_name, position, team_id, played, won, draw, lost,
                         points, goals_for, goals_against, goal_diff, form, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (league_id, season, s.group_name or "", s.position, tid, s.played, s.won, s.draw, s.lost,
                     s.points, s.goals_for, s.goals_against, s.goal_diff, s.form, _now()),
                )
                n += 1
        return n

    def get_standings(self, league_id: int) -> list[dict]:
        with self.db.connect() as c:
            return _dicts(c.execute(
                """SELECT s.*, t.name AS team_name, t.short_name, t.crest_url FROM standings s
                   JOIN teams t ON t.id = s.team_id WHERE s.league_id=? ORDER BY s.group_name, s.position""", (league_id,)))

    # ------------------------------------------------------------------ dự đoán
    def save_prediction(self, match_id: int, kind: str, model_version: str, created_at: str, fingerprint: str,
                        output: dict) -> int:
        with self.db.connect() as c:
            cur = c.execute(
                """INSERT INTO predictions (match_id, kind, model_version, created_at, data_fingerprint,
                     lambda_home, lambda_away, p_home, p_draw, p_away, predicted_home, predicted_away, details_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (match_id, kind, model_version, created_at, fingerprint, output["lambda_home"], output["lambda_away"],
                 output["p_home"], output["p_draw"], output["p_away"], output["predicted_score"]["home"],
                 output["predicted_score"]["away"], json.dumps(output, ensure_ascii=False)),
            )
            return cur.lastrowid

    def latest_prediction(self, match_id: int, kind: str = "live", before: str | None = None) -> dict | None:
        sql = "SELECT * FROM predictions WHERE match_id=? AND kind=?"
        params: list[Any] = [match_id, kind]
        if before:
            sql += " AND created_at < ?"; params.append(before)
        sql += " ORDER BY created_at DESC, id DESC LIMIT 1"
        with self.db.connect() as c:
            r = c.execute(sql, params).fetchone()
            return self._prediction_row(r) if r else None

    @staticmethod
    def _prediction_row(r) -> dict:
        d = dict(r)
        d["details"] = json.loads(d.pop("details_json"))
        return d

    def has_prediction(self, match_id: int, kind: str, model_version: str) -> bool:
        with self.db.connect() as c:
            return c.execute("SELECT 1 FROM predictions WHERE match_id=? AND kind=? AND model_version=? LIMIT 1",
                             (match_id, kind, model_version)).fetchone() is not None

    def finished_matches_with_unscored_live_prediction(self) -> list[dict]:
        """Trận đã kết thúc, có dự đoán 'live' tạo trước giờ bóng lăn, nhưng chưa được chấm điểm."""
        with self.db.connect() as c:
            rows = c.execute(
                """SELECT m.id AS match_id FROM matches m
                   WHERE m.status='FINISHED' AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL
                     AND EXISTS (SELECT 1 FROM predictions p WHERE p.match_id=m.id AND p.kind='live' AND p.created_at < m.utc_date)
                     AND NOT EXISTS (SELECT 1 FROM prediction_results r
                                     JOIN predictions p2 ON p2.id = r.prediction_id
                                     WHERE r.match_id=m.id AND p2.kind='live')""").fetchall()
            return [dict(r) for r in rows]

    def save_result(self, prediction_id: int, match_id: int, result: dict) -> None:
        with self.db.connect() as c:
            c.execute(
                """INSERT OR IGNORE INTO prediction_results (prediction_id, match_id, home_score, away_score,
                     actual_outcome, predicted_outcome, correct, exact_score, brier, log_loss,
                     home_goal_error, away_goal_error, evaluated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (prediction_id, match_id, result["home_score"], result["away_score"], result["actual_outcome"],
                 result["predicted_outcome"], int(result["correct"]), int(result["exact_score"]), result["brier"],
                 result["log_loss"], result["home_goal_error"], result["away_goal_error"], _now()),
            )

    def list_predictions(self, *, kind: str | None = None, league_id: int | None = None,
                         limit: int = 100, offset: int = 0) -> list[dict]:
        where, params = [], []
        if kind:
            where.append("p.kind=?"); params.append(kind)
        if league_id:
            where.append("m.league_id=?"); params.append(league_id)
        sql = """SELECT p.id, p.match_id, p.kind, p.model_version, p.created_at, p.lambda_home, p.lambda_away,
                        p.p_home, p.p_draw, p.p_away, p.predicted_home, p.predicted_away,
                        m.utc_date, m.status, m.home_score, m.away_score,
                        l.name AS league_name, ht.name AS home_name, at_.name AS away_name,
                        r.actual_outcome, r.predicted_outcome, r.correct, r.exact_score, r.brier, r.log_loss
                 FROM predictions p
                 JOIN matches m ON m.id=p.match_id
                 JOIN leagues l ON l.id=m.league_id
                 JOIN teams ht ON ht.id=m.home_team_id
                 JOIN teams at_ ON at_.id=m.away_team_id
                 LEFT JOIN prediction_results r ON r.prediction_id=p.id"""
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.utc_date DESC, p.created_at DESC, p.id DESC LIMIT ? OFFSET ?"
        params += [max(1, min(limit, 500)), max(0, offset)]
        with self.db.connect() as c:
            return _dicts(c.execute(sql, params))

    def result_rows(self, kind: str) -> list[dict]:
        with self.db.connect() as c:
            return _dicts(c.execute(
                """SELECT r.*, p.kind, p.lambda_home, p.lambda_away, m.utc_date, m.league_id, l.name AS league_name
                   FROM prediction_results r
                   JOIN predictions p ON p.id=r.prediction_id
                   JOIN matches m ON m.id=r.match_id
                   JOIN leagues l ON l.id=m.league_id
                   WHERE p.kind=? ORDER BY m.utc_date""", (kind,)))

    def count_predictions(self, kind: str) -> int:
        with self.db.connect() as c:
            return c.execute("SELECT COUNT(*) AS n FROM predictions WHERE kind=?", (kind,)).fetchone()["n"]

    # ------------------------------------------------------------------ bài viết AI
    def save_article(self, match_id: int, content: str, model: str, data_hash: str, payload: dict) -> int:
        with self.db.connect() as c:
            cur = c.execute(
                "INSERT INTO analysis_articles (match_id, content, model, data_hash, payload_json, created_at) VALUES (?,?,?,?,?,?)",
                (match_id, content, model, data_hash, json.dumps(payload, ensure_ascii=False), _now()))
            return cur.lastrowid

    def latest_article(self, match_id: int) -> dict | None:
        with self.db.connect() as c:
            r = c.execute("SELECT id, match_id, content, model, data_hash, created_at FROM analysis_articles "
                          "WHERE match_id=? ORDER BY created_at DESC, id DESC LIMIT 1", (match_id,)).fetchone()
            return dict(r) if r else None

    # ------------------------------------------------------------------ nhật ký đồng bộ
    def start_sync_log(self, provider: str, league_code: str | None) -> int:
        with self.db.connect() as c:
            cur = c.execute("INSERT INTO data_sync_logs (provider, league_code, started_at, status) VALUES (?,?,?, 'running')",
                            (provider, league_code, _now()))
            return cur.lastrowid

    def finish_sync_log(self, log_id: int, status: str, matches: int = 0, error_code: str | None = None,
                        message: str | None = None) -> None:
        with self.db.connect() as c:
            c.execute("UPDATE data_sync_logs SET finished_at=?, status=?, matches_upserted=?, error_code=?, message=? WHERE id=?",
                      (_now(), status, matches, error_code, message, log_id))

    def last_successful_sync(self, provider: str, league_code: str) -> str | None:
        with self.db.connect() as c:
            r = c.execute("SELECT MAX(finished_at) AS t FROM data_sync_logs WHERE provider=? AND league_code=? AND status='ok'",
                          (provider, league_code)).fetchone()
            return r["t"]

    def last_sync_overall(self) -> str | None:
        with self.db.connect() as c:
            return c.execute("SELECT MAX(finished_at) AS t FROM data_sync_logs WHERE status='ok'").fetchone()["t"]

    def list_sync_logs(self, limit: int = 30) -> list[dict]:
        with self.db.connect() as c:
            return _dicts(c.execute("SELECT * FROM data_sync_logs ORDER BY id DESC LIMIT ?", (limit,)))

    def counts(self) -> dict:
        with self.db.connect() as c:
            return {t: c.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                    for t in ("leagues", "teams", "matches", "predictions")}
