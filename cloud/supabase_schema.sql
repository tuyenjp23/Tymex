-- Chạy MỘT LẦN trong Supabase → SQL Editor → New query → dán toàn bộ → Run.
-- Dữ liệu chỉ được GHI bởi GitHub Actions (khóa service_role, bỏ qua RLS). Trình duyệt chỉ ĐỌC và chỉ khi đã đăng nhập.

create table if not exists public.matches (
  id            bigint primary key,
  league_id     bigint,
  league_name   text,
  league_code   text,
  season        int,
  matchday      int,
  stage         text,
  utc_date      text not null,        -- ISO UTC dạng 2025-11-20T10:00:00Z (so sánh chuỗi = so sánh thời gian)
  status        text not null,
  home_team_id  bigint,
  away_team_id  bigint,
  home_name     text,
  away_name     text,
  home_short    text,
  away_short    text,
  home_crest    text,
  away_crest    text,
  home_score    int,
  away_score    int,
  home_ht       int,
  away_ht       int,
  winner        text,
  is_test_data  boolean default false,
  home_search   text,
  away_search   text,
  updated_at    text
);
create index if not exists idx_matches_date   on public.matches (utc_date);
create index if not exists idx_matches_league on public.matches (league_id, utc_date);
create index if not exists idx_matches_home   on public.matches (home_team_id);
create index if not exists idx_matches_away   on public.matches (away_team_id);

create table if not exists public.analysis (
  match_id    bigint primary key,
  payload     jsonb not null,         -- {"5": {...}, "10": {...}} (phân tích với 5 và 10 trận gần nhất)
  updated_at  text
);

create table if not exists public.kv (
  key         text primary key,       -- teams, leagues, status, standings:<id>, summary:live, predictions:live ...
  payload     jsonb not null,
  updated_at  text
);

-- Bật Row Level Security: không có chính sách ghi nào => người dùng trình duyệt không ghi/xóa được gì.
alter table public.matches  enable row level security;
alter table public.analysis enable row level security;
alter table public.kv       enable row level security;

drop policy if exists "doc khi da dang nhap" on public.matches;
drop policy if exists "doc khi da dang nhap" on public.analysis;
drop policy if exists "doc khi da dang nhap" on public.kv;
create policy "doc khi da dang nhap" on public.matches  for select to authenticated using (true);
create policy "doc khi da dang nhap" on public.analysis for select to authenticated using (true);
create policy "doc khi da dang nhap" on public.kv       for select to authenticated using (true);
-- Người chưa đăng nhập (vai trò "anon") không có chính sách nào => không đọc được gì dù biết khóa anon.
