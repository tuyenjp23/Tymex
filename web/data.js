/* Lớp dữ liệu cho bản web (Cloudflare Pages + Supabase). Thay cho /api của bản chạy bằng Python:
   cùng tên đường dẫn, cùng dạng dữ liệu trả về, nên phần giao diện không phải đổi.
   Dữ liệu do GitHub Actions tính sẵn và đẩy lên Supabase; trình duyệt chỉ ĐỌC (bảo vệ bằng đăng nhập + RLS). */
"use strict";

const CFG = window.TYMEX_CONFIG || {};
const sb = (CFG.SUPABASE_URL && !CFG.SUPABASE_URL.includes("YOUR-PROJECT"))
  ? window.supabase.createClient(CFG.SUPABASE_URL, CFG.SUPABASE_ANON_KEY, { auth: { persistSession: true, autoRefreshToken: true } })
  : null;

const UPCOMING = ["SCHEDULED", "TIMED"];
const LIVE = ["IN_PLAY", "PAUSED"];

/* ---------------------------------------------------------------- đăng nhập */
const toEmail = (username) => {
  const u = String(username || "").trim();
  return u.includes("@") ? u : `${u}@${CFG.USERNAME_DOMAIN || "tymex.app"}`;
};
const auth = {
  configured: () => !!sb,
  async session() { return sb ? (await sb.auth.getSession()).data.session : null; },
  async signIn(username, password) {
    let res;
    try {
      res = await sb.auth.signInWithPassword({ email: toEmail(username), password });
    } catch (e) {
      throw new Error("Không kết nối được máy chủ đăng nhập. Kiểm tra mạng rồi thử lại.");
    }
    const { error } = res;
    if (!error) return;
    const msg = String(error.message || "");
    // Chỉ báo "sai mật khẩu" khi Supabase thật sự trả lỗi thông tin đăng nhập; các lỗi khác nói đúng nguyên nhân
    if (/invalid login credentials/i.test(msg)) throw new Error("Sai tên đăng nhập hoặc mật khẩu.");
    if (/email not confirmed/i.test(msg)) throw new Error("Tài khoản chưa được xác nhận. Vào Supabase > Authentication > Users và xác nhận tài khoản.");
    if (error.status === 429 || /rate limit|too many/i.test(msg)) throw new Error("Đã thử đăng nhập quá nhiều lần. Đợi vài phút rồi thử lại.");
    if (/fetch|network|failed to|timeout/i.test(msg) || error.status >= 500 || error.status === 0) throw new Error("Máy chủ đăng nhập không phản hồi (" + (error.status || "mạng") + "). Thử lại sau ít phút.");
    throw new Error("Không đăng nhập được: " + msg);
  },
  async signOut() { await sb.auth.signOut(); },
  onChange(cb) { sb?.auth.onAuthStateChange((_event, session) => cb(session)); },
};

/* ---------------------------------------------------------------- tiện ích */
const searchKey = (t) => String(t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase().trim();
const isoZ = (d) => d.toISOString().replace(/\.\d{3}Z$/, "Z");

function tzOffsetMs(ms, timeZone) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
    .formatToParts(new Date(ms)).filter((x) => x.type !== "literal").map((x) => [x.type, x.value]));
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(ms / 1000) * 1000;
}
/** [đầu ngày, đầu ngày kế tiếp) theo múi giờ `timeZone`, đổi sang UTC dạng ISO (khớp định dạng văn bản trong CSDL). */
function dayRangeUtc(ymd, timeZone) {
  const [y, m, d] = ymd.split("-").map(Number);
  const startOf = (yy, mm, dd) => {
    const guess = Date.UTC(yy, mm - 1, dd);
    const first = guess - tzOffsetMs(guess, timeZone);
    return first - (tzOffsetMs(first, timeZone) - tzOffsetMs(guess, timeZone));
  };
  const next = new Date(Date.UTC(y, m - 1, d + 1));
  return [isoZ(new Date(startOf(y, m, d))), isoZ(new Date(startOf(next.getUTCFullYear(), next.getUTCMonth() + 1, next.getUTCDate())))];
}
const localDate = (timeZone, offsetDays = 0) => {
  const base = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const [y, m, d] = base.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + offsetDays)).toISOString().slice(0, 10);
};

const failure = (message, code = "error", status = 400) => Object.assign(new Error(message), { code, status });
const kvCache = new Map();
async function kv(key, ttlMs = 60000) {
  const hit = kvCache.get(key);
  if (hit && Date.now() - hit.t < ttlMs) return hit.v;
  const { data, error } = await sb.from("kv").select("payload").eq("key", key).maybeSingle();
  if (error) throw failure("Không đọc được dữ liệu: " + error.message, "read_error", 502);
  const v = data ? data.payload : null;
  kvCache.set(key, { t: Date.now(), v });
  return v;
}
const clearCache = () => kvCache.clear();

/* ---------------------------------------------------------------- các "endpoint" */
async function getMatches(p) {
  const zone = p.tz || "Asia/Tokyo";
  const now = new Date();
  let from = null, to = null;
  if (p.day) {
    let ymd;
    if (p.day === "today") ymd = localDate(zone);
    else if (p.day === "tomorrow") ymd = localDate(zone, 1);
    else if (p.day === "yesterday") ymd = localDate(zone, -1);
    else if (/^\d{4}-\d{2}-\d{2}$/.test(p.day)) ymd = p.day;
    else throw failure("Tham số day phải là today, tomorrow, yesterday hoặc YYYY-MM-DD.", "bad_date");
    [from, to] = dayRangeUtc(ymd, zone);
  }
  let statuses = null, asc = true;
  if (p.scope === "upcoming") { statuses = UPCOMING; const n = isoZ(now); from = from && from > n ? from : n; }
  else if (p.scope === "live") statuses = LIVE;
  else if (p.scope === "finished") { statuses = ["FINISHED"]; asc = false; }

  let q = sb.from("matches").select("*");
  if (from) q = q.gte("utc_date", from);
  if (to) q = q.lt("utc_date", to);
  if (p.league_id) q = q.eq("league_id", Number(p.league_id));
  if (p.team_id) { const t = Number(p.team_id); q = q.or(`home_team_id.eq.${t},away_team_id.eq.${t}`); }
  if (statuses) q = q.in("status", statuses);
  if (p.q) {
    const k = searchKey(p.q).replace(/[,()%*\\]/g, " ").trim();
    if (k) q = q.or(`home_search.ilike.%${k}%,away_search.ilike.%${k}%`);
  }
  const { data, error } = await q.order("utc_date", { ascending: asc }).order("id", { ascending: true }).limit(Math.min(Number(p.limit) || 100, 500));
  if (error) throw failure("Không đọc được lịch thi đấu: " + error.message, "read_error", 502);
  return { matches: data, count: data.length, tz: zone, range: { from, to } };
}

async function getStatus() {
  const [st, lg] = await Promise.all([kv("status", 30000), kv("leagues", 30000)]);
  const counts = st?.counts || { leagues: 0, teams: 0, matches: 0, predictions: 0 };
  return {
    provider: "football-data.org", has_api_key: true, ai_configured: false, default_timezone: "Asia/Tokyo",
    counts, has_data: counts.matches > 0, last_sync: st?.last_sync || null, published_at: st?.published_at || null,
    is_test_data: !!st?.is_test_data, leagues: lg?.leagues || [], server_time: isoZ(new Date()), sync: { running: false },
  };
}

async function cloudApi(path, opts = {}) {
  if (!sb) throw failure("Chưa cấu hình Supabase: hãy điền SUPABASE_URL và SUPABASE_ANON_KEY trong file config.js.", "not_configured");
  const url = new URL(path, "https://x.invalid");
  const p = Object.fromEntries(url.searchParams);
  const parts = url.pathname.split("/").filter(Boolean);
  if ((opts.method || "GET") !== "GET") throw failure("Chức năng này chạy tự động trên máy chủ (GitHub Actions), không bấm được từ trình duyệt.", "server_only", 405);

  if (parts[0] === "status") return getStatus();
  if (parts[0] === "matches" && parts.length === 1) return getMatches(p);
  if (parts[0] === "matches" && parts[2] === "analysis") {
    const { data, error } = await sb.from("analysis").select("payload").eq("match_id", Number(parts[1])).maybeSingle();
    if (error) throw failure("Không đọc được phân tích: " + error.message, "read_error", 502);
    const a = data?.payload?.[String(Number(p.form_n) >= 10 ? 10 : 5)];
    if (!a) throw failure("Chưa có phân tích sẵn cho trận này (chỉ tính sẵn cho các trận từ 30 ngày trước đến 14 ngày tới).", "not_found", 404);
    return a;
  }
  if (parts[0] === "teams") {
    const all = (await kv("teams"))?.teams || [];
    const k = searchKey(p.q || "");
    return { teams: all.filter((t) => (!p.league_id || t.leagues.some((l) => String(l.id) === String(p.league_id))) && (!k || (t.search || "").includes(k))) };
  }
  if (parts[0] === "standings") {
    const s = await kv(`standings:${Number(p.league_id)}`);
    if (!s) throw failure("Không tìm thấy giải đấu.", "not_found", 404);
    return s;
  }
  if (parts[0] === "predictions" && parts[1] === "summary") return (await kv(`summary:${p.kind === "backtest" ? "backtest" : "live"}`)) || { overall: { n: 0 }, by_league: [], by_month: [], baseline: { brier_uniform: 0.6667, log_loss_uniform: 1.0986 }, total_predictions: 0 };
  if (parts[0] === "predictions") {
    const r = (await kv(`predictions:${p.kind === "backtest" ? "backtest" : "live"}`)) || { predictions: [] };
    const rows = r.predictions.slice(0, Math.min(Number(p.limit) || 100, 500));
    return { predictions: rows, count: rows.length };
  }
  throw failure("Đường dẫn không tồn tại.", "not_found", 404);
}

window.Tymex = { auth, cloudApi, clearCache, configured: () => !!sb };
