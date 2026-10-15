"""Lược đồ cơ sở dữ liệu (SQL chuẩn, tương thích SQLite; dễ chuyển sang PostgreSQL).

Ghi chú thiết kế:
- "team_form" và "head_to_head" KHÔNG lưu bảng riêng: chúng luôn được tính lại từ bảng `matches`
  tại thời điểm cần (tránh dữ liệu lỗi thời và tránh rò rỉ thông tin tương lai).
- `match_statistics` đã có sẵn cột xG/cú sút/kiểm soát bóng cho nhà cung cấp dữ liệu hỗ trợ sau này.
  football-data.org (gói miễn phí) không cung cấp các trường này nên bảng sẽ để trống.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS leagues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    country TEXT,
    type TEXT,
    emblem_url TEXT,
    current_season INTEGER,
    updated_at TEXT NOT NULL,
    UNIQUE (provider, code)
);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT,
    tla TEXT,
    crest_url TEXT,
    search_name TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (provider, external_id)
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    league_id INTEGER NOT NULL REFERENCES leagues(id),
    season INTEGER,
    matchday INTEGER,
    stage TEXT,
    utc_date TEXT NOT NULL,
    status TEXT NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES teams(id),
    away_team_id INTEGER NOT NULL REFERENCES teams(id),
    home_score INTEGER,
    away_score INTEGER,
    home_ht INTEGER,
    away_ht INTEGER,
    winner TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches (utc_date);
CREATE INDEX IF NOT EXISTS idx_matches_league_date ON matches (league_id, utc_date);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches (home_team_id, utc_date);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches (away_team_id, utc_date);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches (status);

CREATE TABLE IF NOT EXISTS match_statistics (
    match_id INTEGER PRIMARY KEY REFERENCES matches(id),
    source TEXT NOT NULL,
    home_xg REAL, away_xg REAL,
    home_shots INTEGER, away_shots INTEGER,
    home_shots_on_target INTEGER, away_shots_on_target INTEGER,
    home_possession REAL, away_possession REAL,
    home_chances_created INTEGER, away_chances_created INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS standings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id INTEGER NOT NULL REFERENCES leagues(id),
    season INTEGER,
    group_name TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    played INTEGER, won INTEGER, draw INTEGER, lost INTEGER,
    points INTEGER, goals_for INTEGER, goals_against INTEGER, goal_diff INTEGER,
    form TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (league_id, group_name, team_id)
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    kind TEXT NOT NULL,                -- 'live' = tạo trước trận; 'backtest' = kiểm tra lại trên trận cũ
    model_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data_fingerprint TEXT,
    lambda_home REAL NOT NULL,
    lambda_away REAL NOT NULL,
    p_home REAL NOT NULL,
    p_draw REAL NOT NULL,
    p_away REAL NOT NULL,
    predicted_home INTEGER NOT NULL,
    predicted_away INTEGER NOT NULL,
    details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions (match_id, kind, created_at);

CREATE TABLE IF NOT EXISTS prediction_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id INTEGER NOT NULL UNIQUE REFERENCES predictions(id),
    match_id INTEGER NOT NULL REFERENCES matches(id),
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    actual_outcome TEXT NOT NULL,
    predicted_outcome TEXT NOT NULL,
    correct INTEGER NOT NULL,
    exact_score INTEGER NOT NULL,
    brier REAL NOT NULL,
    log_loss REAL NOT NULL,
    home_goal_error REAL NOT NULL,
    away_goal_error REAL NOT NULL,
    evaluated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    content TEXT NOT NULL,
    model TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_match ON analysis_articles (match_id, created_at);

CREATE TABLE IF NOT EXISTS data_sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    league_code TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,              -- running | ok | error | skipped
    matches_upserted INTEGER DEFAULT 0,
    error_code TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_logs ON data_sync_logs (provider, league_code, started_at);

CREATE TABLE IF NOT EXISTS match_odds (
    match_id INTEGER PRIMARY KEY REFERENCES matches(id),
    source TEXT NOT NULL,              -- ví dụ AvgC = trung bình tỷ lệ cược lúc đóng cửa (football-data.co.uk)
    odds_home REAL NOT NULL,
    odds_draw REAL NOT NULL,
    odds_away REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history_imports (
    source TEXT NOT NULL,
    league_code TEXT NOT NULL,
    season INTEGER NOT NULL,
    rows_seen INTEGER NOT NULL DEFAULT 0,
    rows_added INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (source, league_code, season)
);
"""
