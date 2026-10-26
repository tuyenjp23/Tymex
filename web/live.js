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
  const finalDist = [...final.entries()].sort((a, b) => b[1] - a[1])
    .map(([key, v]) => { const [h, a] = key.split("-").map(Number); return { home: h, away: a, prob: v }; });
  return {
    p_home: pH, p_draw: pD, p_away: pA,
    percent: { home: pc[0], draw: pc[1], away: pc[2] },
    top_final_scores: top,
    predicted_final_score: top[0],
    expected_final: { home: hs + rh, away: as + ra },
    next_goal: nextGoal,
    lambda_home_remaining: rh, lambda_away_remaining: ra,
    final_dist: finalDist,
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

/* ---------------------------------------------------------------- thị trường + nhận định (port của app/prediction/markets.py)
   GIỮ ĐÚNG các ngưỡng dùng chung với bản Python: "Mạnh" >= 0,65; "Khá" >= 0,57; sàn tuyệt đối 0,50;
   tỷ số dự đoán luôn là thông tin tham khảo riêng, không trà trộn vào picks. */
const GOAL_LINES = [0.5, 1.5, 2.5, 3.5, 4.5];
const PICK_STRONG = 0.65, PICK_OK = 0.57, PICK_FLOOR = 0.50;
const VERDICT_DISCLAIMER = "Nhận định tham khảo từ mô hình thống kê — không phải lời khuyên cá cược.";
const fmtLine = (x) => x.toFixed(1).replace(".", ",");
function pickStrength(p) { return p >= PICK_STRONG ? "Mạnh" : p >= PICK_OK ? "Khá" : null; }
function linesFromTotalDist(dist) {
  return GOAL_LINES.map((line) => {
    let over = 0;
    dist.forEach((v, t) => { if (t > line) over += v; });
    return { line, over, under: 1 - over };
  });
}
function goalLines(lh, la, rho = LIVE_RHO) {
  const m = liveScoreMatrix(lh, la, rho);
  const dist = new Map();
  let btts = 0, expTotal = 0, pH = 0, pD = 0, pA = 0;
  m.forEach((row, i) => row.forEach((v, j) => {
    dist.set(i + j, (dist.get(i + j) || 0) + v);
    expTotal += (i + j) * v;
    if (i >= 1 && j >= 1) btts += v;
    if (i > j) pH += v; else if (i === j) pD += v; else pA += v;
  }));
  return {
    lines: linesFromTotalDist(dist), expected_total_goals: expTotal,
    btts: { yes: btts, no: 1 - btts },
    double_chance: { "1X": pH + pD, "12": pH + pA, "X2": pD + pA },
  };
}
/** Nhận định có cấu trúc — cùng logic với build_verdict ở markets.py.
    opts.live = {minute, homeScore, awayScore, homeRed, awayRed} khi trận đang đá: 1X2 và tỷ số lấy từ
    dự đoán trực tiếp, Tài/Xỉu tính trên phân phối TỔNG BÀN CHUNG CUỘC (đã gồm tỷ số hiện tại). */
function buildVerdict(lh, la, opts = {}) {
  const homeName = opts.homeName || "Chủ nhà", awayName = opts.awayName || "Đội khách";
  const live = opts.live || null;
  let percent, score, probs, mk;
  if (live) {
    const lp = predictLive(lh, la, live.minute, live.homeScore, live.awayScore, live.homeRed || 0, live.awayRed || 0);
    percent = lp.percent; score = lp.predicted_final_score;
    probs = { home: lp.p_home, draw: lp.p_draw, away: lp.p_away };
    const dist = new Map();
    let bttsYes = 0;
    lp.final_dist.forEach(({ home, away, prob }) => {
      dist.set(home + away, (dist.get(home + away) || 0) + prob);
      if (home >= 1 && away >= 1) bttsYes += prob;
    });
    mk = { lines: linesFromTotalDist(dist), expected_total_goals: lp.expected_final.home + lp.expected_final.away,
           btts: { yes: bttsYes, no: 1 - bttsYes } };
  } else {
    const lp = predictLive(lh, la, 0, 0, 0);
    percent = lp.percent; score = lp.predicted_final_score;
    probs = { home: lp.p_home, draw: lp.p_draw, away: lp.p_away };
    mk = goalLines(lh, la);
  }
  const candidates = [];
  const outs = [["home", probs.home, `${homeName} thắng`], ["draw", probs.draw, "Hòa"], ["away", probs.away, `${awayName} thắng`]]
    .sort((a, b) => b[1] - a[1]);
  candidates.push({ market: "1x2", selection: outs[0][2], probability: outs[0][1] });
  let ouBest = null;
  mk.lines.forEach((ln) => {
    [["Tài", ln.over], ["Xỉu", ln.under]].forEach(([side, prob]) => {
      if (!ouBest || prob > ouBest.probability) ouBest = { market: "goals_ou", selection: `${side} ${fmtLine(ln.line)} bàn`, probability: prob, line: ln.line, side };
    });
  });
  if (ouBest) candidates.push(ouBest);
  const b = mk.btts;
  candidates.push({ market: "btts", selection: b.yes >= b.no ? "Cả hai đội cùng ghi bàn" : "Ít nhất một đội không ghi bàn", probability: Math.max(b.yes, b.no) });
  candidates.sort((a, b) => b.probability - a.probability);
  let picks = candidates.filter((c) => pickStrength(c.probability)).map((c) => ({ ...c, strength: pickStrength(c.probability) }));
  let fallback = false;
  if (!picks.length && candidates.length && candidates[0].probability >= PICK_FLOOR) {
    picks = [{ ...candidates[0], strength: "Cân nhắc" }];
    fallback = true;
  }
  return { picks: picks.slice(0, 4), score: { home: score.home, away: score.away, prob: score.prob },
           percent, markets: mk, ou_pick: ouBest && picks.some((p) => p.market === "goals_ou") ? ouBest : null,
           fallback, disclaimer: VERDICT_DISCLAIMER, live: !!live };
}

/* ---------------------------------------------------------------- phạt góc (port của app/prediction/corners.py)
   GIỮ ĐÚNG hằng số và công thức với bản Python: CORNER_SHRINK_K = 3, mẫu tối thiểu 8 trận của giải /
   3 trận đúng sân của mỗi đội, ngưỡng pick dùng chung PICK_STRONG/PICK_OK/PICK_FLOOR ở trên. */
const CORNER_LINES = [7.5, 8.5, 9.5, 10.5, 11.5, 12.5];
const CORNER_SHRINK_K = 3.0, CORNER_MIN_TOTAL = 8, CORNER_MIN_TEAM = 3;
const shrinkRate = (rate, games, prior, k = CORNER_SHRINK_K) => (rate * games + k * prior) / (games + k);
function cornerExpectations(hf, hag, af, aag, lah, laa, hGames = 0, aGames = 0) {
  const hfS = shrinkRate(hf, hGames, lah), hagS = shrinkRate(hag, hGames, laa);
  const afS = shrinkRate(af, aGames, laa), aagS = shrinkRate(aag, aGames, lah);
  const clamp = (v) => Math.min(Math.max(v, 0.5), 14);
  const home = clamp(lah * (hfS / lah) * (aagS / lah));
  const away = clamp(laa * (afS / laa) * (hagS / laa));
  return { home, away, total: home + away };
}
function cornerLines(totalLam) {
  return CORNER_LINES.map((line) => {
    let over = 0;
    for (let k = Math.floor(line) + 1; k <= 40; k++) over += poissonPmf(k, totalLam);
    return { line, over, under: 1 - over };
  });
}
function cornerPick(lines) {
  let best = null;
  lines.forEach((ln) => {
    [["Tài", ln.over], ["Xỉu", ln.under]].forEach(([side, prob]) => {
      if (!best || prob > best.probability) best = { market: "corners_ou", selection: `${side} góc ${fmtLine(ln.line)}`, probability: prob, line: ln.line, side };
    });
  });
  if (!best) return null;
  const s = pickStrength(best.probability);
  if (s) return { ...best, strength: s };
  return best.probability >= PICK_FLOOR ? { ...best, strength: "Cân nhắc" } : null;
}
const cornerTeamKey = (name) => normTeam(name).replace(/\b(fc|cf|sc|afc|club|bk)\b/g, "").replace(/\s+/g, " ").trim();
const cornerNameMatch = (a, b) => a && b && (a === b || (a.length >= 4 && b.includes(a)) || (b.length >= 4 && a.includes(b)));
/** rows: [{home, away, homeCorners, awayCorners}] tên đội theo ESPN. Giống estimate_from_matches bản Python. */
function estimateCorners(rows, homeName, awayName) {
  const valid = (rows || []).filter((r) => r.homeCorners !== null && r.homeCorners !== undefined && r.awayCorners !== null && r.awayCorners !== undefined);
  const n = valid.length;
  const out = { matches: n };
  if (n) {
    out.leagueAvg = { home: valid.reduce((s, r) => s + r.homeCorners, 0) / n, away: valid.reduce((s, r) => s + r.awayCorners, 0) / n };
  }
  if (n < CORNER_MIN_TOTAL) return { ...out, available: false };
  const hk = cornerTeamKey(homeName), ak = cornerTeamKey(awayName);
  const homeRows = valid.filter((r) => cornerNameMatch(cornerTeamKey(r.home), hk));
  const awayRows = valid.filter((r) => cornerNameMatch(cornerTeamKey(r.away), ak));
  out.homeGames = homeRows.length; out.awayGames = awayRows.length;
  if (homeRows.length < CORNER_MIN_TEAM || awayRows.length < CORNER_MIN_TEAM) return { ...out, available: false };
  const mean = (arr, f) => arr.reduce((s, r) => s + f(r), 0) / arr.length;
  const exp = cornerExpectations(
    mean(homeRows, (r) => r.homeCorners), mean(homeRows, (r) => r.awayCorners),
    mean(awayRows, (r) => r.awayCorners), mean(awayRows, (r) => r.homeCorners),
    out.leagueAvg.home, out.leagueAvg.away, homeRows.length, awayRows.length);
  const lines = cornerLines(exp.total);
  return { ...out, available: true, expected: exp, lines, pick: cornerPick(lines) };
}
/* Lấy tỷ lệ góc của một giải từ ESPN: lặp tối đa 14 ngày scoreboard (từng ngày đơn lẻ — dạng khoảng
   ngày bị ESPN trả 400), gom tối đa ~20 trận đã kết thúc rồi đọc summary của từng trận lấy wonCorners.
   Cache: bộ nhớ + localStorage 6 giờ. Chỉ chạy khi người dùng mở khối nhận định (lười). */
const CORNER_MAX_MATCHES = 20, CORNER_DAYS = 14, CORNER_LS_TTL = 6 * 3600 * 1000;
const cornerRowsDone = new Map(), cornerRowsPromise = new Map();
function cornerRowsCached(slug) { return cornerRowsDone.get(slug) || null; }
function fetchLeagueCornerRows(slug) {
  if (cornerRowsDone.has(slug)) return Promise.resolve(cornerRowsDone.get(slug));
  if (cornerRowsPromise.has(slug)) return cornerRowsPromise.get(slug);
  try {
    const raw = localStorage.getItem("tymex-corners-" + slug);
    if (raw) {
      const o = JSON.parse(raw);
      if (o && Date.now() - o.t < CORNER_LS_TTL && Array.isArray(o.rows)) {
        cornerRowsDone.set(slug, o.rows);
        return Promise.resolve(o.rows);
      }
    }
  } catch (e) { /* localStorage không khả dụng: bỏ qua */ }
  const p = (async () => {
    const found = [];
    const seen = new Set();
    for (let back = 0; back <= CORNER_DAYS && found.length < CORNER_MAX_MATCHES; back++) {
      const d = new Date(Date.now() - back * 86400000);
      const ds = `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, "0")}${String(d.getUTCDate()).padStart(2, "0")}`;
      let j;
      try { j = await fetchJson(`https://site.api.espn.com/apis/site/v2/sports/soccer/${slug}/scoreboard?dates=${ds}`); }
      catch (e) { continue; }
      (j.events || []).forEach((ev) => {
        const comp = ev.competitions && ev.competitions[0];
        if (!comp || !comp.competitors) return;
        const st = (ev.status && ev.status.type) || (comp.status && comp.status.type) || {};
        if (st.state !== "post" || seen.has(String(ev.id))) return;
        const home = comp.competitors.find((x) => x.homeAway === "home");
        const away = comp.competitors.find((x) => x.homeAway === "away");
        if (!home || !away) return;
        seen.add(String(ev.id));
        found.push({ id: String(ev.id), home: home.team.displayName, away: away.team.displayName });
      });
    }
    const targets = found.slice(0, CORNER_MAX_MATCHES);
    const rows = [];
    for (let i = 0; i < targets.length; i += 5) {
      const batch = await Promise.allSettled(targets.slice(i, i + 5).map(async (t) => {
        const sum = await fetchEspnSummary(slug, t.id);
        const hc = parseFloat(sum.stats.home.wonCorners), ac = parseFloat(sum.stats.away.wonCorners);
        if (Number.isNaN(hc) || Number.isNaN(ac)) return null;
        return { home: t.home, away: t.away, homeCorners: hc, awayCorners: ac };
      }));
      batch.forEach((r) => { if (r.status === "fulfilled" && r.value) rows.push(r.value); });
    }
    cornerRowsDone.set(slug, rows);
    try { localStorage.setItem("tymex-corners-" + slug, JSON.stringify({ t: Date.now(), rows })); } catch (e) { /* bỏ qua */ }
    return rows;
  })();
  cornerRowsPromise.set(slug, p);
  return p;
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
  const finished = /FT|AET|PEN|Match Finished|Finished/i.test(status);
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
/* ---- Khử trùng cặp đấu v2 (dùng cho MỌI lần gộp ESPN + TheSportsDB) ----
   Tên đội được bỏ dấu, bỏ các hậu/tiền tố tổ chức phổ biến rồi gộp khoảng trắng. Hai tên được coi là
   khớp MƠHỒ khi một tên là tiền tố/chuỗi con theo ranh giới từ của tên còn lại và phần ngắn có độ dài
   >= 6. Ở cấp cặp đấu chỉ cho phép MỘT phía khớp mơ hồ, phía còn lại phải khớp đúng — tránh gộp hai
   trận khác nhau chỉ vì cả hai tên đều bị rút ngắn. Bảng bí danh chỉ chứa ca đã gặp thật:
   ESPN "Central Córdoba" ↔ TheSportsDB "Central Córdoba de Santiago del Estero". */
const TEAM_NAME_AFFIXES_V2 = new Set(["fc", "cf", "sc", "afc", "club", "de", "ca", "cd", "ec", "ifk", "bk",
  "ac", "as", "us", "ss", "sv", "fk", "sk", "if", "ff", "ik"]);
const TEAM_NAME_ALIASES_V2 = new Map([
  ["central cordoba santiago del estero", "central cordoba"],
]);
function normalizeTeamNameV2(name) {
  const tokens = normTeam(name).split(" ").filter((t) => t && !TEAM_NAME_AFFIXES_V2.has(t));
  const normalized = tokens.join(" ").replace(/\s+/g, " ").trim();
  return TEAM_NAME_ALIASES_V2.get(normalized) || normalized;
}
const pairKey = (e) => `${normalizeTeamNameV2(e.home)}|${normalizeTeamNameV2(e.away)}`;
function teamNameMatchV2(a, b) {
  const x = normalizeTeamNameV2(a), y = normalizeTeamNameV2(b);
  if (!x || !y) return { exact: false, fuzzy: false };
  if (x === y) return { exact: true, fuzzy: false };
  const shorter = x.length <= y.length ? x : y;
  const longer = x.length <= y.length ? y : x;
  const fuzzy = shorter.length >= 6 && ` ${longer} `.includes(` ${shorter} `);
  return { exact: false, fuzzy };
}
function sameLiveFixture(a, b) {
  if (!a || !b) return false;
  const home = teamNameMatchV2(a.home, b.home);
  const away = teamNameMatchV2(a.away, b.away);
  const pairMatches = (home.exact && away.exact)
    || (home.exact && away.fuzzy)
    || (home.fuzzy && away.exact);
  if (!pairMatches) return false;
  const ta = Date.parse(a.startIso || ""), tb = Date.parse(b.startIso || "");
  if (Number.isFinite(ta) && Number.isFinite(tb)) return Math.abs(ta - tb) <= 3 * 3600 * 1000;
  // Thiếu/không đọc được giờ ở một phía: chỉ gộp khi chuỗi ngày YYYY-MM-DD ở đầu startIso trùng nhau.
  const da = String(a.startIso || "").slice(0, 10), db = String(b.startIso || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(da) && da === db;
}
function isEmptyLiveValue(v) {
  return v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length);
}
function mergeDuplicateLiveEvent(kept, extra) {
  // Bản đã giữ (thường là ESPN, giàu dữ liệu hơn) thắng; chỉ lấy từ bản trùng những trường nó thiếu.
  const out = { ...kept };
  Object.entries(extra || {}).forEach(([k, v]) => {
    if (isEmptyLiveValue(out[k]) && !isEmptyLiveValue(v)) out[k] = v;
  });
  // goals/reds là dữ kiện TSDB có thể có trong lúc bản ESPN tương ứng để trống/0 — chỉ bổ sung khi bản giữ trống.
  if ((!kept.goals || !kept.goals.length) && extra.goals && extra.goals.length) out.goals = extra.goals;
  const keptReds = kept.reds || {}, extraReds = extra.reds || {};
  if (!keptReds.home && !keptReds.away && (extraReds.home || extraReds.away)) out.reds = extraReds;
  return out;
}
function mergeLiveEvents(primaryEvents, extraEvents = []) {
  const kept = [];
  [...(primaryEvents || []), ...(extraEvents || [])].forEach((ev) => {
    const idx = kept.findIndex((existing) => sameLiveFixture(existing, ev));
    if (idx < 0) kept.push(ev);
    else kept[idx] = mergeDuplicateLiveEvent(kept[idx], ev);
  });
  return kept;
}
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
  const stateOrder = { in: 0, pre: 1, post: 2 };
  const events = mergeLiveEvents(espnEvents, tsdbEvents).sort((a, b) =>
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
/* ---- đội hình xuất phát (port của app/prediction/lineups.py — GIỮ ĐÚNG hằng số và quy tắc) ----
   Thiếu 1 trụ cột FWD/MID: λ của chính đội ×0,96. Thiếu 1 trụ cột DEF/GK: λ của đối thủ ×1,04.
   Tổng điều chỉnh mỗi λ bị chặn ở [0,85; 1,15]. "Trụ cột" = đá chính ở trận đã kết thúc gần nhất;
   "thiếu" = không có trong đội hình xuất phát mới và cũng không có trong danh sách dự bị mới
   (chưa biết dự bị thì chỉ đối chiếu đội hình xuất phát và ghi rõ). KHÔNG suy đoán lý do vắng mặt. */
const LINEUP_ATTACK_DROP = 0.04, LINEUP_DEFENCE_LEAK = 0.04;
const LINEUP_MIN_FACTOR = 0.85, LINEUP_MAX_FACTOR = 1.15;
const LINEUP_GROUP_LABEL = { GK: "thủ môn", DEF: "hậu vệ", MID: "tiền vệ", FWD: "tiền đạo" };
function espnPositionGroup(position) {
  const name = String((position && (position.name || position.displayName)) || "").toLowerCase();
  const abbrRaw = String((position && position.abbreviation) || "").toUpperCase();
  const abbr = abbrRaw.split("-")[0];
  if (name.includes("goalkeeper") || abbr === "G" || abbr === "GK") return "GK";
  if (name.includes("midfield")) return "MID";
  if (name.includes("defend") || name.includes("back")) return "DEF";
  if (name.includes("forward") || name.includes("striker") || name.includes("winger")) return "FWD";
  if (["CB", "LB", "RB", "LWB", "RWB", "DF"].includes(abbr)) return "DEF";
  if (["DM", "CM", "LM", "RM", "AM", "MF"].includes(abbr)) return "MID";
  if (["ST", "CF", "FW", "LW", "RW", "SS"].includes(abbr)) return "FWD";
  return null;
}
function normalizeLineupGroup(value) {
  const upper = String(value || "").trim().toUpperCase();
  if (["GK", "DEF", "MID", "FWD"].includes(upper)) return upper;
  return espnPositionGroup({ name: String(value || ""), abbreviation: upper });
}
function normLineupPlayer(p) {
  if (!p) return null;
  if (typeof p === "string") return p.trim() ? { name: p.trim(), id: null, positionGroup: null, key: normTeam(p) } : null;
  const name = p.name || p.player_name || p.displayName || (p.athlete && p.athlete.displayName) || "";
  if (!String(name).trim()) return null;
  const id = p.id || p.player_id || p.athlete_id || (p.athlete && p.athlete.id) || null;
  const group = normalizeLineupGroup(p.position_group || p.positionGroup || p.group)
    || espnPositionGroup(typeof p.position === "object" ? p.position : { name: p.position || p.role || "", abbreviation: "" })
    || null;
  return { name: String(name).trim(), id: id ? String(id) : null, positionGroup: group, key: id ? String(id) : normTeam(name) };
}
function lineupRosterParts(currentRoster) {
  if (!currentRoster) return { starters: [], subs: [], benchKnown: false };
  if (!Array.isArray(currentRoster)) {
    const starters = currentRoster.starters || currentRoster.starting_xi || currentRoster.startingXi
      || currentRoster.xi || currentRoster.lineup || currentRoster.players || [];
    const hasSubs = ["substitutes", "bench", "subs", "reserves"].some((k) => Array.isArray(currentRoster[k]));
    const subs = currentRoster.substitutes || currentRoster.bench || currentRoster.subs || currentRoster.reserves || [];
    return { starters, subs, benchKnown: hasSubs };
  }
  if (currentRoster.some((p) => p && typeof p === "object" && "starter" in p)) {
    return { starters: currentRoster.filter((p) => p.starter), subs: currentRoster.filter((p) => !p.starter), benchKnown: true };
  }
  return { starters: currentRoster, subs: [], benchKnown: false };
}
/** Port của missing_regulars() trong lineups.py. */
function missingRegulars(currentRoster, previousXi) {
  const parts = lineupRosterParts(currentRoster);
  const starters = parts.starters.map(normLineupPlayer).filter(Boolean);
  const subs = parts.subs.map(normLineupPlayer).filter(Boolean);
  const previous = (previousXi || []).map(normLineupPlayer).filter(Boolean);
  if (!starters.length) return { status: "chưa công bố", benchKnown: parts.benchKnown, missing: [],
    notes: ["Đội hình xuất phát chưa công bố — chưa thể đối chiếu trụ cột vắng mặt."] };
  if (!previous.length) return { status: "thiếu dữ kiện", benchKnown: parts.benchKnown, missing: [],
    notes: ["Chưa có đội hình xuất phát của trận gần nhất — không biết ai là trụ cột để đối chiếu."] };
  const present = new Set([...starters, ...subs].map((p) => p.key));
  const missing = previous.filter((p) => !present.has(p.key)).map((p) => ({ name: p.name, positionGroup: p.positionGroup }));
  const notes = [];
  if (!parts.benchKnown) notes.push("Nguồn chưa cho danh sách dự bị — chỉ đối chiếu với đội hình xuất phát, cầu thủ ngồi dự bị vẫn bị tính là vắng mặt.");
  if (missing.length) notes.push(`Thiếu ${missing.length} trụ cột so với trận gần nhất: ${missing.map((m) => `${m.name} (${LINEUP_GROUP_LABEL[m.positionGroup] || "chưa rõ vị trí"})`).join(", ")}.`);
  else notes.push("Không thiếu trụ cột nào so với đội hình xuất phát trận gần nhất.");
  return { status: "available", benchKnown: parts.benchKnown, missing, notes };
}
function missingListOf(value) {
  if (!value) return [];
  if (!Array.isArray(value)) {
    if (value.status && value.status !== "available") return [];
    value = value.missing || [];
  }
  return value.map(normLineupPlayer).filter(Boolean).map((p) => ({ name: p.name, positionGroup: p.positionGroup }));
}
/** Port của adjust_lambdas() trong lineups.py — cùng phép nhân, cùng thứ tự và cùng cách chặn ±15%. */
function adjustLambdas(lambdaHome, lambdaAway, homeMissing, awayMissing) {
  const homeMissingN = missingListOf(homeMissing), awayMissingN = missingListOf(awayMissing);
  const lamH = Math.max(0, Number(lambdaHome) || 0), lamA = Math.max(0, Number(lambdaAway) || 0);
  const explanations = [];
  let factorHome = 1, factorAway = 1;
  [["home", homeMissingN], ["away", awayMissingN]].forEach(([side, missing]) => {
    const teamLabel = side === "home" ? "Chủ nhà" : "Đội khách";
    const oppLabel = side === "home" ? "Đội khách" : "Chủ nhà";
    missing.forEach((p) => {
      const group = p.positionGroup, label = LINEUP_GROUP_LABEL[group] || "chưa rõ vị trí";
      if (group === "FWD" || group === "MID") {
        if (side === "home") factorHome *= 1 - LINEUP_ATTACK_DROP; else factorAway *= 1 - LINEUP_ATTACK_DROP;
        explanations.push(`${teamLabel} thiếu ${p.name} (${label}) so với trận gần nhất: λ của ${teamLabel.toLowerCase()} giảm 4% (tấn công yếu đi).`);
      } else if (group === "DEF" || group === "GK") {
        if (side === "home") factorAway *= 1 + LINEUP_DEFENCE_LEAK; else factorHome *= 1 + LINEUP_DEFENCE_LEAK;
        explanations.push(`${teamLabel} thiếu ${p.name} (${label}) so với trận gần nhất: λ của ${oppLabel.toLowerCase()} tăng 4% (hàng thủ ${teamLabel.toLowerCase()} dễ thủng hơn).`);
      } else {
        explanations.push(`${teamLabel} thiếu ${p.name} so với trận gần nhất nhưng chưa rõ nhóm vị trí — không điều chỉnh λ cho cầu thủ này.`);
      }
    });
  });
  const rawHome = factorHome, rawAway = factorAway;
  factorHome = Math.min(Math.max(factorHome, LINEUP_MIN_FACTOR), LINEUP_MAX_FACTOR);
  factorAway = Math.min(Math.max(factorAway, LINEUP_MIN_FACTOR), LINEUP_MAX_FACTOR);
  if (factorHome !== rawHome) explanations.push("Tổng điều chỉnh λ của chủ nhà bị chặn ở ±15% để không đi quá xa dữ kiện dài hạn.");
  if (factorAway !== rawAway) explanations.push("Tổng điều chỉnh λ của đội khách bị chặn ở ±15% để không đi quá xa dữ kiện dài hạn.");
  if (!homeMissingN.length && !awayMissingN.length) explanations.push("Đội hình xuất phát không thiếu trụ cột nào so với trận gần nhất — giữ nguyên λ.");
  const round3 = (x) => Math.round(x * 1000) / 1000;
  return { status: "available",
    lambdaHome: round3(lamH * factorHome), lambdaAway: round3(lamA * factorAway),
    lambdaHomeBefore: round3(lamH), lambdaAwayBefore: round3(lamA),
    factorHome: Math.round(factorHome * 10000) / 10000, factorAway: Math.round(factorAway * 10000) / 10000,
    homeMissing: homeMissingN, awayMissing: awayMissingN, explanations,
    notes: ["Điều chỉnh chỉ dựa trên việc trụ cột có mặt hay không trong đội hình công bố; module không biết lý do vắng mặt (ESPN không có nguồn chấn thương đáng tin cậy ở đây)."] };
}
function parseEspnSummary(j, sourceSlug = "") {
  const teams = (j.boxscore && j.boxscore.teams) || [];
  const stats = { home: {}, away: {} };
  const names = { home: "", away: "" };
  const teamIds = { home: "", away: "" };
  teams.forEach((t) => {
    const side = t.homeAway === "away" ? "away" : "home";
    names[side] = (t.team && t.team.displayName) || "";
    teamIds[side] = (t.team && t.team.id) ? String(t.team.id) : "";
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
  // Đội hình (rosters) + 5 trận gần nhất (lastFiveGames): chỉ CHUẨN HÓA dữ liệu ESPN thật sự trả về.
  const rosters = { home: null, away: null };
  const rosterByTeam = [];
  (j.rosters || []).forEach((r) => {
    const side = r.homeAway === "away" ? "away" : "home";
    const players = (r.roster || []).map((p) => {
      const norm = normLineupPlayer({ id: p.athlete && p.athlete.id, name: p.athlete && p.athlete.displayName,
        position: p.position || null });
      if (!norm) return null;
      return { ...norm, starter: !!p.starter, substitute: !p.starter };
    }).filter(Boolean);
    const entry = { side, teamId: (r.team && r.team.id) ? String(r.team.id) : "", teamName: (r.team && r.team.displayName) || "",
      formation: r.formation || "", players };
    rosters[side] = entry;
    rosterByTeam.push(entry);
  });
  const lastFiveByTeam = (j.lastFiveGames || []).map((g) => ({
    teamId: (g.team && g.team.id) ? String(g.team.id) : "", teamName: (g.team && g.team.displayName) || "",
    events: (g.events || []).map((e) => ({
      id: String(e.id || ""), date: e.gameDate || "", homeTeamId: String(e.homeTeamId || ""), awayTeamId: String(e.awayTeamId || ""),
      homeScore: e.homeTeamScore, awayScore: e.awayTeamScore,
      competitionName: e.competitionName || "", leagueName: e.leagueName || "", leagueAbbreviation: e.leagueAbbreviation || "",
      slug: inferEspnSlug(`${e.competitionName || ""} ${e.leagueName || ""} ${e.leagueAbbreviation || ""}`, sourceSlug),
    })).filter((e) => e.id),
  }));
  return { stats, names, teamIds, keyEvents, rosters, rosterByTeam, lastFiveByTeam, sourceSlug };
}
/** Suy slug ESPN từ tên giải trong lastFiveGames (chỉ các giải đã biết; không rõ thì dùng slug hiện tại). */
function inferEspnSlug(text, fallback = "") {
  const s = normTeam(text);
  const has = (...words) => words.every((w) => s.includes(w));
  if (s.includes("champions league two") || s.includes("afc champions league 2")) return "afc.cup";
  if (s.includes("uefa champions league")) return "uefa.champions";
  if (s.includes("uefa europa conference league") || s.includes("conference league")) return "uefa.europa.conf";
  if (s.includes("uefa europa league")) return "uefa.europa";
  if (s.includes("afc champions league")) return "afc.champions";
  if (has("english", "premier league")) return "eng.1";
  if (s.includes("fa cup") && s.includes("english")) return "eng.fa";
  if (s.includes("carabao cup") || s.includes("league cup")) return "eng.league_cup";
  if (s.includes("copa del rey")) return "esp.copa_del_rey";
  if (s.includes("laliga") || s.includes("la liga")) return "esp.1";
  if (s.includes("coppa italia")) return "ita.coppa_italia";
  if (has("italian", "serie a")) return "ita.1";
  if (s.includes("dfb pokal") || s.includes("german cup")) return "ger.dfb_pokal";
  if (s.includes("bundesliga")) return "ger.1";
  if (s.includes("coupe de france")) return "fra.coupe_de_france";
  if (s.includes("ligue 1")) return "fra.1";
  if (s.includes("j league") || s.includes("japanese")) return "jpn.1";
  if (s.includes("saudi")) return "ksa.1";
  if (s.includes("libertadores")) return "conmebol.libertadores";
  if (s.includes("sudamericana")) return "conmebol.sudamericana";
  if (s.includes("mls")) return "usa.1";
  if (s.includes("liga mx")) return "mex.1";
  if (has("brazilian", "serie a")) return "bra.1";
  if (s.includes("argent")) return "arg.1";
  if (s.includes("world cup")) return "fifa.world";
  if (s.includes("club friendly")) return "club.friendly";
  return fallback;
}
function rosterForTeam(summary, team) {
  if (!summary) return null;
  const entries = summary.rosterByTeam || [];
  if (team && team.id) {
    const byId = entries.find((r) => r.teamId === String(team.id));
    if (byId) return byId;
  }
  if (team && team.side && summary.rosters && summary.rosters[team.side]) return summary.rosters[team.side];
  if (team && team.name) {
    const key = cornerTeamKey(team.name);
    return entries.find((r) => cornerNameMatch(cornerTeamKey(r.teamName), key)) || null;
  }
  return null;
}
async function fetchEspnSummary(slug, eventId) {
  const key = `${slug}:${eventId}`;
  const hit = summaryCache.get(key);
  if (hit && Date.now() - hit.t < 30000) return hit.v;
  const j = await fetchJson(`https://site.api.espn.com/apis/site/v2/sports/soccer/${slug}/summary?event=${eventId}`);
  const v = parseEspnSummary(j, slug);
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

/* ---------------------------------------------------------------- lịch theo NGÀY chọn trước (trang Trực tiếp)
   Dạng đúng đã kiểm chứng: scoreboard theo TỪNG ngày (?dates=YYYYMMDD) cho từng giải. Kết quả được
   cache theo (giải, ngày) 10 phút trong bộ nhớ để chuyển ngày/lọc không gọi lại từ đầu. TheSportsDB
   eventsday là lớp bổ sung cho các giải ESPN không có (K League 1, V.League 1...) và là dự phòng
   khi ESPN không phản hồi. */
const dateScoreboardCache = new Map();   // `${slug}|${yyyymmdd}` -> {t, events}
const DATE_CACHE_TTL = 10 * 60 * 1000;
async function fetchEspnEventsForDate(dateStr, force = false) {
  const compact = String(dateStr || "").replace(/-/g, "");
  if (!/^\d{8}$/.test(compact)) throw new Error("Ngày không hợp lệ.");
  const res = await Promise.allSettled(LIVE_LEAGUES.map(async (lg) => {
    const key = `${lg.slug}|${compact}`;
    const hit = dateScoreboardCache.get(key);
    if (!force && hit && Date.now() - hit.t < DATE_CACHE_TTL) return hit.events;
    const j = await fetchJson(`https://site.api.espn.com/apis/site/v2/sports/soccer/${lg.slug}/scoreboard?dates=${compact}`);
    const events = (j.events || []).map((ev) => espnEventToLive(ev, lg)).filter(Boolean);
    dateScoreboardCache.set(key, { t: Date.now(), events });
    return events;
  }));
  const okCount = res.filter((r) => r.status === "fulfilled").length;
  if (!okCount && !LIVE_LEAGUES.some((lg) => dateScoreboardCache.has(`${lg.slug}|${compact}`))) {
    throw new Error("ESPN không phản hồi cho ngày đã chọn.");
  }
  return LIVE_LEAGUES.flatMap((lg) => (dateScoreboardCache.get(`${lg.slug}|${compact}`) || { events: [] }).events);
}
const TSDB_EXTRA_LEAGUE = /(k league|v\.?league|vietnam|viet nam)/i;
async function fetchSportsDbEventsForDate(dateStr) {
  const j = await fetchJson(`https://www.thesportsdb.com/api/v1/json/123/eventsday.php?d=${dateStr}&s=Soccer`);
  const rows = j.events || [];
  return rows.map(sportsDbEventToLive);
}
async function fetchEventsForDate(dateStr, force = false) {
  let espnEvents = [], espnOk = false, tsdbEvents = [], tsdbOk = false;
  try { espnEvents = await fetchEspnEventsForDate(dateStr, force); espnOk = true; } catch (e) { /* dùng TheSportsDB */ }
  try {
    const all = await fetchSportsDbEventsForDate(dateStr);
    // ESPN đã có dữ liệu thì TheSportsDB chỉ bổ sung các giải ESPN không phủ (K League, V.League...);
    // ESPN sập hẳn thì lấy toàn bộ TheSportsDB làm dự phòng.
    tsdbEvents = espnOk ? all.filter((e) => TSDB_EXTRA_LEAGUE.test(e.league || "")) : all;
    tsdbOk = true;
  } catch (e) { /* không có lớp bổ sung */ }
  if (!espnOk && !tsdbOk) throw new Error("Cả ESPN lẫn TheSportsDB đều không phản hồi cho ngày đã chọn.");
  const stateOrder = { in: 0, pre: 1, post: 2 };
  const events = mergeLiveEvents(espnEvents, tsdbEvents).sort((a, b) =>
    String(a.startIso || "").localeCompare(String(b.startIso || ""))
    || (stateOrder[a.state] ?? 3) - (stateOrder[b.state] ?? 3)
    || (LIVE_LEAGUE_ORDER.get(a.slug) ?? 999) - (LIVE_LEAGUE_ORDER.get(b.slug) ?? 999));
  return { events, espnOk, tsdbOk };
}

/* ---------------------------------------------------------------- đội hình trận trước (cho yếu tố đội hình)
   Đội hình xuất phát trận đã kết thúc gần nhất của một đội: lấy từ lastFiveGames trong summary của
   trận hiện tại (sự kiện đã kết thúc mới nhất), rồi gọi summary của chính sự kiện đó bằng slug suy
   từ tên giải của sự kiện (dự phòng: slug của trận hiện tại). Cache localStorage ~3 giờ theo đội —
   đội hình trận trước không đổi sau khi trận đó đã kết thúc. */
const PREV_XI_TTL = 3 * 3600 * 1000;
const prevXiMemory = new Map();
function prevXiCacheKey(slug, teamName) { return `tymex-prevxi-v1:${slug || "x"}:${cornerTeamKey(teamName)}`; }
function readPrevXiCache(slug, teamName) {
  const key = prevXiCacheKey(slug, teamName);
  if (prevXiMemory.has(key)) return prevXiMemory.get(key);
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const o = JSON.parse(raw);
      if (o && Date.now() - o.t < PREV_XI_TTL && Array.isArray(o.xi)) { prevXiMemory.set(key, o.xi); return o.xi; }
    }
  } catch (e) { /* localStorage không khả dụng */ }
  return null;
}
function writePrevXiCache(slug, teamName, xi) {
  const key = prevXiCacheKey(slug, teamName);
  prevXiMemory.set(key, xi);
  try { localStorage.setItem(key, JSON.stringify({ t: Date.now(), xi })); } catch (e) { /* bỏ qua */ }
}
async function fetchPreviousStartingXi(currentSummary, side, currentEvent) {
  if (!currentSummary) return null;
  const teamId = currentSummary.teamIds ? currentSummary.teamIds[side] : "";
  const teamName = currentSummary.names ? currentSummary.names[side] : "";
  const cacheSlug = currentSummary.sourceSlug || (currentEvent && currentEvent.slug) || "";
  const cached = readPrevXiCache(cacheSlug, teamName);
  if (cached) return cached;
  const group = (currentSummary.lastFiveByTeam || []).find((g) =>
    (teamId && g.teamId === teamId) || (teamName && cornerNameMatch(cornerTeamKey(g.teamName), cornerTeamKey(teamName))));
  if (!group) return null;
  const currentStart = currentEvent && currentEvent.startIso ? new Date(currentEvent.startIso).getTime() : null;
  const candidates = group.events
    .filter((e) => e.id && e.id !== String(currentEvent && currentEvent.eventId)
      && e.homeScore !== null && e.homeScore !== undefined && e.homeScore !== "")
    .filter((e) => !currentStart || !e.date || new Date(e.date).getTime() < currentStart)
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
  for (const cand of candidates.slice(0, 2)) {
    const slugs = [...new Set([cand.slug, cacheSlug].filter(Boolean))];
    for (const slug of slugs) {
      try {
        const sum = await fetchEspnSummary(slug, cand.id);
        const roster = rosterForTeam(sum, { id: teamId, name: teamName });
        if (!roster) continue;
        const xi = roster.players.filter((p) => p.starter).map((p) => ({ name: p.name, id: p.id, positionGroup: p.positionGroup }));
        if (xi.length >= 7) { writePrevXiCache(cacheSlug, teamName, xi); return xi; }
      } catch (e) { /* thử slug/sự kiện kế tiếp */ }
    }
  }
  return null;
}

window.TymexLive = {
  predictLive, probTimeline, createSimulation, fetchLiveEvents, fetchEspnSummary, fetchEventsForDate,
  xgProxyFromShots, STAT_DEFS, LEAGUE_AVG_LAMBDAS, DEFAULT_AVG_LAMBDAS, FULL_MINUTES: LIVE_FULL_MINUTES,
  LEAGUE_GROUPS: LIVE_LEAGUE_GROUPS, LEAGUES: LIVE_LEAGUES, normTeam,
  normalizeTeamNameV2, pairKey, sameLiveFixture, mergeLiveEvents,
  goalLines, buildVerdict, VERDICT_DISCLAIMER,
  cornerExpectations, cornerLines, cornerPick, estimateCorners, fetchLeagueCornerRows, cornerRowsCached,
  GOAL_LINES, CORNER_LINES,
  missingRegulars, adjustLambdas, rosterForTeam, fetchPreviousStartingXi,
  LINEUP_ATTACK_DROP, LINEUP_DEFENCE_LEAK, LINEUP_MIN_FACTOR, LINEUP_MAX_FACTOR, LINEUP_GROUP_LABEL,
};
