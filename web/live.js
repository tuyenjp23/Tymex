/* Trang Trực tiếp (bản web): mô hình dự đoán trực tiếp + mô phỏng trận, port từ app/prediction/live.py
   (giữ nguyên hằng số và công thức để hai bản khớp nhau), cộng lớp lấy dữ liệu:
   - Tỷ số trực tiếp: ESPN (site.api.espn.com, có CORS mở) cho các giải lớn ở châu Âu/châu Á/châu Mỹ (nhóm dưới đây),
     cộng lượt quét toàn cầu TheSportsDB để phủ các giải ESPN không có (K League, V.League...) và dự phòng khi ESPN sập.
   - Thống kê chi tiết 1 trận: ESPN summary (boxscore + keyEvents). Chỉ hiển thị số liệu nguồn thật sự trả về.
   Phần "mô phỏng" trong file này là diễn biến GIẢ LẬP bằng mô hình, luôn được gắn nhãn rõ trên giao diện. */
"use strict";

const LIVE_FULL_MINUTES = 95;          // 90 phút + ~5 phút bù giờ trung bình (giống FULL_MINUTES ở live.py)
const LIVE_RHO = -0.08;                 // Dixon-Coles, giống ModelParams.dixon_coles_rho
/* Danh sách giải lấy từ ESPN — mọi slug dưới đây đã được kiểm chứng trả HTTP 200 trên ESPN (2026-10-26).
   `featured` = nhóm ưu tiên (Cúp C1/C2/C3 châu Âu, 5 giải lớn châu Âu, AFC Champions League, J1, MLS,
   Libertadores): làm mới mỗi 60 giây. Các giải còn lại làm mới thưa hơn (xem fetchEspnEvents) để không
   gọi dồn dập hơn 40 endpoint từ trình duyệt.
   KHÔNG có trên ESPN (trả 400, đừng thêm): K League (kor.1), V.League Việt Nam (vie.1), Qatar (qat.1), UAE (uae.1)
   — hai giải K League 1 và V.League 1 được bao phủ nhờ lượt quét toàn cầu TheSportsDB trong fetchLiveEvents. */
const LIVE_LEAGUE_GROUPS = [
  { region: "Châu Âu", leagues: [
    { slug: "uefa.champions", name: "Champions League (Cúp C1)", featured: true },
    { slug: "uefa.europa", name: "Europa League (Cúp C2)", featured: true },
    { slug: "uefa.europa.conf", name: "Conference League (Cúp C3)", featured: true },
    { slug: "eng.1", name: "Premier League (Anh)", featured: true },
    { slug: "esp.1", name: "La Liga (Tây Ban Nha)", featured: true },
    { slug: "ita.1", name: "Serie A (Ý)", featured: true },
    { slug: "ger.1", name: "Bundesliga (Đức)", featured: true },
    { slug: "fra.1", name: "Ligue 1 (Pháp)", featured: true },
    { slug: "por.1", name: "Primeira Liga (Bồ Đào Nha)" },
    { slug: "ned.1", name: "Eredivisie (Hà Lan)" },
    { slug: "tur.1", name: "Süper Lig (Thổ Nhĩ Kỳ)" },
    { slug: "sco.1", name: "Premiership (Scotland)" },
    { slug: "bel.1", name: "Pro League (Bỉ)" },
    { slug: "eng.fa", name: "FA Cup (Anh)" },
    { slug: "esp.copa_del_rey", name: "Copa del Rey (Tây Ban Nha)" },
    { slug: "ger.dfb_pokal", name: "DFB-Pokal (Đức)" },
    { slug: "ita.coppa_italia", name: "Coppa Italia (Ý)" },
    { slug: "fra.coupe_de_france", name: "Coupe de France (Pháp)" },
    { slug: "eng.league_cup", name: "League Cup (Anh)" },
  ] },
  { region: "Châu Á", leagues: [
    { slug: "afc.champions", name: "AFC Champions League Elite", featured: true },
    { slug: "afc.cup", name: "AFC Champions League Two" },
    { slug: "jpn.1", name: "J.League 1 (Nhật Bản)", featured: true },
    { slug: "ksa.1", name: "Saudi Pro League (Ả Rập Xê Út)" },
    { slug: "chn.1", name: "Super League (Trung Quốc)" },
    { slug: "tha.1", name: "Thai League 1 (Thái Lan)" },
    { slug: "idn.1", name: "Liga 1 (Indonesia)" },
    { slug: "mys.1", name: "Super League (Malaysia)" },
    { slug: "ind.1", name: "Super League (Ấn Độ)" },
    { slug: "aus.1", name: "A-League (Úc)" },
    { slug: "afc.asian.cup", name: "Asian Cup" },
  ] },
  { region: "Châu Mỹ", leagues: [
    { slug: "conmebol.libertadores", name: "Copa Libertadores", featured: true },
    { slug: "conmebol.sudamericana", name: "Copa Sudamericana" },
    { slug: "concacaf.champions", name: "CONCACAF Champions Cup" },
    { slug: "usa.1", name: "MLS (Mỹ)", featured: true },
    { slug: "mex.1", name: "Liga MX (Mexico)" },
    { slug: "bra.1", name: "Série A (Brazil)" },
    { slug: "arg.1", name: "Liga Profesional (Argentina)" },
    { slug: "chi.1", name: "Primera División (Chile)" },
    { slug: "col.1", name: "Primera A (Colombia)" },
    { slug: "per.1", name: "Liga 1 (Peru)" },
    { slug: "uru.1", name: "Primera División (Uruguay)" },
    { slug: "usa.open", name: "US Open Cup (Mỹ)" },
  ] },
  { region: "Đội tuyển", leagues: [
    { slug: "fifa.world", name: "FIFA World Cup" },
    { slug: "uefa.euro", name: "UEFA Euro" },
    { slug: "conmebol.america", name: "Copa América" },
  ] },
];
const LIVE_LEAGUES = LIVE_LEAGUE_GROUPS.flatMap((g) => g.leagues.map((l) => ({ ...l, region: g.region })));
const LIVE_LEAGUE_ORDER = new Map(LIVE_LEAGUES.map((l, i) => [l.slug, i]));
/* λ trung bình dài hạn XẤP XỈ của từng giải (bàn thắng trung bình của một đội chủ nhà / đội khách trong một trận,
   tra từ thống kê nhiều mùa). CHỈ dùng khi không khớp được dự đoán trước trận của Tymex cho trận đó;
   giao diện luôn ghi rõ "ước tính theo trung bình giải" trong trường hợp này. Giải không có trong bảng dùng mặc định. */
const LEAGUE_AVG_LAMBDAS = {
  "uefa.champions": { home: 1.56, away: 1.20 }, "uefa.europa": { home: 1.48, away: 1.14 }, "uefa.europa.conf": { home: 1.50, away: 1.12 },
  "eng.1": { home: 1.55, away: 1.24 }, "esp.1": { home: 1.44, away: 1.08 }, "ita.1": { home: 1.42, away: 1.12 },
  "ger.1": { home: 1.66, away: 1.30 }, "fra.1": { home: 1.48, away: 1.13 }, "por.1": { home: 1.50, away: 1.10 },
  "ned.1": { home: 1.66, away: 1.28 }, "tur.1": { home: 1.50, away: 1.14 }, "sco.1": { home: 1.52, away: 1.16 },
  "bel.1": { home: 1.52, away: 1.18 },
  "afc.champions": { home: 1.52, away: 1.12 }, "afc.cup": { home: 1.48, away: 1.10 }, "jpn.1": { home: 1.42, away: 1.14 },
  "ksa.1": { home: 1.58, away: 1.22 }, "chn.1": { home: 1.50, away: 1.16 }, "tha.1": { home: 1.52, away: 1.14 },
  "idn.1": { home: 1.44, away: 1.06 }, "mys.1": { home: 1.50, away: 1.12 }, "ind.1": { home: 1.38, away: 1.04 },
  "aus.1": { home: 1.56, away: 1.26 },
  "conmebol.libertadores": { home: 1.46, away: 0.98 }, "conmebol.sudamericana": { home: 1.44, away: 1.00 },
  "concacaf.champions": { home: 1.54, away: 1.08 }, "usa.1": { home: 1.58, away: 1.18 }, "mex.1": { home: 1.46, away: 1.10 },
  "bra.1": { home: 1.38, away: 0.96 }, "arg.1": { home: 1.30, away: 0.92 }, "chi.1": { home: 1.48, away: 1.12 },
  "col.1": { home: 1.34, away: 0.94 }, "per.1": { home: 1.44, away: 0.94 }, "uru.1": { home: 1.40, away: 1.02 },
  "fifa.world": { home: 1.44, away: 1.08 }, "uefa.euro": { home: 1.38, away: 1.04 }, "conmebol.america": { home: 1.40, away: 1.02 },
};
const DEFAULT_AVG_LAMBDAS = { home: 1.45, away: 1.15 };

/* ---------------------------------------------------------------- toán của mô hình (port từ live.py) */
function poissonPmf(k, lam) {
  if (lam <= 0) return k === 0 ? 1 : 0;
  let logFact = 0;
  for (let i = 2; i <= k; i++) logFact += Math.log(i);
  return Math.exp(-lam + k * Math.log(lam) - logFact);
}
function dcTau(i, j, lh, la, rho) {
  if (i === 0 && j === 0) return 1 - lh * la * rho;
  if (i === 1 && j === 0) return 1 + la * rho;
  if (i === 0 && j === 1) return 1 + lh * rho;
  if (i === 1 && j === 1) return 1 - rho;
  return 1;
}
function liveScoreMatrix(lh, la, rho = LIVE_RHO, maxGoals = 10) {
  const m = [];
  for (let i = 0; i <= maxGoals; i++) {
    m.push([]);
    for (let j = 0; j <= maxGoals; j++) m[i].push(poissonPmf(i, lh) * poissonPmf(j, la));
  }
  if (rho) for (const i of [0, 1]) for (const j of [0, 1]) m[i][j] *= Math.max(dcTau(i, j, lh, la, rho), 0);
  let total = 0;
  m.forEach((r) => r.forEach((v) => { total += v; }));
  return m.map((r) => r.map((v) => v / total));
}
function roundTo100(probs) {
  const unit = 10, totalUnits = 100 * unit;
  const raw = probs.map((p) => p * totalUnits);
  const floors = raw.map((x) => Math.floor(x));
  let remaining = totalUnits - floors.reduce((a, b) => a + b, 0);
  const order = raw.map((x, i) => [x - floors[i], i]).sort((a, b) => b[0] - a[0]);
  for (const [, i] of order) { if (remaining <= 0) break; floors[i] += 1; remaining -= 1; }
  return floors.map((f) => f / unit);
}
function stateFactor(goalDiffForTeam) {
  const d = Math.max(-2, Math.min(2, goalDiffForTeam));
  if (d < 0) return Math.pow(1.12, -d);
  if (d > 0) return Math.pow(0.90, d);
  return 1;
}
function remainingLambdas(lh, la, minute, hs, as, rcH = 0, rcA = 0) {
  const remaining = Math.max(LIVE_FULL_MINUTES - Math.max(minute, 0), 0) / LIVE_FULL_MINUTES;
  const diff = hs - as;
  return [
    lh * remaining * stateFactor(diff) * Math.pow(0.72, rcH) * Math.pow(1.10, rcA),
    la * remaining * stateFactor(-diff) * Math.pow(0.72, rcA) * Math.pow(1.10, rcH),
  ];
}
function predictLive(lh, la, minute, hs, as, rcH = 0, rcA = 0) {
  minute = Math.max(0, minute);
  const [rh, ra] = remainingLambdas(lh, la, minute, hs, as, rcH, rcA);
  const matrix = liveScoreMatrix(rh, ra);
  const final = new Map();
  matrix.forEach((row, i) => row.forEach((v, j) => {
    if (!v) return;
    const key = `${hs + i}-${as + j}`;
    final.set(key, (final.get(key) || 0) + v);
  }));
  let pH = 0, pD = 0, pA = 0;
  final.forEach((v, key) => {
    const [i, j] = key.split("-").map(Number);
    if (i > j) pH += v; else if (i === j) pD += v; else pA += v;
  });
  const s = pH + pD + pA;
  pH /= s; pD /= s; pA /= s;
  const pc = roundTo100([pH, pD, pA]);
  const top = [...final.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
    .map(([key, v]) => { const [h, a] = key.split("-").map(Number); return { home: h, away: a, prob: v }; });
  const totalRem = rh + ra;
  let nextGoal;
  if (totalRem <= 0) nextGoal = { home: 0, away: 0, none: 1 };
  else {
    const pNone = Math.exp(-totalRem), pAny = 1 - pNone;
    nextGoal = { home: pAny * rh / totalRem, away: pAny * ra / totalRem, none: pNone };
  }
  return {
    p_home: pH, p_draw: pD, p_away: pA,
    percent: { home: pc[0], draw: pc[1], away: pc[2] },
    top_final_scores: top,
    predicted_final_score: top[0],
    expected_final: { home: hs + rh, away: as + ra },
    next_goal: nextGoal,
    lambda_home_remaining: rh, lambda_away_remaining: ra,
  };
}
/** Chuỗi xác suất thắng của chủ nhà từ phút 0 tới phút hiện tại, dùng các thời điểm ghi bàn đã biết.
    Đây là đầu ra của mô hình trực tiếp (không phải dữ liệu thế trận/sút bóng thật). */
function probTimeline(lh, la, goals, currentMinute, rcH = 0, rcA = 0) {
  const cur = Math.max(0, Math.min(Math.round(currentMinute), LIVE_FULL_MINUTES));
  const step = Math.max(1, Math.round(cur / 18) || 1);
  const pts = [];
  const at = (t) => ({
    minute: t,
    p_home: predictLive(lh, la, t,
      goals.filter((g) => g.side === "home" && g.minute <= t).length,
      goals.filter((g) => g.side === "away" && g.minute <= t).length, rcH, rcA).p_home,
  });
  for (let t = 0; t <= cur; t += step) pts.push(at(t));
  if (!pts.length || pts[pts.length - 1].minute !== cur) pts.push(at(cur));
  return pts;
}

/* ---------------------------------------------------------------- mô phỏng trận (port của simulate_match) */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function poissonDraw(rng, lam) {
  if (lam <= 0) return 0;
  const limit = Math.exp(-lam);
  let k = 0, p = 1;
  do { p *= rng(); if (p <= limit) return k; k += 1; } while (k < 12);
  return k;
}
/** Tạo một phiên MÔ PHỎNG. opts: {seed, minute, homeScore, awayScore, homeRed, awayRed}.
    Mỗi step() đá thêm 1 phút: số cơ hội tấn công ~ Poisson(λ_phút × 3), mỗi cơ hội thành bàn với xác suất 1/3
    (giữ đúng kỳ vọng bàn thắng của mô hình); cơ hội không thành bàn được ghi là "cơ hội" trong dòng sự kiện mô phỏng. */
function createSimulation(lh, la, opts = {}) {
  const rng = mulberry32(opts.seed ?? Math.floor(Math.random() * 1e9));
  const st = {
    minute: opts.minute || 0, home: opts.homeScore || 0, away: opts.awayScore || 0,
    rcH: opts.homeRed || 0, rcA: opts.awayRed || 0, events: [], done: false, probs: null, history: [],
  };
  st.probs = predictLive(lh, la, st.minute, st.home, st.away, st.rcH, st.rcA);
  st.history.push({ minute: st.minute, p_home: st.probs.p_home });
  function step() {
    if (st.minute >= LIVE_FULL_MINUTES) { st.done = true; return []; }
    const [rh, ra] = remainingLambdas(lh, la, st.minute, st.home, st.away, st.rcH, st.rcA);
    const left = LIVE_FULL_MINUTES - st.minute;
    const evs = [];
    for (const [side, perMin] of [["home", rh / left], ["away", ra / left]]) {
      const chances = poissonDraw(rng, perMin * 3);
      for (let i = 0; i < chances; i++) {
        if (rng() < 1 / 3) {
          if (side === "home") st.home += 1; else st.away += 1;
          evs.push({ minute: st.minute + 1, type: "goal", side, home: st.home, away: st.away });
        } else {
          evs.push({ minute: st.minute + 1, type: "chance", side });
        }
      }
    }
    st.minute += 1;
    st.events.push(...evs);
    st.probs = predictLive(lh, la, st.minute, st.home, st.away, st.rcH, st.rcA);
    st.history.push({ minute: st.minute, p_home: st.probs.p_home });
    if (st.minute >= LIVE_FULL_MINUTES) st.done = true;
    return evs;
  }
  return { state: st, step };
}

/* ---------------------------------------------------------------- lấy dữ liệu trực tiếp */
async function fetchJson(url, timeoutMs = 12000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } finally { clearTimeout(timer); }
}
/** "45'+2'" -> 47, "67'" -> 67, "23" -> 23; không đọc được thì dùng giây của ESPN nếu có. */
function clockMinute(display, valueSec) {
  if (display) {
    const parts = String(display).replace(/'/g, "").split("+").map((x) => parseInt(x, 10)).filter((n) => !Number.isNaN(n));
    if (parts.length) return parts.reduce((a, b) => a + b, 0);
  }
  return valueSec ? Math.floor(valueSec / 60) : null;
}
function espnEventToLive(ev, league) {
  const comp = ev.competitions && ev.competitions[0];
  if (!comp || !comp.competitors) return null;
  const home = comp.competitors.find((x) => x.homeAway === "home");
  const away = comp.competitors.find((x) => x.homeAway === "away");
  if (!home || !away) return null;
  const st = ev.status || comp.status || {};
  const state = (st.type && st.type.state) || "pre";
  const goals = [], reds = { home: 0, away: 0 };
  (comp.details || []).forEach((d) => {
    const side = String(d.team && d.team.id) === String(home.team.id) ? "home"
      : String(d.team && d.team.id) === String(away.team.id) ? "away" : null;
    if (!side) return;
    const typeText = (d.type && d.type.text) || "";
    if (d.scoringPlay) goals.push({ minute: clockMinute(d.clock && d.clock.displayValue, d.clock && d.clock.value) ?? 0, side, scorer: (d.athletesInvolved && d.athletesInvolved[0] && d.athletesInvolved[0].displayName) || "", type: typeText });
    if (/red card/i.test(typeText)) reds[side] += 1;
  });
  const score = (c) => (c.score === null || c.score === undefined || c.score === "" ? null : Number(c.score));
  return {
    source: "ESPN", eventId: String(ev.id), slug: league.slug, league: league.name,
    startIso: ev.date || null, state,
    statusLabel: (st.type && (st.type.shortDetail || st.type.description)) || "",
    clockLabel: st.displayClock || "", minute: state === "in" ? clockMinute(st.displayClock, st.clock && st.clock.value) : null,
    halftime: (st.type && st.type.name) === "STATUS_HALFTIME",
    home: home.team.displayName, away: away.team.displayName,
    homeLogo: home.team.logo || "", awayLogo: away.team.logo || "",
    homeScore: score(home), awayScore: score(away), goals, reds,
  };
}
const espnSlugCache = new Map();   // slug -> {t, events}
const ESPN_REST_TTL = 4 * 60 * 1000;   // giải không ưu tiên: làm mới tối đa 4 phút/lần
async function fetchEspnEvents(forceAll = false) {
  const now = Date.now();
  const due = LIVE_LEAGUES.filter((lg) => {
    if (lg.featured || forceAll) return true;
    const hit = espnSlugCache.get(lg.slug);
    return !hit || now - hit.t > ESPN_REST_TTL;
  });
  const res = await Promise.allSettled(due.map(async (lg) => {
    const j = await fetchJson(`https://site.api.espn.com/apis/site/v2/sports/soccer/${lg.slug}/scoreboard`);
    const events = (j.events || []).map((ev) => espnEventToLive(ev, lg)).filter(Boolean);
    espnSlugCache.set(lg.slug, { t: Date.now(), events });
    return events;
  }));
  const fresh = due.filter((_, i) => res[i].status === "fulfilled");
  if (LIVE_LEAGUES.every((lg) => !espnSlugCache.has(lg.slug))) {
    throw new Error("ESPN không phản hồi ở mọi giải.");
  }
  // Gộp bản mới nhất của từng giải (bản cache của giải chưa tới lượt làm mới vẫn được dùng).
  return { events: LIVE_LEAGUES.flatMap((lg) => (espnSlugCache.get(lg.slug) || { events: [] }).events), fetched: fresh.length };
}
function sportsDbEventToLive(e) {
  const status = String(e.strStatus || "");
  const finished = /FT|AET|PEN/i.test(status);
  const started = e.intHomeScore !== null && e.intHomeScore !== undefined && e.intHomeScore !== "";
  const slug = { "Premier League": "eng.1", "La Liga": "esp.1", "Serie A": "ita.1", "Bundesliga": "ger.1", "Ligue 1": "fra.1", "UEFA Champions League": "uefa.champions" }[e.strLeague] || null;
  return {
    source: "TheSportsDB", eventId: String(e.idEvent), slug, league: e.strLeague,
    startIso: e.strTimestamp || null, state: finished ? "post" : started ? "in" : "pre",
    statusLabel: status, clockLabel: e.strProgress ? `${e.strProgress}'` : "",
    minute: started && !finished ? (parseInt(e.strProgress, 10) || null) : null, halftime: /HT/i.test(status),
    home: e.strHomeTeam, away: e.strAwayTeam, homeLogo: e.strHomeTeamBadge || "", awayLogo: e.strAwayTeamBadge || "",
    homeScore: started ? Number(e.intHomeScore) : null, awayScore: started ? Number(e.intAwayScore) : null,
    goals: [], reds: { home: 0, away: 0 },
  };
}
async function fetchSportsDbEvents() {
  const j = await fetchJson("https://www.thesportsdb.com/api/v1/json/123/livescore.php?s=Soccer");
  const rows = j.livescore || j.events || [];
  return rows.map(sportsDbEventToLive);
}
const normTeam = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
const pairKey = (e) => `${normTeam(e.home)}|${normTeam(e.away)}`;
/** Lấy toàn bộ trận cho trang Trực tiếp:
    - ESPN theo 2 tầng (ưu tiên mỗi lần gọi; giải còn lại theo cache 4 phút, hoặc tất cả khi forceAll).
    - Quét toàn cầu TheSportsDB (một lời gọi duy nhất, trả MỌI trận đang đá trên thế giới): bổ sung các giải
      ESPN không có (K League 1, V.League 1...) và làm dự phòng khi ESPN sập. Khử trùng theo cặp tên đội:
      trận nào ESPN đã có thì bản TheSportsDB (ít chi tiết hơn) bị loại.
    Trả về {events, espnOk, tsdbOk}: từng trận tự mang nhãn nguồn trong trường `source`. */
async function fetchLiveEvents(forceAll = false) {
  let espnEvents = [], espnOk = false, tsdbEvents = [], tsdbOk = false;
  try { espnEvents = (await fetchEspnEvents(forceAll)).events; espnOk = true; } catch (e) { /* dùng TheSportsDB thay */ }
  try { tsdbEvents = await fetchSportsDbEvents(); tsdbOk = true; } catch (e) { /* không có quét bổ sung */ }
  if (!espnOk && !tsdbOk) throw new Error("Cả ESPN lẫn TheSportsDB đều không phản hồi.");
  const seen = new Set(espnEvents.map(pairKey));
  const extra = tsdbEvents.filter((e) => !seen.has(pairKey(e)));
  const stateOrder = { in: 0, pre: 1, post: 2 };
  const events = [...espnEvents, ...extra].sort((a, b) =>
    (stateOrder[a.state] ?? 3) - (stateOrder[b.state] ?? 3)
    || (LIVE_LEAGUE_ORDER.get(a.slug) ?? 999) - (LIVE_LEAGUE_ORDER.get(b.slug) ?? 999)
    || String(a.startIso || "").localeCompare(String(b.startIso || "")));
  return { events, espnOk, tsdbOk };
}

/* ---------------------------------------------------------------- thống kê chi tiết 1 trận (ESPN summary) */
/* Tên trường đã kiểm chứng trên dữ liệu thật của ESPN (boxscore.teams[].statistics: name -> displayValue).
   Chỉ vẽ những thống kê nguồn thật sự trả về cho trận đó; thiếu trường nào thì bỏ hàng đó. */
const STAT_DEFS = [
  ["possessionPct", "Kiểm soát bóng (%)"],
  ["totalShots", "Tổng số cú sút"],
  ["shotsOnTarget", "Sút trúng đích"],
  ["blockedShots", "Cú sút bị chặn"],
  ["wonCorners", "Phạt góc"],
  ["offsides", "Việt vị"],
  ["foulsCommitted", "Phạm lỗi"],
  ["saves", "Thủ môn cứu thua"],
  ["yellowCards", "Thẻ vàng"],
  ["redCards", "Thẻ đỏ"],
  ["totalPasses", "Số đường chuyền"],
  ["accuratePasses", "Chuyền chính xác"],
  ["passPct", "Tỷ lệ chuyền đúng (%)"],
  ["totalTackles", "Tắc bóng"],
  ["effectiveTackles", "Tắc bóng thành công"],
  ["interceptions", "Đánh chặn"],
  ["totalClearance", "Phá bóng"],
  ["totalCrosses", "Tạt bóng"],
  ["accurateCrosses", "Tạt bóng chính xác"],
  ["totalLongBalls", "Bóng dài"],
  ["penaltyKickShots", "Số lần sút phạt đền"],
  ["penaltyKickGoals", "Bàn thắng phạt đền"],
];
const summaryCache = new Map();
function parseEspnSummary(j) {
  const teams = (j.boxscore && j.boxscore.teams) || [];
  const stats = { home: {}, away: {} };
  const names = { home: "", away: "" };
  teams.forEach((t) => {
    const side = t.homeAway === "away" ? "away" : "home";
    names[side] = (t.team && t.team.displayName) || "";
    (t.statistics || []).forEach((s) => { stats[side][s.name] = s.displayValue; });
  });
  const idToSide = {};
  teams.forEach((t) => { if (t.team && t.team.id) idToSide[String(t.team.id)] = t.homeAway === "away" ? "away" : "home"; });
  const keyEvents = (j.keyEvents || []).map((e) => ({
    minute: clockMinute(e.clock && e.clock.displayValue, e.clock && e.clock.value) ?? 0,
    clockLabel: (e.clock && e.clock.displayValue) || "",
    type: (e.type && (e.type.text || e.type.type)) || "",
    text: e.text || "",
    side: idToSide[String(e.team && e.team.id)] || null,
    scoringPlay: !!e.scoringPlay,
  })).sort((a, b) => a.minute - b.minute);
  return { stats, names, keyEvents };
}
async function fetchEspnSummary(slug, eventId) {
  const key = `${slug}:${eventId}`;
  const hit = summaryCache.get(key);
  if (hit && Date.now() - hit.t < 30000) return hit.v;
  const j = await fetchJson(`https://site.api.espn.com/apis/site/v2/sports/soccer/${slug}/summary?event=${eventId}`);
  const v = parseEspnSummary(j);
  summaryCache.set(key, { t: Date.now(), v });
  return v;
}
/** xG ƯỚC TÍNH của Tymex từ cú sút (KHÔNG phải xG chính thức): sút trúng đích × 0,32 + sút còn lại × 0,03.
    Trả về null nếu nguồn không có đủ số cú sút. */
function xgProxyFromShots(statsSide) {
  const total = parseFloat(statsSide.totalShots), on = parseFloat(statsSide.shotsOnTarget);
  if (Number.isNaN(total) || Number.isNaN(on)) return null;
  return on * 0.32 + Math.max(total - on, 0) * 0.03;
}

window.TymexLive = {
  predictLive, probTimeline, createSimulation, fetchLiveEvents, fetchEspnSummary,
  xgProxyFromShots, STAT_DEFS, LEAGUE_AVG_LAMBDAS, DEFAULT_AVG_LAMBDAS, FULL_MINUTES: LIVE_FULL_MINUTES,
  LEAGUE_GROUPS: LIVE_LEAGUE_GROUPS, LEAGUES: LIVE_LEAGUES, normTeam,
};
