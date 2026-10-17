/* Football Analytics cá nhân — bản web (Cloudflare Pages + Supabase). Giao diện thuần JavaScript, không cần build.
   Dữ liệu lấy qua data.js (Supabase, có đăng nhập). */
"use strict";

const TZ_OPTIONS = ["Asia/Tokyo", "Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Seoul", "Europe/London", "Europe/Paris", "America/New_York", "UTC"];
const STATUS_LABEL = {
  SCHEDULED: "Sắp đá", TIMED: "Sắp đá", IN_PLAY: "Đang đá", PAUSED: "Nghỉ giữa hiệp", FINISHED: "Kết thúc",
  POSTPONED: "Hoãn", SUSPENDED: "Tạm dừng", CANCELLED: "Hủy", AWARDED: "Xử thắng",
};
const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const state = { status: null, tz: localStorage.getItem("tz") || null, syncPoll: null };

/* ---------------------------------------------------------------- tiện ích */
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v, d = 1) => Number(v).toLocaleString("vi-VN", { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("vi-VN", { minimumFractionDigits: d, maximumFractionDigits: d }));

const api = (path, opts) => Tymex.cloudApi(path, opts);
const qs = (obj) => {
  const p = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") p.set(k, v); });
  const s = p.toString();
  return s ? "?" + s : "";
};
function toast(message, type = "ok") {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), type === "error" ? 9000 : 4500);
}
const tz = () => state.tz || state.status?.default_timezone || "Asia/Tokyo";
const fmtTime = (iso) => new Intl.DateTimeFormat("vi-VN", { timeZone: tz(), hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));
const fmtDate = (iso, long = false) => new Intl.DateTimeFormat("vi-VN", long
  ? { timeZone: tz(), weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" }
  : { timeZone: tz(), day: "2-digit", month: "2-digit", year: "2-digit" }).format(new Date(iso));
const dayKey = (iso) => new Intl.DateTimeFormat("en-CA", { timeZone: tz(), year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
const tzLabel = () => {
  const part = new Intl.DateTimeFormat("en", { timeZone: tz(), timeZoneName: "short" }).formatToParts(new Date()).find((p) => p.type === "timeZoneName");
  return `${part ? part.value : ""} (${tz()})`;
};
function relDay(iso) {
  const now = new Date();
  const k = dayKey(iso), today = dayKey(now.toISOString());
  const tomorrow = dayKey(new Date(now.getTime() + 86400000).toISOString());
  const yesterday = dayKey(new Date(now.getTime() - 86400000).toISOString());
  return k === today ? "Hôm nay" : k === tomorrow ? "Ngày mai" : k === yesterday ? "Hôm qua" : fmtDate(iso);
}
const fmtStamp = (iso) => (iso ? `${fmtDate(iso)} ${fmtTime(iso)}` : "chưa có");
const initials = (name) => (name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 3).toUpperCase();
const crest = (url, name) => url
  ? `<img class="crest" src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.outerHTML='<span class=\\'crest-fallback\\'>${esc(initials(name))}</span>'">`
  : `<span class="crest-fallback">${esc(initials(name))}</span>`;
const loading = (text = "Đang tải dữ liệu…") => `<p class="loading"><span class="spinner"></span>${esc(text)}</p>`;
const errorBox = (e) => `<div class="notice error"><b>Không tải được dữ liệu.</b><br>${esc(e.message || e)}<div style="margin-top:.6rem"><button class="btn btn-small" data-retry>Thử lại</button></div></div>`;
const emptyBox = (text, cta = "") => `<div class="empty">${esc(text)}${cta ? `<div style="margin-top:.6rem">${cta}</div>` : ""}</div>`;

/* ---------------------------------------------------------------- khối hiển thị dùng chung */
function matchRow(m) {
  const done = m.status === "FINISHED", live = m.status === "IN_PLAY" || m.status === "PAUSED";
  const hasScore = m.home_score !== null && m.away_score !== null;
  const hw = done && m.home_score > m.away_score, aw = done && m.away_score > m.home_score;
  const stCls = live ? "live" : done ? "done" : ["POSTPONED", "SUSPENDED", "CANCELLED"].includes(m.status) ? "warn" : "";
  const timeCell = done || live ? `<div class="mtime">${fmtTime(m.utc_date)}<small>${relDay(m.utc_date)}</small></div>`
    : `<div class="mtime">${fmtTime(m.utc_date)}<small>${relDay(m.utc_date)}</small></div>`;
  return `<a class="mrow" href="#/match/${m.id}" aria-label="Phân tích ${esc(m.home_name)} gặp ${esc(m.away_name)}">
    ${timeCell}
    <div class="mteams">
      <div class="mteam ${hw ? "win" : ""}">${crest(m.home_crest, m.home_name)}<span class="name">${esc(m.home_name)}</span>${hasScore ? `<span class="score">${m.home_score}</span>` : ""}</div>
      <div class="mteam ${aw ? "win" : ""}">${crest(m.away_crest, m.away_name)}<span class="name">${esc(m.away_name)}</span>${hasScore ? `<span class="score">${m.away_score}</span>` : ""}</div>
    </div>
    <div class="mside"><span class="status ${stCls}">${esc(STATUS_LABEL[m.status] || m.status)}</span><span class="go">Phân tích</span></div>
  </a>`;
}
function matchList(matches) {
  const groups = new Map();
  matches.forEach((m) => { if (!groups.has(m.league_name)) groups.set(m.league_name, []); groups.get(m.league_name).push(m); });
  return [...groups].map(([league, ms]) => `<div class="league-group"><div class="league-name">${esc(league)}</div><div class="mlist">${ms.map(matchRow).join("")}</div></div>`).join("");
}
const section = (title, matches, emptyText) => `<section class="section"><h2>${esc(title)}<span class="count">${matches.length ? matches.length + " trận" : ""}</span></h2>${matches.length ? matchList(matches) : emptyBox(emptyText)}</section>`;

function filtersBar(leagues, f, onChange, { withDate = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "filters";
  wrap.innerHTML = `
    <select aria-label="Giải đấu" data-f="league"><option value="">Tất cả giải đấu</option>${leagues.map((l) => `<option value="${l.id}" ${String(f.league) === String(l.id) ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select>
    <input type="search" data-f="q" placeholder="Tìm đội bóng…" aria-label="Tìm đội bóng" value="${esc(f.q || "")}">
    ${withDate ? `<button class="btn" data-f="prev" aria-label="Ngày trước">‹</button><input type="date" data-f="date" aria-label="Chọn ngày" value="${esc(f.date || "")}"><button class="btn" data-f="next" aria-label="Ngày sau">›</button><button class="btn" data-f="today">Hôm nay</button>` : ""}`;
  let timer;
  wrap.addEventListener("input", (e) => {
    if (e.target.dataset.f === "q") { clearTimeout(timer); timer = setTimeout(() => onChange({ q: e.target.value.trim() }), 300); }
  });
  wrap.addEventListener("change", (e) => {
    const k = e.target.dataset.f;
    if (k === "league") onChange({ league: e.target.value });
    if (k === "date") onChange({ date: e.target.value });
  });
  wrap.addEventListener("click", (e) => {
    const k = e.target.dataset?.f;
    if (!k || !["prev", "next", "today"].includes(k)) return;
    const cur = f.date || dayKey(new Date().toISOString());
    const d = new Date(cur + "T12:00:00Z");
    if (k === "prev") d.setUTCDate(d.getUTCDate() - 1);
    if (k === "next") d.setUTCDate(d.getUTCDate() + 1);
    onChange({ date: k === "today" ? dayKey(new Date().toISOString()) : d.toISOString().slice(0, 10) });
  });
  return wrap;
}

/* ---------------------------------------------------------------- định tuyến */
function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { parts: path.split("/").filter(Boolean), params: Object.fromEntries(new URLSearchParams(query)) };
}
function setParams(patch) {
  const { parts, params } = parseHash();
  const next = { ...params, ...patch };
  Object.keys(next).forEach((k) => { if (next[k] === "" || next[k] == null) delete next[k]; });
  const s = new URLSearchParams(next).toString();
  location.hash = "#/" + parts.join("/") + (s ? "?" + s : "");
}
const ROUTES = {
  "": ["dashboard", pageDashboard], schedule: ["schedule", pageSchedule], match: ["match", pageMatch],
  standings: ["standings", pageStandings], teams: ["teams", pageTeams], predictions: ["predictions", pageHistory], settings: ["settings", pageSettings],
};
async function render() {
  const { parts, params } = parseHash();
  const [name, fn] = ROUTES[parts[0] || ""] || ROUTES[""];
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  app.innerHTML = loading();
  try {
    if (!state.status) await refreshStatus();
    await fn(parts, params);
  } catch (e) {
    app.innerHTML = errorBox(e);
    $("[data-retry]", app)?.addEventListener("click", render);
  }
  window.scrollTo(0, 0);
}

async function refreshStatus() {
  state.status = await api("/status");
  if (!state.tz) state.tz = state.status.default_timezone;
  const b = $("#banners");
  const s = state.status;
  let html = "";
  if (s.is_test_data) html += `<div class="banner banner-test"><b>DỮ LIỆU KIỂM THỬ</b> — đây là dữ liệu giả để thử giao diện, KHÔNG phải dữ liệu bóng đá thật. Đừng dùng để tham khảo nhận định.</div>`;
  if (!s.has_data) html += `<div class="banner banner-warn">Chưa có dữ liệu. Chờ lần đồng bộ đầu tiên của GitHub Actions hoàn tất (xem hướng dẫn triển khai).</div>`;
  b.innerHTML = html;
}

/* ---------------------------------------------------------------- Dashboard */
async function pageDashboard(_, params) {
  const s = state.status;
  const f = { league: params.league || "", q: params.q || "" };
  const base = { tz: tz(), league_id: f.league, q: f.q };
  app.innerHTML = "";
  const head = document.createElement("div");
  head.className = "page-head";
  head.innerHTML = `<h1>Tổng quan</h1><span class="muted small">Giờ hiển thị: ${esc(tzLabel())} · Cập nhật dữ liệu: ${esc(fmtStamp(s.last_sync))}</span>`;
  app.appendChild(head);
  app.appendChild(filtersBar(s.leagues, f, (p) => setParams({ league: p.league ?? f.league, q: p.q ?? f.q })));
  if (!s.has_data) {
    app.insertAdjacentHTML("beforeend", `<div class="notice"><h2>Chưa có dữ liệu</h2><p>Dữ liệu do GitHub Actions đồng bộ tự động. Sau lần chạy thành công đầu tiên, hãy bấm <b>Làm mới</b>.</p></div>`);
    return;
  }
  const holder = document.createElement("div");
  holder.innerHTML = loading();
  app.appendChild(holder);
  const [live, today, tomorrow, upcoming, finished] = await Promise.all([
    api("/matches" + qs({ ...base, scope: "live" })), api("/matches" + qs({ ...base, day: "today" })),
    api("/matches" + qs({ ...base, day: "tomorrow" })), api("/matches" + qs({ ...base, scope: "upcoming", limit: 40 })),
    api("/matches" + qs({ ...base, scope: "finished", limit: 20 })),
  ]);
  const seen = new Set([...live.matches, ...today.matches, ...tomorrow.matches].map((m) => m.id));
  const rest = (arr, n) => arr.filter((m) => !seen.has(m.id)).slice(0, n);
  holder.innerHTML = "";
  if (live.matches.length) holder.insertAdjacentHTML("beforeend", section("Đang diễn ra", live.matches, ""));
  holder.insertAdjacentHTML("beforeend", section("Hôm nay", today.matches, "Không có trận nào hôm nay theo bộ lọc hiện tại."));
  holder.insertAdjacentHTML("beforeend", section("Ngày mai", tomorrow.matches, "Không có trận nào ngày mai theo bộ lọc hiện tại."));
  holder.insertAdjacentHTML("beforeend", section("Sắp diễn ra", rest(upcoming.matches, 12), "Chưa có trận sắp tới nào trong dữ liệu đã đồng bộ."));
  holder.insertAdjacentHTML("beforeend", section("Đã kết thúc gần đây", rest(finished.matches, 12), "Chưa có kết quả nào trong dữ liệu đã đồng bộ."));
}

/* ---------------------------------------------------------------- Lịch thi đấu */
async function pageSchedule(_, params) {
  const s = state.status;
  const f = { league: params.league || "", q: params.q || "", date: params.date || (params.team ? "" : dayKey(new Date().toISOString())), team: params.team || "" };
  app.innerHTML = "";
  let title = "Lịch thi đấu";
  if (f.team) {
    try { title = "Lịch thi đấu: " + (await api("/teams")).teams.find((t) => String(t.id) === f.team)?.name; } catch { /* giữ tiêu đề mặc định */ }
  }
  app.insertAdjacentHTML("beforeend", `<div class="page-head"><h1>${esc(title)}</h1><span class="muted small">Giờ hiển thị: ${esc(tzLabel())}</span></div>`);
  app.appendChild(filtersBar(s.leagues, f, (p) => setParams({ league: p.league ?? f.league, q: p.q ?? f.q, date: p.date ?? f.date, team: f.team }), { withDate: !f.team }));
  if (f.team) app.insertAdjacentHTML("beforeend", `<p><a class="btn btn-small" href="#/schedule">Bỏ lọc theo đội</a></p>`);
  const holder = document.createElement("div");
  holder.innerHTML = loading();
  app.appendChild(holder);
  const res = await api("/matches" + qs({ tz: tz(), league_id: f.league, q: f.q, team_id: f.team, day: f.team ? "" : f.date, limit: f.team ? 80 : 200 }));
  if (!res.matches.length) { holder.innerHTML = emptyBox("Không có trận nào khớp bộ lọc. Thử chọn ngày khác hoặc bỏ bớt bộ lọc."); return; }
  holder.innerHTML = (f.date && !f.team ? `<h2 style="margin-bottom:.6rem">${esc(fmtDate(f.date + "T12:00:00Z", true))}</h2>` : "") + matchList(res.matches);
}

/* ---------------------------------------------------------------- Chi tiết trận */
const resChip = (r) => `<span class="chip ${r}" title="${{ W: "Thắng", D: "Hòa", L: "Thua" }[r]}">${{ W: "T", D: "H", L: "B" }[r]}</span>`;

function gamesTable(games) {
  if (!games.length) return emptyBox("Chưa có trận nào trong dữ liệu.");
  return `<div class="t-scroll"><table class="t"><thead><tr><th>Ngày</th><th>Sân</th><th>Đối thủ</th><th class="r">Tỷ số</th><th></th></tr></thead><tbody>${games.map((g) =>
    `<tr><td>${esc(fmtDate(g.utc_date))}</td><td>${g.venue === "H" ? "Nhà" : "Khách"}</td><td>${esc(g.opponent)}</td><td class="r num">${g.gf}-${g.ga}</td><td class="r">${resChip(g.result)}</td></tr>`).join("")}</tbody></table></div>`;
}
const sumBoxes = (s) => `<div class="sumgrid">
  <div class="fact-box"><div class="v">${s.points}</div><div class="l">điểm / ${s.played} trận</div></div>
  <div class="fact-box"><div class="v">${s.wins}-${s.draws}-${s.losses}</div><div class="l">thắng-hòa-thua</div></div>
  <div class="fact-box"><div class="v">${s.clean_sheets}</div><div class="l">trận giữ sạch lưới</div></div>
  <div class="fact-box"><div class="v">${num(s.avg_goals_for)}</div><div class="l">bàn thắng TB</div></div>
  <div class="fact-box"><div class="v">${num(s.avg_goals_against)}</div><div class="l">bàn thua TB</div></div>
  <div class="fact-box"><div class="v">${s.win_rate === null ? "—" : pct(s.win_rate, 0) + "%"}</div><div class="l">tỷ lệ thắng</div></div></div>`;

function predictionBlock(a) {
  const p = a.prediction, m = a.match;
  if (!p.available) {
    return `<section class="block"><h2>Dự đoán thống kê</h2><div class="notice warn"><b>Chưa thể dự đoán.</b><br>${esc(p.reason)}<br><span class="small">Hệ thống không tạo con số dự đoán khi dữ liệu không đủ.</span></div></section>`;
  }
  const pc = p.percent;
  const maxP = Math.max(...p.matrix.flat());
  const pick = p.predicted_score;
  const head = ["0", "1", "2", "3", "4", "5"];
  const matrix = `<div class="matrix-wrap"><table class="matrix" aria-label="Ma trận xác suất tỷ số"><tr><th></th>${head.map((h) => `<th>${h}</th>`).join("")}</tr>${p.matrix.map((row, i) =>
    `<tr><th>${i}</th>${row.map((v, j) => `<td class="${i === pick.home && j === pick.away ? "pick" : ""}" style="--p:${(v / maxP * 0.2).toFixed(3)}" title="${i}-${j}: ${pct(v * 100)}%">${pct(v * 100, 1)}</td>`).join("")}</tr>`).join("")}</table></div>
    <div class="axis-note">Hàng = bàn của ${esc(m.home_name)} (chủ nhà), cột = bàn của ${esc(m.away_name)}. Số trong ô là xác suất (%).</div>`;
  const stamp = p.mode === "stored_pre_match" ? `Đã lưu lúc ${fmtStamp(p.created_at)} (${tzLabel()})` : "";
  return `<section class="block"><h2>Dự đoán thống kê (Poisson)</h2>
    <p class="block-sub">${esc(p.label || "")} ${esc(stamp)}</p>
    ${p.mode === "recomputed_pre_match" ? `<div class="notice warn" style="margin-bottom:.8rem">Trận đã diễn ra và hệ thống không có bản dự đoán lưu trước trận. Con số dưới đây được tính lại chỉ bằng dữ liệu có trước giờ bóng lăn.</div>` : ""}
    <div class="pstrip" role="img" aria-label="Xác suất: chủ nhà ${pc.home}%, hòa ${pc.draw}%, khách ${pc.away}%">
      <div class="h" style="width:${pc.home}%">${pct(pc.home)}%</div><div class="d" style="width:${pc.draw}%">${pct(pc.draw)}%</div><div class="a" style="width:${pc.away}%">${pct(pc.away)}%</div></div>
    <div class="plabels"><span>${esc(m.home_name)} thắng</span><span>Hòa</span><span>${esc(m.away_name)} thắng</span></div>
    <div class="facts">
      <div class="fact-box"><div class="v">${num(p.lambda_home)} - ${num(p.lambda_away)}</div><div class="l">bàn thắng kỳ vọng (nhà - khách): con số phân biệt các trận rõ nhất</div></div>
      <div class="fact-box"><div class="v">${pick.home} - ${pick.away}</div><div class="l">tỷ số đơn lẻ hay gặp nhất, chỉ ${pct(pick.prob * 100)}% khả năng đúng</div></div>
      <div class="fact-box"><div class="v">${pct(p.over_2_5 * 100, 0)}%</div><div class="l">trên 2,5 bàn</div></div>
      <div class="fact-box"><div class="v">${pct(p.both_teams_score * 100, 0)}%</div><div class="l">cả hai đội cùng ghi bàn</div></div></div>
    <h3>Ma trận tỷ số</h3>${matrix}
    <h3 style="margin-top:.8rem">Các tỷ số khả dĩ nhất</h3>
    <p>${p.top_scores.map((t) => `<span class="num">${t.home}-${t.away}</span> (${pct(t.prob * 100)}%)`).join(" &nbsp; ")}</p>
    <h3 style="margin-top:.8rem">Yếu tố làm tăng/giảm đánh giá của mô hình</h3>
    <ul class="factors">${p.factors.map((x) => `<li class="${x.direction}">${esc(x.text)}</li>`).join("")}</ul>
    <p class="small muted" style="margin-top:.8rem">Dữ liệu mô hình dùng: ${p.quality.league_games} trận của giải, ${p.quality.home_games} trận của chủ nhà, ${p.quality.away_games} trận của đội khách (trong ${p.quality.lookback_days} ngày). Độ tin cậy ước lượng: <b>${esc(p.quality.reliability)}</b>. ${esc((p.notes || []).join(" "))}</p></section>`;
}

const MARKET_SOURCE = {
  AvgC: "trung bình nhiều nhà cái lúc đóng cửa (football-data.co.uk)", Avg: "trung bình nhiều nhà cái (football-data.co.uk)",
  PinnC: "Pinnacle lúc đóng cửa", Pinn: "Pinnacle", B365C: "Bet365 lúc đóng cửa", B365: "Bet365", BbAv: "trung bình nhiều nhà cái",
};
function marketSourceLabel(src) {
  const m = /^(OddsAPI|the-odds-api|api-football):(\d+)$/.exec(src || "");
  if (m) return `trung bình ${m[2]} nhà cái (${m[1] === "api-football" ? "API-Football" : "The Odds API"})`;
  return MARKET_SOURCE[src] || src || "không rõ";
}
function marketBlock(a) {
  const k = a.market, m = a.match;
  if (!k) return "";
  if (!k.available) {
    return `<section class="block"><h2>So sánh với nhà cái</h2><div class="notice">${esc(k.reason)}</div></section>`;
  }
  const strip = (p, label) => `<div class="mk-row"><div class="mk-label">${label}</div>
    <div class="pstrip" role="img" aria-label="${esc(label)}: chủ nhà ${pct(p.home * 100, 0)}%, hòa ${pct(p.draw * 100, 0)}%, khách ${pct(p.away * 100, 0)}%">
      <div class="h" style="width:${p.home * 100}%">${pct(p.home * 100, 0)}%</div><div class="d" style="width:${p.draw * 100}%">${pct(p.draw * 100, 0)}%</div><div class="a" style="width:${p.away * 100}%">${pct(p.away * 100, 0)}%</div></div></div>`;
  const names = { home: `${m.home_name} thắng`, draw: "Hòa", away: `${m.away_name} thắng` };
  const sign = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + pct(Math.abs(v) * 100, 0);
  const tbl = k.model ? `<div class="t-scroll"><table class="t"><thead><tr><th>Kết quả</th><th class="r">Mô hình</th><th class="r">Thị trường</th><th class="r">Chênh lệch (điểm %)</th><th class="r">Tỷ lệ cược</th></tr></thead><tbody>${["home", "draw", "away"].map((x) =>
    `<tr><td>${esc(names[x])}</td><td class="r num">${pct(k.model[x] * 100, 0)}%</td><td class="r num">${pct(k.market[x] * 100, 0)}%</td><td class="r num">${sign(k.diff[x])}</td><td class="r num">${num(k.odds[x])}</td></tr>`).join("")}</tbody></table></div>` : "";
  return `<section class="block"><h2>So sánh với nhà cái</h2>
    <p class="block-sub">Nguồn: ${esc(marketSourceLabel(k.source))}. Cập nhật lúc ${esc(fmtStamp(k.updated_at))} (${esc(tzLabel())}). Đã loại phần lợi nhuận của nhà cái (khoảng ${pct(k.margin * 100, 1)}%).</p>
    ${k.model ? strip(k.model, "Mô hình Poisson") : ""}${strip(k.market, "Thị trường cược")}
    <div class="plabels"><span>${esc(m.home_name)} thắng</span><span>Hòa</span><span>${esc(m.away_name)} thắng</span></div>
    ${tbl}
    <div class="notice ${k.level === "agree" || k.level === "none" ? "" : "warn"}" style="margin-top:.8rem">${esc(k.verdict)}</div></section>`;
}

function availabilityBlock(a) {
  const v = a.availability, m = a.match;
  if (!v) return "";
  if (!v.available) return `<section class="block"><h2>Vắng mặt / chấn thương</h2><div class="notice">${esc(v.reason)}</div></section>`;
  const col = (t) => {
    const li = (arr, label) => arr.length ? `<h3 class="small muted">${label}</h3><ul class="plain">${arr.map((x) => `<li>${esc(x.player)}${x.reason ? ` <span class="muted small">(${esc(x.reason)})</span>` : ""}</li>`).join("")}</ul>` : "";
    return `<div><h3>${esc(t.team)}</h3>${li(t.out, "Vắng mặt")}${li(t.doubtful, "Nghi ngờ")}${!t.out.length && !t.doubtful.length ? '<p class="muted small">Chưa có tin.</p>' : ""}</div>`;
  };
  const adj = v.adjusted ? (() => {
    const names = { home: `${m.home_name} thắng`, draw: "Hòa", away: `${m.away_name} thắng` };
    return `<div class="t-scroll"><table class="t"><thead><tr><th>Kết quả</th><th class="r">Dự đoán đã lưu</th><th class="r">Điều chỉnh (tham khảo)</th></tr></thead><tbody>${["home", "draw", "away"].map((x) =>
      `<tr><td>${esc(names[x])}</td><td class="r num">${pct(v.adjusted.before[x] * 100, 0)}%</td><td class="r num">${pct(v.adjusted.after[x] * 100, 0)}%</td></tr>`).join("")}</tbody></table></div>
      <div class="notice warn" style="margin-top:.8rem">${esc(v.note)}</div>` : "";
  })() : "";
  return `<section class="block"><h2>Vắng mặt / chấn thương</h2>
    <p class="block-sub">Nguồn: API-Football. Cập nhật lúc ${esc(fmtStamp(v.updated_at))} (${esc(tzLabel())}). Tin có thể chưa đầy đủ; đội hình xuất phát chỉ có sát giờ đá.</p>
    <div class="cols">${col(v.teams.home)}${col(v.teams.away)}</div>${adj}</section>`;
}

function formBlock(a, n) {
  const col = (name, f, cls) => `<div><h3>${esc(name)} <span class="muted small">(${cls})</span></h3>
    <div class="chips" style="margin-top:.5rem">${f.games.map((g) => resChip(g.result)).join("") || '<span class="muted">Chưa có dữ liệu</span>'}</div>
    ${f.available ? sumBoxes(f.summary) : ""}${f.available < f.requested ? `<p class="small muted">Chỉ có ${f.available}/${f.requested} trận trong dữ liệu đã đồng bộ.</p>` : ""}${gamesTable(f.games)}</div>`;
  return `<section class="block"><div class="row" style="justify-content:space-between"><h2>Phong độ ${n} trận gần nhất</h2>
    <div class="seg" role="group" aria-label="Số trận"><button data-n="5" class="${n === 5 ? "on" : ""}">5 trận</button><button data-n="10" class="${n === 10 ? "on" : ""}">10 trận</button></div></div>
    <p class="block-sub">${esc(a.data_scope_note)}</p>
    <div class="cols">${col(a.match.home_name, a.form.home, "chủ nhà")}${col(a.match.away_name, a.form.away, "đội khách")}</div></section>`;
}
function venueBlock(a) {
  const col = (name, v, label) => `<div><h3>${esc(name)} — ${label}</h3>${v.available ? sumBoxes(v.summary) : ""}
    <p class="small muted">Dựa trên ${v.available}/${v.requested} trận gần nhất ${label}. Tỷ lệ giữ sạch lưới: ${v.summary.clean_sheet_rate === null ? "—" : pct(v.summary.clean_sheet_rate, 0) + "%"}.</p>${v.available ? "" : emptyBox("Chưa có dữ liệu.")}</div>`;
  return `<section class="block"><h2>Sân nhà và sân khách</h2><div class="cols">${col(a.match.home_name, a.venue.home, "trên sân nhà")}${col(a.match.away_name, a.venue.away, "trên sân khách")}</div></section>`;
}
function h2hBlock(a) {
  const h = a.head_to_head, s = h.summary, m = a.match;
  if (!h.available) return `<section class="block"><h2>Lịch sử đối đầu</h2>${emptyBox("Không có trận đối đầu nào trong dữ liệu đã đồng bộ. Hệ thống không tự tạo lịch sử đối đầu.")}</section>`;
  const t = s.played;
  return `<section class="block"><h2>Lịch sử đối đầu</h2><p class="block-sub">${h.available} trận gần nhất có dữ liệu (tối đa ${h.requested}).</p>
    <div class="h2h-bar"><div class="h" style="width:${s.a_wins / t * 100}%"></div><div class="d" style="width:${s.draws / t * 100}%"></div><div class="a" style="width:${s.b_wins / t * 100}%"></div></div>
    <div class="plabels"><span>${esc(m.home_name)} thắng ${s.a_wins}</span><span>Hòa ${s.draws}</span><span>${esc(m.away_name)} thắng ${s.b_wins}</span></div>
    <p class="small muted">Tổng bàn thắng: ${esc(m.home_name)} ${s.a_goals} - ${s.b_goals} ${esc(m.away_name)}.</p>
    <div class="t-scroll"><table class="t"><thead><tr><th>Ngày</th><th>Trận đấu</th><th class="r">Tỷ số</th><th>Kết quả</th></tr></thead><tbody>${h.games.map((g) =>
      `<tr><td>${esc(fmtDate(g.utc_date))}</td><td>${esc(g.home_name)} - ${esc(g.away_name)}</td><td class="r num">${g.home_score}-${g.away_score}</td><td>${g.winner === "A" ? esc(m.home_name) : g.winner === "B" ? esc(m.away_name) : "Hòa"}</td></tr>`).join("")}</tbody></table></div></section>`;
}
function scoreLine(sc, m) {
  if (!sc) return "";
  const top = sc.top.map((t, k) => `<span class="sc${k === 0 ? " first" : ""}"><b class="num">${t.home}-${t.away}</b> ${pct(t.prob * 100, 0)}%</span>`).join("");
  return `<div class="line score"><span class="k">Tỷ số gợi ý</span><span class="v"><span class="xg">Bàn kỳ vọng <b class="num">${num(sc.lambda_home)} - ${num(sc.lambda_away)}</b></span> ${top}
    <span class="small muted">(theo góc nhìn này: ${esc(sc.basis)}; % là khả năng đúng chính xác tỷ số đó)</span></span></div>`;
}
function conclusionBlock(a) {
  const c = a.conclusions;
  return `<section class="block"><h2>Kết luận phân tích</h2><p class="block-sub">Mỗi mục tách rõ dữ kiện (số liệu) và suy luận (diễn giải từ số liệu).</p>
    ${c.items.map((i) => `<div class="concl"><h3>${esc(i.topic)}</h3><div class="line fact"><span class="k">Dữ kiện</span><span class="v">${esc(i.fact)}</span></div><div class="line infer"><span class="k">Suy luận</span><span class="v">${esc(i.inference)}</span></div>${scoreLine(i.score, a.match)}</div>`).join("")}
    <div class="concl"><h3>Dữ liệu còn thiếu khiến nhận định kém chắc chắn</h3><ul class="gaps">${c.data_gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></div></section>`;
}
async function pageMatch(parts) {
  const id = Number(parts[1]);
  if (!Number.isInteger(id)) throw new Error("Đường dẫn trận đấu không hợp lệ.");
  let n = 5;
  const load = async () => {
    const a = await api(`/matches/${id}/analysis?form_n=${n}`);
    const m = a.match, done = m.status === "FINISHED", has = m.home_score !== null && m.away_score !== null;
    app.innerHTML = `<p><a class="muted" href="javascript:history.back()">‹ Quay lại</a></p>
      <section class="match-head"><div class="meta">${esc(m.league_name)}${m.matchday ? ` · Vòng ${m.matchday}` : ""}${m.season ? ` · Mùa ${m.season}/${String(m.season + 1).slice(2)}` : ""}
        ${a.is_test_data ? '<span class="tag-test">DỮ LIỆU KIỂM THỬ</span>' : ""}<br>${esc(relDay(m.utc_date))}, ${esc(fmtDate(m.utc_date, true))} lúc <b>${esc(fmtTime(m.utc_date))}</b> — múi giờ ${esc(tzLabel())}</div>
        <div class="versus"><div class="vteam home">${crest(m.home_crest, m.home_name)}<h2>${esc(m.home_name)}</h2><span class="role">Chủ nhà (sân nhà)</span></div>
        <div class="vscore">${has ? `${m.home_score} - ${m.away_score}` : "vs"}<small>${esc(STATUS_LABEL[m.status] || m.status)}${done && m.home_ht !== null ? ` · H1 ${m.home_ht}-${m.away_ht}` : ""}</small></div>
        <div class="vteam away">${crest(m.away_crest, m.away_name)}<h2>${esc(m.away_name)}</h2><span class="role">Đội khách (sân khách)</span></div></div></section>`;
    app.insertAdjacentHTML("beforeend", predictionBlock(a) + marketBlock(a) + availabilityBlock(a) + formBlock(a, a.form_n) + venueBlock(a) + h2hBlock(a));
    app.insertAdjacentHTML("beforeend", `<section class="block"><h2>Thống kê nâng cao</h2><div class="notice">${esc(a.advanced.available ? "Có dữ liệu nâng cao." : a.advanced.reason)}</div></section>`);
    app.insertAdjacentHTML("beforeend", conclusionBlock(a));
    app.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", async () => { n = Number(b.dataset.n); await load(); }));
  };
  await load();
}

/* ---------------------------------------------------------------- Bảng xếp hạng, đội bóng */
async function pageStandings(_, params) {
  const leagues = state.status.leagues;
  if (!leagues.length) { app.innerHTML = `<div class="page-head"><h1>Bảng xếp hạng</h1></div>` + emptyBox("Chưa có giải đấu nào. Hãy đồng bộ dữ liệu trước."); return; }
  const lid = params.league || leagues[0].id;
  const res = await api(`/standings?league_id=${lid}`);
  app.innerHTML = `<div class="page-head"><h1>Bảng xếp hạng</h1><span class="muted small">Cập nhật: ${esc(fmtStamp(res.updated_at))}</span></div>
    <div class="filters"><select id="st-league" aria-label="Giải đấu">${leagues.map((l) => `<option value="${l.id}" ${String(l.id) === String(lid) ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></div>`;
  $("#st-league").addEventListener("change", (e) => setParams({ league: e.target.value }));
  if (!res.groups.length) { app.insertAdjacentHTML("beforeend", emptyBox("Chưa có bảng xếp hạng cho giải này (giải loại trực tiếp hoặc chưa đồng bộ).")); return; }
  res.groups.forEach((g) => {
    app.insertAdjacentHTML("beforeend", `<section class="block">${g.name ? `<h2>${esc(g.name.replace("_", " "))}</h2>` : ""}<div class="t-scroll"><table class="t"><thead><tr><th>#</th><th>Đội</th><th class="r">Trận</th><th class="r">T</th><th class="r">H</th><th class="r">B</th><th class="r">BT</th><th class="r">BB</th><th class="r">HS</th><th class="r">Điểm</th></tr></thead><tbody>${g.rows.map((r) =>
      `<tr><td class="num">${r.position}</td><td><a class="tname" href="#/schedule?team=${r.team_id}">${crest(r.crest_url, r.team_name)}<span>${esc(r.team_name)}</span></a></td><td class="r num">${r.played}</td><td class="r num">${r.won}</td><td class="r num">${r.draw}</td><td class="r num">${r.lost}</td><td class="r num">${r.goals_for}</td><td class="r num">${r.goals_against}</td><td class="r num">${r.goal_diff > 0 ? "+" : ""}${r.goal_diff}</td><td class="r num"><b>${r.points}</b></td></tr>`).join("")}</tbody></table></div></section>`);
  });
}
async function pageTeams(_, params) {
  const leagues = state.status.leagues;
  const f = { league: params.league || "", q: params.q || "" };
  app.innerHTML = `<div class="page-head"><h1>Đội bóng</h1></div>`;
  app.appendChild(filtersBar(leagues, f, (p) => setParams({ league: p.league ?? f.league, q: p.q ?? f.q })));
  const res = await api("/teams" + qs({ league_id: f.league, q: f.q }));
  if (!res.teams.length) { app.insertAdjacentHTML("beforeend", emptyBox("Không có đội bóng nào khớp. Nếu chưa có dữ liệu, hãy đồng bộ trước.")); return; }
  app.insertAdjacentHTML("beforeend", `<div class="teams-grid">${res.teams.map((t) => `<a class="team-card" href="#/schedule?team=${t.id}">${crest(t.crest_url, t.name)}<div><div>${esc(t.name)}</div><div class="leagues">${esc(t.leagues.map((l) => l.name).join(", "))}</div></div></a>`).join("")}</div>`);
}

/* ---------------------------------------------------------------- Lịch sử dự đoán */
const OUT = { H: "Chủ nhà thắng", D: "Hòa", A: "Khách thắng" };
async function pageHistory(_, params) {
  const kind = params.kind === "backtest" ? "backtest" : "live";
  const [sum, list] = await Promise.all([api(`/predictions/summary?kind=${kind}`), api(`/predictions?kind=${kind}&limit=150`)]);
  const o = sum.overall;
  app.innerHTML = `<div class="page-head"><h1>Lịch sử dự đoán</h1>
    <div class="seg"><button data-k="live" class="${kind === "live" ? "on" : ""}">Dự đoán thật (lưu trước trận)</button><button data-k="backtest" class="${kind === "backtest" ? "on" : ""}">Kiểm tra lại trên trận cũ</button></div></div>
    <p class="muted">${kind === "live"
      ? "Chỉ gồm dự đoán được lưu TRƯỚC giờ bóng lăn. Tất cả đều được giữ lại, kể cả dự đoán sai; không có dự đoán nào bị xóa hay chỉnh sửa."
      : "Mô hình được chạy lại trên các trận đã kết thúc, chỉ dùng dữ liệu có trước giờ bóng lăn của từng trận. Đây là kiểm tra mô hình, KHÔNG phải dự đoán đã công bố trước trận."}</p>`;
  if (kind === "backtest") app.insertAdjacentHTML("beforeend", `<p class="small muted">Kiểm tra lại chạy tự động trong mỗi lần đồng bộ (100 trận đã kết thúc gần nhất chưa được đánh giá).</p>`);
  app.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => setParams({ kind: b.dataset.k })));
  if (!o.n) {
    app.insertAdjacentHTML("beforeend", emptyBox(kind === "live"
      ? `Chưa có dự đoán nào được chấm điểm. ${sum.total_predictions ? `Đã lưu ${sum.total_predictions} dự đoán, đang chờ các trận kết thúc.` : "Dự đoán được lưu tự động khi bạn mở trang phân tích của một trận sắp đá hoặc sau mỗi lần cập nhật dữ liệu."}`
      : "Chưa có kết quả kiểm tra lại. Bấm nút phía trên (cần đã đồng bộ dữ liệu)."));
  } else {
    app.insertAdjacentHTML("beforeend", `<div class="metrics">
      <div class="fact-box"><div class="v">${o.n}</div><div class="l">trận đã chấm điểm</div></div>
      <div class="fact-box"><div class="v">${pct(o.accuracy)}%</div><div class="l">đúng kết quả 1X2</div></div>
      <div class="fact-box"><div class="v">${num(o.brier, 3)}</div><div class="l">Brier (đoán đều 1/3 = ${num(sum.baseline.brier_uniform, 3)}; thấp hơn là tốt)</div></div>
      <div class="fact-box"><div class="v">${num(o.log_loss, 3)}</div><div class="l">Log loss (đoán đều = ${num(sum.baseline.log_loss_uniform, 3)})</div></div>
      <div class="fact-box"><div class="v">${num(o.mae_home_goals)} / ${num(o.mae_away_goals)}</div><div class="l">sai số bàn thắng TB (nhà / khách)</div></div>
      <div class="fact-box"><div class="v">${pct(o.exact_score_rate)}%</div><div class="l">đúng chính xác tỷ số</div></div></div>
      <div class="cols"><section class="block"><h2>Theo giải đấu</h2>${groupTable(sum.by_league, "league")}</section><section class="block"><h2>Theo tháng</h2>${groupTable(sum.by_month, "month")}</section></div>`);
  }
  if (list.predictions.length) {
    app.insertAdjacentHTML("beforeend", `<section class="block"><h2>Từng dự đoán</h2><div class="t-scroll"><table class="t"><thead><tr><th>Trận</th><th>Đã lưu lúc</th><th>Dự đoán (nhà/hòa/khách)</th><th>Kết quả</th><th></th></tr></thead><tbody>${list.predictions.map((p) =>
      `<tr><td><a href="#/match/${p.match_id}"><u>${esc(p.home_name)} - ${esc(p.away_name)}</u></a><div class="small muted">${esc(p.league_name)} · ${esc(fmtDate(p.utc_date))}</div></td>
      <td class="small">${esc(fmtStamp(p.created_at))}</td><td class="num">${pct(p.p_home * 100, 0)}/${pct(p.p_draw * 100, 0)}/${pct(p.p_away * 100, 0)}% · ${p.predicted_home}-${p.predicted_away}</td>
      <td class="num">${p.actual_outcome ? `${p.home_score}-${p.away_score}` : p.status === "FINISHED" ? "Không chấm" : "Chưa đá"}</td>
      <td>${p.actual_outcome ? `<span class="chip ${p.correct ? "W" : "L"}">${p.correct ? "Đúng" : "Sai"}</span>` : ""}</td></tr>`).join("")}</tbody></table></div></section>`);
  }
}
const groupTable = (rows, key) => `<table class="t"><thead><tr><th>${key === "league" ? "Giải" : "Tháng"}</th><th class="r">Trận</th><th class="r">Đúng</th><th class="r">Brier</th></tr></thead><tbody>${rows.map((r) =>
  `<tr><td>${esc(r[key])}</td><td class="r num">${r.n}</td><td class="r num">${pct(r.accuracy, 0)}%</td><td class="r num">${num(r.brier, 3)}</td></tr>`).join("")}</tbody></table>`;

/* ---------------------------------------------------------------- Tài khoản */
async function pageSettings() {
  const sess = await Tymex.auth.session();
  const st = state.status;
  app.innerHTML = `<div class="page-head"><h1>Tài khoản</h1></div>
  <section class="block"><h2>Đăng nhập</h2><p>Đang đăng nhập: <b>${esc(sess?.user?.email || "")}</b></p>
    <p><button class="btn" id="logout">Đăng xuất</button></p></section>
  <section class="block"><h2>Dữ liệu</h2>
    <p>Đồng bộ từ football-data.org lần gần nhất: <b>${esc(fmtStamp(st.last_sync))}</b>. Dữ liệu đưa lên web lúc: <b>${esc(fmtStamp(st.published_at))}</b>.</p>
    <p class="small muted">Dữ liệu được GitHub Actions cập nhật tự động theo lịch (không phải trực tiếp từng phút nên tỷ số trận đang đá có thể chậm). Khóa API bóng đá nằm trong GitHub Secrets, không bao giờ đến trình duyệt. Muốn cập nhật ngay: GitHub → Actions → "Đồng bộ dữ liệu" → Run workflow.</p>
    <p class="small muted">Số liệu hiện có: ${st.counts.matches} trận, ${st.counts.teams} đội, ${st.counts.predictions} dự đoán đã lưu.</p></section>`;
  $("#logout").addEventListener("click", () => Tymex.auth.signOut());
}

/* ---------------------------------------------------------------- Đăng nhập */
function showLogin(message = "") {
  document.body.classList.add("logged-out");
  $("#banners").innerHTML = "";
  app.innerHTML = `<form class="login" id="login-form" autocomplete="on">
    <h1>Football Analytics</h1><p class="muted">Đăng nhập để xem dữ liệu.</p>
    ${Tymex.configured() ? "" : `<div class="notice error">Chưa cấu hình Supabase. Điền <code>SUPABASE_URL</code> và <code>SUPABASE_ANON_KEY</code> trong <code>config.js</code>.</div>`}
    <label>Tên đăng nhập<input id="login-user" name="username" type="text" autocomplete="username" required autocapitalize="none" spellcheck="false"></label>
    <label>Mật khẩu<input id="login-pass" name="password" type="password" autocomplete="current-password" required></label>
    <div class="notice error" id="login-err" ${message ? "" : "hidden"}>${esc(message)}</div>
    <button class="btn btn-accent" type="submit">Đăng nhập</button></form>`;
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#login-form button"), err = $("#login-err");
    btn.disabled = true; err.hidden = true;
    try { await Tymex.auth.signIn($("#login-user").value, $("#login-pass").value); }
    catch (ex) { err.textContent = ex.message; err.hidden = false; btn.disabled = false; }
  });
}

/* ---------------------------------------------------------------- khởi động */
let started = false;
async function enter(session) {
  if (!session) { state.status = null; Tymex.clearCache(); showLogin(); return; }
  document.body.classList.remove("logged-out");
  state.status = null;
  await render();
}
function init() {
  const sel = $("#tz-select");
  const saved = state.tz;
  const opts = [...new Set([saved, ...TZ_OPTIONS].filter(Boolean))];
  sel.innerHTML = opts.map((z) => `<option value="${z}">${z}</option>`).join("");
  sel.value = saved || "Asia/Tokyo";
  state.tz = sel.value;
  sel.addEventListener("change", () => { state.tz = sel.value; localStorage.setItem("tz", sel.value); render(); });
  $("#sync-btn").addEventListener("click", () => { Tymex.clearCache(); state.status = null; render(); });
  window.addEventListener("hashchange", () => { if (!document.body.classList.contains("logged-out")) render(); });
  // Không gọi Supabase ngay trong callback này (sẽ kẹt khóa đăng nhập → trang treo ở "Đang tải"); chỉ phản ứng khi thật sự đăng nhập/đăng xuất.
  Tymex.auth.onChange((session, event) => {
    if (!started || event === "INITIAL_SESSION" || event === "TOKEN_REFRESHED" || event === "USER_UPDATED") return;
    const loggedIn = !document.body.classList.contains("logged-out");
    if (!!session === loggedIn) return;
    setTimeout(() => enter(session), 0);
  });
  Tymex.auth.session().then((session) => { started = true; return enter(session); });
}
init();
