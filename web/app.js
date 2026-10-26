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
const state = { status: null, tz: localStorage.getItem("tz") || null, syncPoll: null, liveTimer: null, simTimer: null, currentRoute: null, lastNonMatchRoute: null };
/* Điều hướng theo ngữ cảnh: nhớ route gần nhất KHÔNG phải trang trận, vị trí cuộn của từng route và
   trạng thái trang Trực tiếp (bộ lọc giải, thẻ đang mở, cửa sổ "sắp diễn ra", ngày đang xem) trong
   sessionStorage — để nút "Quay lại" ở trang trận quay về đúng nơi người dùng vừa rời khỏi, thay vì
   phụ thuộc vào history.back() (ngăn xếp lịch sử của trình duyệt không phản ánh đúng tuyến trong ứng dụng:
   lần tải đầu/đăng nhập luôn dựng trang Tổng quan trong bộ nhớ mà không tạo mục lịch sử tương ứng, nên
   history.back() từ trang trận có thể rơi về mục nhập đầu tiên — tab Tổng quan — thay vì Trực tiếp). */
const NAV_LAST_ROUTE_KEY = "tymex:last-non-match-route";
const NAV_SCROLL_KEY = "tymex:route-scroll";
const LIVE_UI_KEY = "tymex:live-ui";
const storageGet = (key) => { try { return sessionStorage.getItem(key); } catch { return null; } };
const storageSet = (key, value) => { try { sessionStorage.setItem(key, value); } catch { /* bỏ qua */ } };
const storageJson = (key, fallback) => { try { const v = JSON.parse(storageGet(key) || "null"); return v ?? fallback; } catch { return fallback; } };
const scrollPositions = new Map(Object.entries(storageJson(NAV_SCROLL_KEY, {})));
function persistScrollPositions() { storageSet(NAV_SCROLL_KEY, JSON.stringify(Object.fromEntries(scrollPositions))); }
state.lastNonMatchRoute = storageGet(NAV_LAST_ROUTE_KEY) || "#/";
const ROUTE_LABELS = { dashboard: "Tổng quan", live: "Trực tiếp", schedule: "Lịch thi đấu", standings: "Bảng xếp hạng", teams: "Đội bóng", predictions: "Lịch sử dự đoán", settings: "Cài đặt" };
function routeNameOfHash(hash) {
  const seg = String(hash || "").replace(/^#\/?/, "").split(/[/?]/)[0];
  return seg === "" ? "dashboard" : seg;
}
function backLinkHtml() {
  const target = state.lastNonMatchRoute || storageGet(NAV_LAST_ROUTE_KEY) || "#/";
  const label = ROUTE_LABELS[routeNameOfHash(target)] || "trang trước";
  return `<p><a class="muted" href="${esc(target)}">‹ Quay lại ${esc(label)}</a></p>`;
}

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
const canonicalHash = () => {
  const raw = location.hash.replace(/^#/, "") || "/";
  return "#" + (raw.startsWith("/") ? raw : "/" + raw);
};
const ROUTES = {
  "": ["dashboard", pageDashboard], schedule: ["schedule", pageSchedule], match: ["match", pageMatch], live: ["live", pageLive],
  standings: ["standings", pageStandings], outrights: ["outrights", pageOutrights], teams: ["teams", pageTeams], predictions: ["predictions", pageHistory], settings: ["settings", pageSettings],
};
async function render() {
  if (state.liveTimer) { clearInterval(state.liveTimer); state.liveTimer = null; }
  if (state.simTimer) { clearInterval(state.simTimer); state.simTimer = null; liveState.sim = null; }
  // Lưu vị trí cuộn của route đang rời khỏi trước khi nội dung bị thay.
  if (state.currentRoute) {
    scrollPositions.set(state.currentRoute, window.scrollY || 0);
    persistScrollPositions();
  }
  const { parts, params } = parseHash();
  const [name, fn] = ROUTES[parts[0] || ""] || ROUTES[""];
  const thisRoute = canonicalHash();
  state.currentRoute = thisRoute;
  if (name !== "match") {
    state.lastNonMatchRoute = thisRoute;
    storageSet(NAV_LAST_ROUTE_KEY, thisRoute);
  }
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  app.innerHTML = loading();
  let rendered = false;
  try {
    if (!state.status) await refreshStatus();
    await fn(parts, params);
    rendered = true;
  } catch (e) {
    app.innerHTML = errorBox(e);
    $("[data-retry]", app)?.addEventListener("click", render);
  }
  // Khôi phục vị trí cuộn đã lưu của route này (trang trận luôn mở từ đầu trang).
  const restoreY = rendered && name !== "match" ? (scrollPositions.get(thisRoute) || 0) : 0;
  requestAnimationFrame(() => window.scrollTo(0, restoreY));
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

/* ---------------------------------------------------------------- Trực tiếp (ESPN + quét toàn cầu TheSportsDB)
   Tỷ số/phút lấy trực tiếp từ ESPN ngay trong trình duyệt (không qua lần đồng bộ 3 giờ của Supabase);
   TheSportsDB bổ sung các giải ESPN không có (K League, V.League...) — mỗi thẻ ghi rõ nguồn của trận đó.
   Dự đoán trực tiếp và mô phỏng chạy bằng mô hình trong live.js (port từ app/prediction/live.py). */
const liveUiSaved = storageJson(LIVE_UI_KEY, {});
const liveState = {
  open: new Set(Array.isArray(liveUiSaved.open) ? liveUiSaved.open : []),
  sim: null,
  filter: liveUiSaved.filter || "",
  window: liveUiSaved.window || "today",
  viewDate: liveUiSaved.viewDate || "",
  current: new Map(), draw: null,
  possessionMini: new Map(),
};
function persistLiveUi() {
  storageSet(LIVE_UI_KEY, JSON.stringify({
    open: [...liveState.open], filter: liveState.filter,
    window: liveState.window, viewDate: liveState.viewDate,
  }));
}

const teamKeyLive = (name) => TymexLive.normTeam(name).replace(/\b(fc|cf|sc|afc|club|bk)\b/g, "").replace(/\s+/g, " ").trim();
const nameMatch = (a, b) => a && b && (a === b || (a.length >= 4 && b.includes(a)) || (b.length >= 4 && a.includes(b)));
function findStoredPrediction(ev, preds) {
  const hk = teamKeyLive(ev.home), ak = teamKeyLive(ev.away);
  const start = ev.startIso ? new Date(ev.startIso).getTime() : null;
  for (const p of preds || []) {
    const t = p.utc_date ? new Date(p.utc_date).getTime() : null;
    if (start && t && Math.abs(t - start) > 36 * 3600 * 1000) continue;
    const ph = teamKeyLive(p.home_name), pa = teamKeyLive(p.away_name);
    if (nameMatch(ph, hk) && nameMatch(pa, ak)) return { lh: Number(p.lambda_home), la: Number(p.lambda_away), swapped: false, pred: p };
    if (nameMatch(ph, ak) && nameMatch(pa, hk)) return { lh: Number(p.lambda_away), la: Number(p.lambda_home), swapped: true, pred: p };
  }
  return null;
}
function lambdasForLive(ev, preds) {
  const found = findStoredPrediction(ev, preds);
  if (found && found.lh > 0 && found.la > 0) return { ...found, source: "tymex" };
  const avg = (ev.slug && TymexLive.LEAGUE_AVG_LAMBDAS[ev.slug]) || TymexLive.DEFAULT_AVG_LAMBDAS;
  return { lh: avg.home, la: avg.away, source: "league_avg", pred: null, swapped: false };
}
const liveKey = (ev) => `${ev.source}-${ev.slug || "x"}-${ev.eventId}`.replace(/[^a-zA-Z0-9-]/g, "-");

function probStrip(pc, homeName, awayName, idPrefix = "") {
  return `<div class="pstrip" ${idPrefix ? `id="${idPrefix}"` : ""} role="img" aria-label="Xác suất: chủ nhà ${pc.home}%, hòa ${pc.draw}%, khách ${pc.away}%">
    <div class="h" style="width:${pc.home}%">${pct(pc.home)}%</div><div class="d" style="width:${pc.draw}%">${pct(pc.draw)}%</div><div class="a" style="width:${pc.away}%">${pct(pc.away)}%</div></div>
  <div class="plabels"><span>${esc(homeName)} thắng</span><span>Hòa</span><span>${esc(awayName)} thắng</span></div>`;
}
function probChartSvg(points, homeName) {
  if (!points || points.length < 2) return "";
  const W = 340, H = 88, PAD = 8;
  const X = (m) => PAD + (m / TymexLive.FULL_MINUTES) * (W - 2 * PAD);
  const Y = (p) => H - PAD - p * (H - 2 * PAD);
  const line = points.map((pt) => `${X(pt.minute).toFixed(1)},${Y(pt.p_home).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return `<svg class="prob-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Biến động xác suất thắng của ${esc(homeName)}">
    <line x1="${PAD}" y1="${Y(0.5)}" x2="${W - PAD}" y2="${Y(0.5)}" class="grid"></line>
    <polyline points="${line}"></polyline>
    <circle cx="${X(last.minute)}" cy="${Y(last.p_home)}" r="3.2"></circle></svg>
  <div class="plabels"><span>Phút 0</span><span>Xác suất ${esc(homeName)} thắng: <b>${pct(last.p_home * 100, 0)}%</b></span><span>Phút ${last.minute}</span></div>`;
}
/* ---- khối "Nhận định dự đoán": kết quả & tỉ số, tài/xỉu bàn thắng, tài/xỉu phạt góc ----
   Số liệu bàn thắng/1X2 tính bằng mô hình trong live.js (port của markets.py, cùng ngưỡng Mạnh/Khá);
   phạt góc nạp LƯỜI từ ESPN (tỷ lệ góc gần nhất của giải) — không đủ dữ liệu thì nói rõ, không bịa số. */
const fmtProb = (p) => pct(p * 100, 0) + "%";
const fmtLn = (x) => Number(x).toFixed(1).replace(".", ",");
function pickChip(p) {
  const cls = p.strength === "Mạnh" ? "strong" : p.strength === "Khá" ? "ok" : "consider";
  return `<span class="pick-chip ${cls}">${esc(p.selection)} · ${fmtProb(p.probability)} · ${esc(p.strength)}</span>`;
}
function picksChips(picks) {
  if (!picks || !picks.length) return `<p class="small muted">Không có lựa chọn nào đạt xác suất 50%.</p>`;
  return `<div class="pick-chips">${picks.map(pickChip).join("")}</div>`;
}
function ouPickFromPicks(picks) {
  const p = (picks || []).find((x) => x.market === "goals_ou" || x.market === "corners_ou");
  if (!p) return null;
  const m = /(\d+)[.,](\d+)/.exec(p.selection || "");
  return { line: m ? Number(m[1] + "." + m[2]) : null, side: (p.selection || "").startsWith("Tài") ? "Tài" : "Xỉu" };
}
function linesHtml(lines, subset, ouPick, unit) {
  const rows = (lines || []).filter((l) => subset.includes(l.line)).map((l) => {
    const rec = ouPick && ouPick.line !== null && Math.abs(ouPick.line - l.line) < 1e-9 ? ouPick.side : null;
    return `<div class="ln-row"><span class="ln-line">${fmtLn(l.line)} ${unit}</span>
      <span class="ln-side ${rec === "Tài" ? "rec" : ""}">Tài ${fmtProb(l.over)}${rec === "Tài" ? " ★" : ""}</span>
      <span class="ln-side ${rec === "Xỉu" ? "rec" : ""}">Xỉu ${fmtProb(l.under)}${rec === "Xỉu" ? " ★" : ""}</span></div>`;
  }).join("");
  return `<div class="ln-table">${rows}</div>`;
}
const verdictClock = () => new Date().toLocaleTimeString("vi-VN", { timeZone: tz(), hour: "2-digit", minute: "2-digit", hour12: false });
function touchVerdictTime(fromEl) {
  const el = fromEl?.closest?.(".verdict")?.querySelector("[data-verdict-time]");
  if (el) el.textContent = `Nhận định cập nhật lúc ${verdictClock()}`;
}
function lineupEligible(ev) {
  if (!ev || ev.source !== "ESPN" || !ev.slug || ev.state !== "pre" || !ev.startIso) return false;
  const diff = new Date(ev.startIso).getTime() - Date.now();
  return diff <= 2 * 3600 * 1000 && diff > -30 * 60 * 1000;
}
function lineupInfoHtml(info, ev) {
  if (!info) return "";
  if (info.status === "available") {
    const adj = info.adjustment;
    const missingNames = [...(adj.homeMissing || []), ...(adj.awayMissing || [])]
      .map((p) => `${esc(p.name)} (${esc(TymexLive.LINEUP_GROUP_LABEL?.[p.positionGroup] || p.positionGroup || "chưa rõ vị trí")})`).join(", ");
    return `<div class="vd-sec lineup-box"><span class="lineup-badge">Đã tính đội hình xuất phát</span>
      <p class="small">λ sau đội hình: <b class="num">${num(adj.lambdaHome)} - ${num(adj.lambdaAway)}</b> <span class="muted">(trước đó ${num(adj.lambdaHomeBefore)} - ${num(adj.lambdaAwayBefore)})</span>${missingNames ? ` · Thiếu trụ cột: ${missingNames}` : ""}</p>
      ${(adj.explanations || []).map((x) => `<p class="small muted">${esc(x)}</p>`).join("")}
      <p class="small muted">Mô hình phạt góc chưa dùng yếu tố đội hình — phần phạt góc ở dưới giữ nguyên.</p></div>`;
  }
  if (info.status === "unpublished") {
    return `<p class="small muted">Đội hình xuất phát chưa công bố — nhận định sẽ tự cập nhật khi có (thường ~60 phút trước giờ đá).</p>`;
  }
  return `<p class="small muted">Chưa đối chiếu được đội hình xuất phát với trận gần nhất — nhận định giữ nguyên theo λ hiện tại.</p>`;
}
function verdictHtml(ev, L, key, lineupInfo = null) {
  const isLive = ev.state === "in" && ev.minute !== null && ev.homeScore !== null;
  const v = isLive
    ? TymexLive.buildVerdict(L.lh, L.la, { homeName: ev.home, awayName: ev.away, live: { minute: ev.minute, homeScore: ev.homeScore, awayScore: ev.awayScore, homeRed: (ev.reds || {}).home || 0, awayRed: (ev.reds || {}).away || 0 } })
    : TymexLive.buildVerdict(L.lh, L.la, { homeName: ev.home, awayName: ev.away });
  const lineupBlock = lineupInfo ? lineupInfoHtml(lineupInfo, ev)
    : (!isLive && lineupEligible(ev) ? `<div id="lu-${key}" data-lineups="${key}"><p class="small muted">Đang kiểm tra đội hình xuất phát…</p></div>` : "");
  return `<div class="verdict" data-verdict="${key}" id="vd-${key}">
    <div class="vd-title">Nhận định dự đoán${isLive ? " — cập nhật trực tiếp" : ""}</div>
    <div class="vd-updated" data-verdict-time>Nhận định cập nhật lúc ${esc(verdictClock())}</div>
    ${lineupBlock}
    <div class="vd-sec"><div class="vd-h">Kết quả & tỉ số</div>
      ${isLive ? "" : probStrip(v.percent, ev.home, ev.away)}
      <p class="small">${isLive ? "Tỉ số chung cuộc dự đoán" : "Tỉ số dự đoán"}: <b class="num">${v.score.home}-${v.score.away}</b> <span class="muted">(xác suất đúng chính xác ${fmtProb(v.score.prob)} — luôn thấp, chỉ để tham khảo)</span></p>
      ${picksChips(v.picks)}
      ${v.fallback ? `<p class="small muted">Chưa có lựa chọn nào đủ mạnh theo ngưỡng của mô hình (cần ≥ 57%); lựa chọn "Cân nhắc" ở trên là lựa chọn tốt nhất hiện có.</p>` : ""}
    </div>
    <div class="vd-sec"><div class="vd-h">Tài/Xỉu bàn thắng${isLive ? " (tổng bàn cuối trận, đã gồm tỉ số hiện tại)" : ""}</div>
      ${linesHtml(v.markets.lines, [1.5, 2.5, 3.5], ouPickFromPicks(v.picks), "bàn")}
      <p class="small muted">Tổng bàn kỳ vọng: <b class="num">${num(v.markets.expected_total_goals)}</b></p>
    </div>
    <div class="vd-sec"><div class="vd-h">Tài/Xỉu phạt góc</div>
      <div id="lc-${key}" data-corners="${key}"><p class="small muted">Đang tính phạt góc từ các trận gần nhất của giải…</p></div>
    </div>
    <p class="vd-note">${esc(TymexLive.VERDICT_DISCLAIMER)}</p>
  </div>`;
}
async function fillCorners(key) {
  const item = liveState.current.get(key);
  let box = $(`#lc-${CSS.escape(key)}`);
  if (!box || !item) return;
  const { ev } = item;
  const noData = (extra = "") => { box.innerHTML = `<p class="small muted">Chưa đủ dữ liệu phạt góc từ ESPN cho trận này${extra}.</p>`; };
  if (ev.source !== "ESPN" || !ev.slug) { noData(); return; }
  let rows;
  try { rows = await TymexLive.fetchLeagueCornerRows(ev.slug); } catch (e) { noData(); return; }
  box = $(`#lc-${CSS.escape(key)}`);
  if (!box) return;   // trang đã vẽ lại trong lúc chờ
  const est = TymexLive.estimateCorners(rows, ev.home, ev.away);
  if (!est.available) {
    const detail = est.homeGames !== undefined ? ` (có ${est.matches} trận của giải có số liệu góc; đội chủ nhà mới có ${est.homeGames} trận sân nhà, đội khách ${est.awayGames} trận sân khách có góc)` : ` (mới có ${est.matches} trận của giải có số liệu góc)`;
    noData(detail);
    return;
  }
  let lines = est.lines, pick = est.pick, liveHtml = "";
  if (ev.state === "in" && ev.minute !== null) {
    try {
      const sum = await TymexLive.fetchEspnSummary(ev.slug, ev.eventId);
      const ah = parseFloat(sum.stats.home.wonCorners), aa = parseFloat(sum.stats.away.wonCorners);
      if (!Number.isNaN(ah) && !Number.isNaN(aa)) {
        const remaining = Math.max(TymexLive.FULL_MINUTES - ev.minute, 0) / TymexLive.FULL_MINUTES;
        const projected = ah + aa + est.expected.total * remaining;
        lines = TymexLive.cornerLines(projected);
        pick = TymexLive.cornerPick(lines);
        liveHtml = `<p class="small">Góc thực tế tới phút ${ev.minute}': <b class="num">${ah} - ${aa}</b> (tổng ${ah + aa}) · Chiếu cuối trận (ước tính từ nhịp góc còn lại): <b class="num">~${num(projected, 1)}</b> góc — các mốc dưới đây tính theo số chiếu này.</p>`;
      }
    } catch (e) { /* không có thống kê trực tiếp: chỉ hiện dự đoán trước trận */ }
  }
  box.innerHTML = `${liveHtml}
    <p class="small">Góc kỳ vọng${ev.state === "in" ? " (trước trận)" : ""}: ${esc(ev.home)} <b class="num">${num(est.expected.home)}</b> · ${esc(ev.away)} <b class="num">${num(est.expected.away)}</b> · Tổng <b class="num">${num(est.expected.total)}</b></p>
    ${linesHtml(lines, [8.5, 9.5, 10.5, 11.5], pick ? { line: pick.line, side: pick.side } : null, "góc")}
    ${pick ? `<div class="pick-chips">${pickChip(pick)}</div>` : `<p class="small muted">Không có lựa chọn phạt góc nào đạt 50%.</p>`}
    <p class="small muted">Tính từ ${est.matches} trận gần nhất của giải trên ESPN; tỷ lệ góc của đội đã co về trung bình giải. football-data.org không có dữ liệu phạt góc.</p>`;
  touchVerdictTime(box);
}

/* ---- yếu tố ĐỘI HÌNH XUẤT PHÁT cho nhận định của trận sắp đá (chỉ ESPN, lười tải) ----
   Kết quả được cache trong bộ nhớ: đội hình đã công bố giữ 10 phút; "chưa công bố" chỉ giữ ~60 giây
   để lần làm mới sau kiểm tra lại, vì đội hình thường chỉ xuất hiện khoảng 60 phút trước giờ đá. */
const lineupCache = new Map();
async function computeLineupAdjustment(ev, L, currentSummary = null) {
  const cacheKey = liveKey(ev);
  const hit = lineupCache.get(cacheKey);
  if (hit && Date.now() - hit.t < 10 * 60 * 1000) return hit.promise;
  const promise = (async () => {
    const sum = currentSummary || await TymexLive.fetchEspnSummary(ev.slug, ev.eventId);
    const homeRoster = TymexLive.rosterForTeam(sum, { side: "home", name: ev.home, id: sum.teamIds?.home });
    const awayRoster = TymexLive.rosterForTeam(sum, { side: "away", name: ev.away, id: sum.teamIds?.away });
    const homeStarters = homeRoster ? homeRoster.players.filter((p) => p.starter) : [];
    const awayStarters = awayRoster ? awayRoster.players.filter((p) => p.starter) : [];
    if (!homeStarters.length || !awayStarters.length) return { status: "unpublished", summary: sum };
    const [prevHome, prevAway] = await Promise.all([
      TymexLive.fetchPreviousStartingXi(sum, "home", ev),
      TymexLive.fetchPreviousStartingXi(sum, "away", ev),
    ]);
    if (!prevHome || !prevAway) return { status: "insufficient", summary: sum };
    const missingHome = TymexLive.missingRegulars(homeRoster.players, prevHome);
    const missingAway = TymexLive.missingRegulars(awayRoster.players, prevAway);
    if (missingHome.status !== "available" || missingAway.status !== "available") return { status: "insufficient", summary: sum };
    const adjustment = TymexLive.adjustLambdas(L.lh, L.la, missingHome, missingAway);
    return { status: "available", adjustment, missing: { home: missingHome, away: missingAway }, summary: sum };
  })();
  const entry = { t: Date.now(), promise };
  lineupCache.set(cacheKey, entry);
  promise.then((info) => { if (info.status !== "available") entry.t = Date.now() - (10 * 60 * 1000 - 60 * 1000); }, () => { entry.t = 0; });
  return promise;
}
async function fillLineups(key, currentSummary = null) {
  const item = liveState.current.get(key);
  if (!item || !lineupEligible(item.ev)) return;
  const box = document.querySelector(`[data-lineups="${key}"]`);
  if (!box) return;
  let info;
  try { info = await computeLineupAdjustment(item.ev, item.L, currentSummary); }
  catch (e) { if (box.isConnected) box.innerHTML = lineupInfoHtml({ status: "insufficient" }, item.ev); return; }
  const current = liveState.current.get(key);
  const verdict = document.querySelector(`[data-verdict="${key}"]`);
  if (!current || !verdict) return;
  if (info.status !== "available") {
    if (box.isConnected) { box.innerHTML = lineupInfoHtml(info, current.ev); touchVerdictTime(box); }
    return;
  }
  const newL = { ...current.L, lh: info.adjustment.lambdaHome, la: info.adjustment.lambdaAway, lineupAdjustment: info.adjustment };
  current.L = newL;
  verdict.outerHTML = verdictHtml(current.ev, newL, key, info);
  fillCorners(key);
}

function countdownLabel(ev, nowMs = Date.now()) {
  if (!ev || !ev.startIso) return "";
  const diff = new Date(ev.startIso).getTime() - nowMs;
  if (!Number.isFinite(diff) || diff <= 0) return "";
  const totalMinutes = Math.floor(diff / 60000);
  if (totalMinutes < 1) return "còn chưa đầy 1 phút";
  if (totalMinutes < 60) return `còn ${totalMinutes} phút`;
  const hours = Math.floor(totalMinutes / 60), minutes = totalMinutes % 60;
  return minutes ? `còn ${hours} giờ ${minutes} phút` : `còn ${hours} giờ`;
}
function liveCard(ev, preds) {
  const L = lambdasForLive(ev, preds);
  const key = liveKey(ev);
  liveState.current.set(key, { ev, L });
  const isLive = ev.state === "in", isPost = ev.state === "post";
  const clock = isLive ? `<span class="live-badge"><span class="live-dot"></span>LIVE ${esc(ev.halftime ? "Nghỉ giữa hiệp" : ev.clockLabel || (ev.minute !== null ? ev.minute + "'" : ""))}</span>`
    : isPost ? `<span class="status done">Kết thúc</span>`
    : `<span class="status">Sắp đá${ev.startIso ? " · " + esc(fmtTime(ev.startIso)) : ""}${countdownLabel(ev) ? ` · ${esc(countdownLabel(ev))}` : ""}</span>`;
  const scorers = (ev.goals || []).length
    ? `<div class="scorers">${ev.goals.map((g) => `<span>${g.minute}' ${esc(g.scorer || "Bàn thắng")} (${esc(g.side === "home" ? ev.home : ev.away)})</span>`).join("")}</div>` : "";
  let predHtml = "";
  if (isLive && ev.homeScore !== null && ev.minute !== null) {
    const lp = TymexLive.predictLive(L.lh, L.la, ev.minute, ev.homeScore, ev.awayScore, (ev.reds || {}).home || 0, (ev.reds || {}).away || 0);
    predHtml = `<div class="live-pred"><div class="live-pred-title">Dự đoán trực tiếp của Tymex</div>${probStrip(lp.percent, ev.home, ev.away)}
      <p class="small">Tỷ số chung cuộc khả thi nhất: <b class="num">${lp.predicted_final_score.home}-${lp.predicted_final_score.away}</b> (${pct(lp.predicted_final_score.prob * 100)}%) · Kỳ vọng chung cuộc: <b class="num">${num(lp.expected_final.home)}-${num(lp.expected_final.away)}</b><br>
      Bàn thắng tiếp theo: ${esc(ev.home)} ${pct(lp.next_goal.home * 100, 0)}% · Không thêm bàn ${pct(lp.next_goal.none * 100, 0)}% · ${esc(ev.away)} ${pct(lp.next_goal.away * 100, 0)}%</p></div>`;
  }
  const lambdaNote = L.source === "tymex"
    ? `<span class="tag-src tag-tymex">λ theo dự đoán trước trận của Tymex (λ ${num(L.lh)} - ${num(L.la)})</span>`
    : `<span class="tag-src">λ ước tính theo trung bình giải — chưa có dự đoán Tymex cho trận này (λ ${num(L.lh)} - ${num(L.la)})</span>`;
  return `<article class="live-card">
    <div class="live-top"><span class="league-name">${esc(ev.league)}</span>${clock}<span class="src-note">Nguồn: ${esc(ev.source)}</span></div>
    <div class="live-main">
      <div class="vteam home">${crest(ev.homeLogo, ev.home)}<span class="name">${esc(ev.home)}</span></div>
      <div class="vscore">${ev.homeScore !== null ? `${ev.homeScore} - ${ev.awayScore}` : "—"}</div>
      <div class="vteam away">${crest(ev.awayLogo, ev.away)}<span class="name">${esc(ev.away)}</span></div>
    </div>
    ${scorers}${predHtml}
    ${liveState.possessionMini.has(key) ? possessionMiniHtml(ev, liveState.possessionMini.get(key)) : ""}
    ${ev.state === "post" ? "" : verdictHtml(ev, L, key)}
    <div class="live-actions">${lambdaNote}
      ${ev.source === "ESPN" ? `<button class="btn btn-small" data-expand="${key}">${liveState.open.has(key) ? "Ẩn thống kê" : "Thống kê & diễn biến"}</button>` : ""}
      <button class="btn btn-small" data-sim="${key}">▶ Mô phỏng</button>
    </div>
    <div class="live-detail" id="ld-${key}" ${liveState.open.has(key) ? "" : "hidden"}></div>
  </article>`;
}

/* ---- thống kê chi tiết + dòng sự kiện (ESPN summary; chỉ vẽ số liệu nguồn thật sự trả về) ---- */
function comparativeStats(sum) {
  const rows = TymexLive.STAT_DEFS
    .filter(([name]) => name !== "possessionPct" && (sum.stats.home[name] !== undefined || sum.stats.away[name] !== undefined))
    .map(([name, label]) => {
      const h = sum.stats.home[name], a = sum.stats.away[name];
      const hv = parseFloat(h), av = parseFloat(a);
      const share = !Number.isNaN(hv) && !Number.isNaN(av) && hv + av > 0 ? (hv / (hv + av)) * 100 : 50;
      return `<div class="stat-row"><span class="sv ${hv > av ? "bold" : ""}">${esc(h ?? "—")}</span>
        <div class="stat-mid"><div class="stat-label">${esc(label)}</div>
        <div class="sbar"><div class="sb-h" style="width:${share}%"></div><div class="sb-a" style="width:${100 - share}%"></div></div></div>
        <span class="sv r ${av > hv ? "bold" : ""}">${esc(a ?? "—")}</span></div>`;
    }).join("");
  if (!rows) return "";
  const xh = TymexLive.xgProxyFromShots(sum.stats.home), xa = TymexLive.xgProxyFromShots(sum.stats.away);
  const xg = xh !== null && xa !== null
    ? `<div class="facts"><div class="fact-box"><div class="v">${num(xh)} - ${num(xa)}</div><div class="l">xG ước tính từ cú sút (mô hình Tymex: sút trúng đích × 0,32 + sút còn lại × 0,03) — KHÔNG phải xG chính thức của nguồn dữ liệu</div></div></div>` : "";
  return `<h3>Thống kê trận đấu (ESPN)</h3>${xg}<div class="stats">${rows}</div>`;
}
function eventKindLabel(type, scoring) {
  const t = String(type || "").toLowerCase();
  if (scoring || t.includes("goal")) return "Bàn thắng";
  if (t.includes("red")) return "Thẻ đỏ";
  if (t.includes("yellow")) return "Thẻ vàng";
  if (t.includes("substitution")) return "Thay người";
  if (t.includes("halftime")) return "Hết hiệp 1";
  if (t.includes("full")) return "Hết giờ";
  if (t.includes("kickoff") || t.includes("start")) return "Bắt đầu";
  if (t.includes("penalty")) return "Phạt đền";
  if (t.includes("var")) return "VAR";
  return type || "Sự kiện";
}
function eventsTimeline(sum, ev) {
  if (!sum.keyEvents.length) return "";
  return `<h3 style="margin-top:1rem">Diễn biến trận đấu (ESPN)</h3><ul class="evt-list">${sum.keyEvents.map((e) =>
    `<li><span class="evt-min">${esc(e.clockLabel || e.minute + "'")}</span><span class="evt-kind ${e.scoringPlay ? "goal" : ""}">${esc(eventKindLabel(e.type, e.scoringPlay))}</span><span class="evt-text">${esc(e.text)}${e.side ? ` <span class="muted">(${esc(e.side === "home" ? ev.home : ev.away)})</span>` : ""}</span></li>`).join("")}</ul>`;
}
/* ---- KIỂM SOÁT BÓNG ----
   ESPN chỉ cho % lũy kế tại thời điểm gọi API, KHÔNG có lịch sử theo phút. Biểu đồ theo thời gian vì vậy
   chỉ vẽ từ các mẫu máy chủ Tymex tự ghi mỗi ~1–2 phút (GitHub Actions chạy vòng lặp 52 phút mỗi giờ,
   chu kỳ mục tiêu 90 giây → Supabase kv "possession:<id>"). Không có mẫu trung tâm thì chỉ hiện thanh %
   hiện tại/tỉ số cuối + một dòng ghi rõ — tuyệt đối không tự suy diễn hay lấp đầy các phút trước đó. */
function possessionValues(sum) {
  if (!sum || !sum.stats) return null;
  const h = parseFloat(sum.stats.home.possessionPct), a = parseFloat(sum.stats.away.possessionPct);
  if (Number.isNaN(h) || Number.isNaN(a) || h + a <= 0) return null;
  return { home: Math.round(h * 10) / 10, away: Math.round(a * 10) / 10 };
}
function possessionBarHtml(ev, poss, title = "Kiểm soát bóng") {
  if (!poss) return "";
  const homePct = Math.max(0, Math.min(100, poss.home));
  return `<div class="poss-block"><div class="poss-head"><span>${esc(title)}</span><span class="muted">lũy kế tới hiện tại</span></div>
    <div class="poss-labels"><span><b class="num">${pct(poss.home, 1)}%</b> ${esc(ev.home)}</span><span>${esc(ev.away)} <b class="num">${pct(poss.away, 1)}%</b></span></div>
    <div class="poss-bar" role="img" aria-label="Kiểm soát bóng ${esc(ev.home)} ${pct(poss.home, 1)}%, ${esc(ev.away)} ${pct(poss.away, 1)}%"><div class="poss-home" style="width:${homePct}%"></div><div class="poss-away" style="width:${100 - homePct}%"></div></div></div>`;
}
function possessionMiniHtml(ev, poss) {
  if (!poss) return "";
  const homePct = Math.max(0, Math.min(100, poss.home));
  return `<div class="poss-mini" title="Kiểm soát bóng"><span>${esc(ev.home)} <b class="num">${pct(poss.home, 1)}%</b></span><div class="poss-bar mini"><div class="poss-home" style="width:${homePct}%"></div><div class="poss-away" style="width:${100 - homePct}%"></div></div><span><b class="num">${pct(poss.away, 1)}%</b> ${esc(ev.away)}</span></div>`;
}
const possessionSeriesCache = new Map();
async function fetchCentralPossession(ev) {
  if (!ev || ev.source !== "ESPN" || !ev.eventId) return null;
  const cacheKey = String(ev.eventId);
  const hit = possessionSeriesCache.get(cacheKey);
  if (hit && Date.now() - hit.t < 60 * 1000) return hit.payload;
  let payload = null;
  try {
    const data = await window.TymexData.kv(`possession:${cacheKey}`);
    if (data && Array.isArray(data.samples)) payload = data;
  } catch (e) { payload = null; }
  possessionSeriesCache.set(cacheKey, { t: Date.now(), payload });
  return payload;
}
function possessionChartHtml(ev, payload) {
  const samples = ((payload && payload.samples) || [])
    .filter((s) => Number.isFinite(parseFloat(s.possession_home_pct)))
    .map((s) => ({ minute: s.minute === null || s.minute === undefined || s.minute === "" ? null : Number(s.minute),
      clock: s.clock || "", homePct: parseFloat(s.possession_home_pct), ts: s.ts_utc || "" }))
    .sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  if (!samples.length) {
    return `<p class="muted small">Chưa có mẫu theo thời gian cho trận này.</p>`;
  }
  if (samples.length < 2) {
    return `<p class="muted small">Mới ghi được 1 mẫu kiểm soát bóng — biểu đồ sẽ hiện khi hệ thống ghi thêm mẫu trong lúc trận đấu diễn ra.</p>`;
  }
  const W = 640, H = 180, padL = 34, padR = 10, padT = 12, padB = 24;
  const hasAllMinutes = samples.every((s) => Number.isFinite(s.minute));
  // Thiếu phút trận ở bất kỳ mẫu nào thì dùng thứ tự mẫu với khoảng danh nghĩa 1,5 phút (chu kỳ ghi mẫu),
  // thay vì bịa phút trận. Nhãn đầu/cuối khi đó lấy đồng hồ trận hoặc giờ ghi mẫu, không ghi phút giả.
  const minutes = hasAllMinutes ? samples.map((s) => s.minute) : samples.map((_, i) => i * 1.5);
  const maxMinute = Math.max(hasAllMinutes ? 45 : 10, ...minutes);
  const x = (m) => padL + (Math.max(0, Math.min(maxMinute, m)) / maxMinute) * (W - padL - padR);
  const y = (p) => padT + (1 - Math.max(0, Math.min(100, p)) / 100) * (H - padT - padB);
  const pts = samples.map((s, i) => [x(minutes[i]), y(s.homePct)]);
  // Đường BẬC THANG: giữ nguyên % lũy kế của mẫu trước cho tới đúng thời điểm mẫu kế tiếp; các chấm là mẫu thật.
  let line = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) line += ` L${pts[i][0].toFixed(1)},${pts[i - 1][1].toFixed(1)} L${pts[i][0].toFixed(1)},${pts[i][1].toFixed(1)}`;
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${y(0).toFixed(1)} L${pts[0][0].toFixed(1)},${y(0).toFixed(1)} Z`;
  const grid = [0, 50, 100].map((p) => `<line x1="${padL}" y1="${y(p)}" x2="${W - padR}" y2="${y(p)}" class="poss-grid"/><text x="4" y="${y(p) + 4}" class="poss-axis">${p}%</text>`).join("");
  const sampleLabel = (s, i) => s.clock || (hasAllMinutes ? `${minutes[i]}'` : (s.ts ? `${String(s.ts).slice(11, 16)} UTC` : `Mẫu ${i + 1}`));
  const dots = pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="3" class="poss-dot"><title>${esc(sampleLabel(samples[i], i))}: ${esc(ev.home)} ${pct(samples[i].homePct, 1)}%</title></circle>`).join("");
  const firstLabel = sampleLabel(samples[0], 0), lastLabel = sampleLabel(samples[samples.length - 1], samples.length - 1);
  return `<div class="poss-chart"><div class="poss-head"><span>Kiểm soát bóng theo thời gian</span><span class="muted">${esc(ev.home)} (%)</span></div>
    <svg viewBox="0 0 ${W} ${H}" class="poss-svg" role="img" aria-label="Biểu đồ kiểm soát bóng của ${esc(ev.home)} theo thời gian">${grid}<line x1="${padL}" y1="${y(50)}" x2="${W - padR}" y2="${y(50)}" class="poss-mid"/><path d="${area}" class="poss-area"/><path d="${line}" class="poss-line"/>${dots}<text x="${padL}" y="${H - 6}" class="poss-axis">${esc(firstLabel)}</text><text x="${W - padR - 44}" y="${H - 6}" class="poss-axis">${esc(lastLabel)}</text></svg>
    <p class="muted small">Hệ thống Tymex tự ghi mẫu mỗi ~1–2 phút từ ESPN — không cần mở trang. Các chấm là mẫu thật; đường bậc thang giữ giá trị lũy kế của mẫu trước tới mẫu kế tiếp, không phải dữ liệu từng phút. Có thể khuyết vài phút quanh thời điểm chuyển ca mỗi giờ.</p></div>`;
}
async function fillPossessionChart(key) {
  const item = liveState.current.get(key);
  const box = document.querySelector(`[data-possession-chart="${key}"]`);
  if (!item || !box) return;
  const payload = await fetchCentralPossession(item.ev);
  if (!box.isConnected) return;
  box.innerHTML = payload && (payload.samples || []).length
    ? possessionChartHtml(item.ev, payload)
    : `<p class="muted small">Chưa có mẫu theo thời gian cho trận này.</p>`;
}

async function fillLiveDetail(key) {
  const box = $(`#ld-${CSS.escape(key)}`);
  const item = liveState.current.get(key);
  if (!box || !item) return;
  const { ev, L } = item;
  box.innerHTML = loading("Đang tải thống kê…");
  const parts = [];
  const curMinute = ev.state === "post" ? TymexLive.FULL_MINUTES : ev.minute;
  if (curMinute !== null && curMinute !== undefined && (ev.goals || []).length) {
    const pts = TymexLive.probTimeline(L.lh, L.la, ev.goals, curMinute, (ev.reds || {}).home || 0, (ev.reds || {}).away || 0);
    if (pts.length >= 2) parts.push(`<h3>Biến động xác suất thắng</h3>${probChartSvg(pts, ev.home)}<p class="small muted">Đường xác suất do mô hình trực tiếp của Tymex tính lại tại từng thời điểm ghi bàn đã biết — đây là đầu ra của mô hình, không phải dữ liệu thế trận/cú sút thật.</p>`);
  }
  let sumRef = null;
  if (ev.source === "ESPN") {
    try {
      const sum = await TymexLive.fetchEspnSummary(ev.slug, ev.eventId);
      sumRef = sum;
      const poss = possessionValues(sum);
      if (poss) {
        liveState.possessionMini.set(key, poss);
        parts.push(possessionBarHtml(ev, poss, ev.state === "post" ? "Kiểm soát bóng chung cuộc" : "Kiểm soát bóng"));
      }
      parts.push(`<div data-possession-chart="${key}"><p class="muted small">Đang tải mẫu kiểm soát bóng theo thời gian…</p></div>`);
      parts.push(comparativeStats(sum) || `<div class="notice">ESPN không cung cấp thống kê chi tiết cho trận này.</div>`);
      parts.push(eventsTimeline(sum, ev));
    } catch (e) {
      parts.push(`<div class="notice warn">Không tải được thống kê chi tiết từ ESPN (${esc(e.message || e)}).</div>`);
      parts.push(`<div data-possession-chart="${key}"><p class="muted small">Đang tải mẫu kiểm soát bóng theo thời gian…</p></div>`);
    }
  } else {
    parts.push(`<div class="notice">Nguồn TheSportsDB chỉ cung cấp tỷ số trực tiếp, không có thống kê chi tiết cho trận này.</div>`);
    parts.push(`<p class="muted small">Chưa có mẫu theo thời gian cho trận này.</p>`);
  }
  if (ev.state === "post") {
    const v = TymexLive.buildVerdict(L.lh, L.la, { homeName: ev.home, awayName: ev.away });
    const ch = sumRef ? parseFloat(sumRef.stats.home.wonCorners) : NaN;
    const ca = sumRef ? parseFloat(sumRef.stats.away.wonCorners) : NaN;
    parts.push(`<h3 style="margin-top:1rem">Nhận định dự đoán (mô hình, TRƯỚC trận — để đối chiếu kết quả thật)</h3>
      <p class="small muted">Nhận định cập nhật lúc ${esc(verdictClock())}</p>
      <p class="small">Tỉ số dự đoán: <b class="num">${v.score.home}-${v.score.away}</b> · Tổng bàn kỳ vọng: <b class="num">${num(v.markets.expected_total_goals)}</b></p>
      ${picksChips(v.picks)}
      ${linesHtml(v.markets.lines, [1.5, 2.5, 3.5], ouPickFromPicks(v.picks), "bàn")}
      ${!Number.isNaN(ch) && !Number.isNaN(ca) ? `<p class="small">Phạt góc thực tế: <b class="num">${ch} - ${ca}</b> (tổng ${ch + ca}).</p>` : ""}
      <p class="vd-note">${esc(TymexLive.VERDICT_DISCLAIMER)}</p>`);
  }
  box.innerHTML = parts.join("") || `<div class="notice">Chưa có dữ liệu chi tiết cho trận này.</div>`;
  if (ev.source === "ESPN") fillPossessionChart(key);
  if (ev.state === "pre" && lineupEligible(ev)) fillLineups(key, sumRef);
}
async function toggleLiveDetail(key, btn) {
  const box = $(`#ld-${CSS.escape(key)}`);
  if (!box) return;
  if (liveState.open.has(key)) {
    liveState.open.delete(key); box.hidden = true; if (btn) btn.textContent = "Thống kê & diễn biến";
  } else {
    liveState.open.add(key); box.hidden = false; if (btn) btn.textContent = "Ẩn thống kê";
    await fillLiveDetail(key);
  }
  persistLiveUi();
}

/* ---- chế độ MÔ PHỎNG trực tiếp (diễn biến giả lập bằng mô hình, luôn gắn nhãn rõ) ---- */
function stopSimulation() {
  if (state.simTimer) { clearInterval(state.simTimer); state.simTimer = null; }
  liveState.sim = null;
}
function startSimulation(key) {
  const item = liveState.current.get(key);
  if (!item) return;
  const { ev, L } = item;
  const fromLive = ev.state === "in" && ev.homeScore !== null && ev.minute !== null;
  const sim = TymexLive.createSimulation(L.lh, L.la, {
    seed: Math.floor(Math.random() * 1e9),
    minute: fromLive ? ev.minute : 0, homeScore: fromLive ? ev.homeScore : 0, awayScore: fromLive ? ev.awayScore : 0,
    homeRed: (ev.reds || {}).home || 0, awayRed: (ev.reds || {}).away || 0,
  });
  liveState.sim = { sim, ev, L, playing: false, speed: 500 };
  renderSimPanel();
  setSimPlaying(true);
  $("#sim-holder")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderSimPanel() {
  const holder = $("#sim-holder"), S = liveState.sim;
  if (!holder || !S) return;
  const { sim, ev, L } = S, st = sim.state;
  holder.innerHTML = `<section class="block sim-panel">
    <div class="sim-banner">MÔ PHỎNG bằng mô hình — không phải diễn biến thật</div>
    <div class="row" style="justify-content:space-between"><h2>${esc(ev.home)} — ${esc(ev.away)}</h2>
      <span class="muted small">${esc(ev.league)} · λ ${num(L.lh)} - ${num(L.la)} (${L.source === "tymex" ? "dự đoán trước trận của Tymex" : "ước tính theo trung bình giải"})${st.minute > 0 && ev.state === "in" ? ` · mô phỏng tiếp từ phút ${st.minute}, tỷ số ${ev.homeScore}-${ev.awayScore}` : ""}</span></div>
    <div class="sim-score"><span class="sim-clock" id="sim-clock">${st.minute}'</span><b id="sim-score">${st.home} - ${st.away}</b></div>
    <div id="sim-strip">${probStrip(st.probs.percent, ev.home, ev.away)}</div>
    <div id="sim-chart">${probChartSvg(st.history, ev.home)}</div>
    <div class="row sim-controls">
      <button class="btn btn-accent" id="sim-play" type="button">⏸ Tạm dừng</button>
      <label class="small">Tốc độ <select id="sim-speed">
        <option value="250">Nhanh · 0,25 giây/phút</option><option value="500" selected>Vừa · 0,5 giây/phút</option><option value="1000">Chậm · 1 giây/phút</option>
      </select></label>
      <button class="btn" id="sim-restart" type="button">↺ Mô phỏng lại</button>
      <button class="btn" id="sim-close" type="button">Đóng</button>
    </div>
    <ul class="evt-list" id="sim-feed"></ul>
  </section>`;
  $("#sim-play").addEventListener("click", () => setSimPlaying(!S.playing));
  $("#sim-speed").addEventListener("change", (e) => { S.speed = Number(e.target.value); if (S.playing) setSimPlaying(true); });
  $("#sim-restart").addEventListener("click", () => {
    const key = [...liveState.current.entries()].find(([, v]) => v.ev === S.ev)?.[0];
    if (key) startSimulation(key);
  });
  $("#sim-close").addEventListener("click", () => { stopSimulation(); holder.innerHTML = ""; });
}
function setSimPlaying(play) {
  const S = liveState.sim;
  if (!S) return;
  if (state.simTimer) { clearInterval(state.simTimer); state.simTimer = null; }
  S.playing = play && !S.sim.state.done;
  const btn = $("#sim-play");
  if (btn) btn.textContent = S.sim.state.done ? "Đã hết giờ (mô phỏng)" : S.playing ? "⏸ Tạm dừng" : "▶ Chạy tiếp";
  if (!S.playing) return;
  state.simTimer = setInterval(simTick, S.speed);
}
function simTick() {
  const S = liveState.sim;
  if (!S) { if (state.simTimer) clearInterval(state.simTimer); return; }
  const evs = S.sim.step();
  const st = S.sim.state;
  const clock = $("#sim-clock"), score = $("#sim-score"), strip = $("#sim-strip"), chart = $("#sim-chart"), feed = $("#sim-feed");
  if (!clock || !score) { stopSimulation(); return; }
  clock.textContent = `${st.minute}'`;
  score.textContent = `${st.home} - ${st.away}`;
  if (strip) strip.innerHTML = probStrip(st.probs.percent, S.ev.home, S.ev.away);
  if (chart) chart.innerHTML = probChartSvg(st.history, S.ev.home);
  if (feed) evs.forEach((e) => {
    const li = document.createElement("li");
    li.innerHTML = e.type === "goal"
      ? `<span class="evt-min">${e.minute}'</span><span class="evt-kind goal">Bàn thắng (mô phỏng)</span><span class="evt-text">${esc(e.side === "home" ? S.ev.home : S.ev.away)} ghi bàn — tỷ số mô phỏng ${e.home}-${e.away}</span>`
      : `<span class="evt-min">${e.minute}'</span><span class="evt-kind">Cơ hội (mô phỏng)</span><span class="evt-text">${esc(e.side === "home" ? S.ev.home : S.ev.away)} có cơ hội nguy hiểm nhưng không thành bàn</span>`;
    feed.prepend(li);
  });
  if (st.done) setSimPlaying(false);
}

/* ---- trang Trực tiếp ---- */
function liveFilterOptions(events) {
  const groups = TymexLive.LEAGUE_GROUPS.map((g) =>
    `<optgroup label="${esc(g.region)}">${g.leagues.map((l) => `<option value="${esc(l.slug)}" ${liveState.filter === l.slug ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</optgroup>`).join("");
  const extra = [...new Set(events.filter((e) => !e.slug).map((e) => e.league))];
  const extraOpts = extra.length ? `<optgroup label="Giải khác (quét toàn cầu TheSportsDB)">${extra.map((n) => `<option value="tsdb:${esc(n)}" ${liveState.filter === "tsdb:" + n ? "selected" : ""}>${esc(n)}</option>`).join("")}</optgroup>` : "";
  return `<option value="" ${!liveState.filter ? "selected" : ""}>Tất cả các giải</option>${groups}${extraOpts}`;
}
const liveEventMatchesFilter = (ev) => !liveState.filter
  || (liveState.filter.startsWith("tsdb:") ? ev.source === "TheSportsDB" && ev.league === liveState.filter.slice(5) : ev.slug === liveState.filter);
const LIVE_WINDOWS = [
  { id: "1h", label: "1 giờ", hours: 1 },
  { id: "3h", label: "3 giờ", hours: 3 },
  { id: "6h", label: "6 giờ", hours: 6 },
  { id: "12h", label: "12 giờ", hours: 12 },
  { id: "today", label: "Hôm nay", hours: null },
];
function liveWindowById(id) { return LIVE_WINDOWS.find((w) => w.id === id) || LIVE_WINDOWS[LIVE_WINDOWS.length - 1]; }
function upcomingInWindow(ev, windowId, nowMs = Date.now()) {
  if (!ev || ev.state !== "pre" || !ev.startIso) return false;
  const start = new Date(ev.startIso).getTime();
  if (!Number.isFinite(start)) return false;
  const win = liveWindowById(windowId);
  if (win.hours === null) return dayKey(ev.startIso) === dayKey(new Date(nowMs).toISOString());
  return start >= nowMs && start <= nowMs + win.hours * 3600 * 1000;
}
function liveWindowChipsHtml() {
  const active = liveWindowById(liveState.window).id;
  return LIVE_WINDOWS.map((w) => `<button type="button" class="window-chip ${w.id === active ? "on" : ""}" data-window="${w.id}" aria-pressed="${w.id === active}">${w.label}</button>`).join("");
}
async function pageLive() {
  app.innerHTML = `<div class="page-head"><h1>Trực tiếp</h1>
    <span class="muted small">Tỷ số lấy trực tiếp từ ESPN + quét toàn cầu TheSportsDB, tự làm mới mỗi 60 giây<span id="live-updated"></span></span></div>
  <div id="sim-holder"></div>
  <div class="filters"><select id="live-filter" aria-label="Lọc theo giải đấu"></select>
    <span class="muted small">Champions League (Cúp C1) và các giải ưu tiên làm mới mỗi 60 giây; giải còn lại tối đa 4 phút/lần.</span></div>
  <div class="filters live-tools">
    <label class="live-date-label">Xem trận theo ngày <input type="date" id="live-date" aria-label="Xem trận theo ngày" value="${esc(liveState.viewDate || "")}"></label>
    <button type="button" class="btn btn-small" id="live-date-today">Hôm nay</button>
    <span class="muted small" id="live-date-note">${liveState.viewDate ? "Đang xem lịch của ngày đã chọn." : "Chưa chọn ngày riêng — đang xem trực tiếp như thường lệ."}</span>
  </div>
  <div class="window-row" id="live-window-row"><span class="muted small">Sắp diễn ra trong:</span><div class="window-chips" id="live-window-chips">${liveWindowChipsHtml()}</div></div>
  <div id="live-holder">${loading("Đang tải tỷ số trực tiếp…")}</div>`;
  const draw = async (forceAll = false) => {
    const holder = $("#live-holder");
    if (!holder) return;
    let data, preds = [];
    const dateMode = !!liveState.viewDate;
    try {
      data = dateMode ? await TymexLive.fetchEventsForDate(liveState.viewDate, forceAll) : await TymexLive.fetchLiveEvents(forceAll);
    } catch (e) {
      holder.innerHTML = `<div class="notice error"><b>Không lấy được dữ liệu ${dateMode ? "cho ngày đã chọn" : "trực tiếp"}.</b><br>${esc(e.message || e)}<div style="margin-top:.6rem"><button class="btn btn-small" id="live-retry">Thử lại</button></div></div>`;
      $("#live-retry")?.addEventListener("click", () => draw(true));
      return;
    }
    try { preds = (await api("/predictions?kind=live&limit=500")).predictions || []; } catch { preds = []; }
    const sel = $("#live-filter");
    if (sel) sel.innerHTML = liveFilterOptions(data.events);
    const upd = $("#live-updated");
    if (upd) upd.textContent = ` · Cập nhật lúc ${new Date().toLocaleTimeString("vi-VN")}`;
    liveState.current = new Map();
    const evs = data.events.filter(liveEventMatchesFilter);
    const live = evs.filter((e) => e.state === "in");
    const upcomingAll = evs.filter((e) => e.state === "pre");
    const upcoming = upcomingAll.filter((e) => upcomingInWindow(e, liveState.window));
    const finished = evs.filter((e) => e.state === "post");
    const groupRender = (arr) => {
      const groups = new Map();
      arr.forEach((e) => { if (!groups.has(e.league)) groups.set(e.league, []); groups.get(e.league).push(e); });
      return [...groups].map(([league, ms]) => `<div class="league-group"><div class="league-name">${esc(league)}</div>${ms.map((e) => liveCard(e, preds)).join("")}</div>`).join("");
    };
    const windowRow = $("#live-window-row");
    if (windowRow) windowRow.hidden = dateMode;
    const chips = $("#live-window-chips");
    if (chips) chips.innerHTML = liveWindowChipsHtml();
    let html = "";
    if (dateMode) {
      const dateTitle = fmtDate(`${liveState.viewDate}T12:00:00Z`, true);
      html += `<section class="section"><h2>Trận ngày ${esc(dateTitle)}<span class="count">${evs.length ? evs.length + " trận" : ""}</span></h2>${evs.length ? groupRender(evs) : emptyBox("Không có trận nào trong dữ liệu ESPN/TheSportsDB cho ngày đã chọn và bộ lọc hiện tại.")}</section>`;
    } else {
      html += `<section class="section"><h2><span class="live-dot"></span>Đang diễn ra<span class="count">${live.length ? live.length + " trận" : ""}</span></h2>${live.length ? groupRender(live) : emptyBox("Hiện không có trận nào đang đá ở các giải chính")}</section>`;
      const win = liveWindowById(liveState.window);
      if (upcomingAll.length) {
        html += `<section class="section"><h2>Sắp diễn ra<span class="count">${upcoming.length ? upcoming.length + " trận" : ""}</span></h2>${upcoming.length ? groupRender(upcoming) : emptyBox(`Không có trận sắp đá nào trong khung “${win.label}”.`)}</section>`;
      }
      if (finished.length) html += `<section class="section"><h2>Kết quả hôm nay</h2>${groupRender(finished)}</section>`;
      if (!evs.length) html += emptyBox("Không có trận nào khớp bộ lọc giải đấu hiện tại.");
    }
    holder.innerHTML = html;
    holder.querySelectorAll("[data-expand]").forEach((b) => b.addEventListener("click", () => toggleLiveDetail(b.dataset.expand, b)));
    holder.querySelectorAll("[data-sim]").forEach((b) => b.addEventListener("click", () => startSimulation(b.dataset.sim)));
    holder.querySelectorAll("[data-corners]").forEach((el) => fillCorners(el.dataset.corners));
    holder.querySelectorAll("[data-lineups]").forEach((el) => fillLineups(el.dataset.lineups));
    for (const key of liveState.open) { if (liveState.current.has(key)) fillLiveDetail(key); }
  };
  liveState.draw = draw;
  $("#live-filter").addEventListener("change", (e) => { liveState.filter = e.target.value; persistLiveUi(); draw(true); });
  $("#live-date")?.addEventListener("change", (e) => {
    liveState.viewDate = e.target.value || "";
    persistLiveUi();
    const note = $("#live-date-note");
    if (note) note.textContent = liveState.viewDate ? "Đang xem lịch của ngày đã chọn." : "Chưa chọn ngày riêng — đang xem trực tiếp như thường lệ.";
    draw(false);
  });
  $("#live-date-today")?.addEventListener("click", () => {
    liveState.viewDate = "";
    const input = $("#live-date"); if (input) input.value = "";
    const note = $("#live-date-note"); if (note) note.textContent = "Chưa chọn ngày riêng — đang xem trực tiếp như thường lệ.";
    persistLiveUi();
    draw(false);
  });
  $("#live-window-chips")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-window]");
    if (!btn) return;
    liveState.window = liveWindowById(btn.dataset.window).id;
    persistLiveUi();
    draw(false);
  });
  await draw(false);
  state.liveTimer = setInterval(() => draw(false), 60000);
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

/* Khối "Nhận định dự đoán" trong trang trận đã đồng bộ: dùng verdict/markets từ payload nếu có
   (dự đoán lưu bằng mã mới); bản lưu cũ chưa có thì tính ngay từ λ đã lưu bằng mô hình trong live.js. */
function verdictSectionHtml(p, m) {
  let v = p.verdict, mk = p.markets, computedNote = "";
  if ((!v || !mk) && window.TymexLive && p.lambda_home && p.lambda_away) {
    const bv = TymexLive.buildVerdict(Number(p.lambda_home), Number(p.lambda_away), { homeName: m.home_name, awayName: m.away_name });
    v = v || { picks: bv.picks, score: bv.score, reasoning: [], disclaimer: bv.disclaimer };
    mk = mk || bv.markets;
    computedNote = `<p class="small muted">Bản dự đoán đã lưu chưa kèm khối nhận định — các lựa chọn dưới đây được tính ngay từ λ đã lưu của chính dự đoán này.</p>`;
  }
  if (!v || !mk) return "";
  const reasoning = (v.reasoning || []).length
    ? `<ul class="factors">${v.reasoning.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : "";
  return `<h3 style="margin-top:.8rem">Nhận định dự đoán</h3>${computedNote}
    <p class="small muted">Nhận định cập nhật lúc ${esc(verdictClock())}</p>
    <p class="small">Tỉ số dự đoán: <b class="num">${v.score.home}-${v.score.away}</b></p>
    ${picksChips(v.picks)}
    <div class="vd-h">Tài/Xỉu bàn thắng</div>
    ${linesHtml(mk.lines, [1.5, 2.5, 3.5], ouPickFromPicks(v.picks), "bàn")}
    <p class="small muted">Tổng bàn kỳ vọng: <b class="num">${num(mk.expected_total_goals)}</b> · Cơ hội kép: 1X ${fmtProb(mk.double_chance["1X"])} · 12 ${fmtProb(mk.double_chance["12"])} · X2 ${fmtProb(mk.double_chance["X2"])}</p>
    ${reasoning}
    <p class="vd-note">${esc(v.disclaimer || TymexLive.VERDICT_DISCLAIMER)}</p>`;
}

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
    ${verdictSectionHtml(p, m)}
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
      <div class="notice warn" style="margin-top:.8rem">${esc(v.note)}</div>`;
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
    app.innerHTML = `${backLinkHtml()}
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

/* ---------------------------------------------------------------- Dự đoán vô địch */
const OUTRIGHTS_SOURCE_NOTE = "Tỉ lệ vô địch: tổng hợp từ The Odds API (nhiều nhà cái quốc tế), xác suất đã chuẩn hóa loại trừ lãi nhà cái. Cột mô hình: mô phỏng Monte Carlo phần còn lại của mùa giải bằng mô hình Poisson/Dixon-Coles của Tymex.";
async function pageOutrights() {
  app.innerHTML = `<div class="page-head"><h1>Dự đoán vô địch</h1></div>`;
  const holder = document.createElement("div");
  holder.innerHTML = loading();
  app.appendChild(holder);
  const data = await window.TymexData.kv("outrights");
  if (!data || !Array.isArray(data.leagues) || !data.leagues.length) {
    holder.innerHTML = emptyBox("Dữ liệu dự đoán vô địch sẽ có sau lần đồng bộ kế tiếp.");
    return;
  }
  holder.innerHTML = `<p class="muted small">${esc(OUTRIGHTS_SOURCE_NOTE)}<br>`
    + `Tỉ lệ thị trường lấy lúc: ${esc(fmtStamp(data.fetched_at))} · Mô phỏng chạy lúc: ${esc(fmtStamp(data.simulated_at))} (${esc(tzLabel())}).</p>`;
  data.leagues.forEach((lg) => holder.insertAdjacentHTML("beforeend", outrightCard(lg)));
  holder.insertAdjacentHTML("beforeend", `<p class="vd-note">${esc(TymexLive.VERDICT_DISCLAIMER)}</p>`);
}
function outrightCard(lg) {
  const market = lg.market || {}, model = lg.model || {};
  const mOut = market.available ? (market.outcomes || []) : [];
  const modOut = model.available ? (model.outcomes || []) : [];
  const mByTeam = new Map(mOut.map((o) => [o.team, o]));
  const modByTeam = new Map(modOut.map((o) => [o.team, o]));
  // Hợp nhất: top 6 theo xác suất thị trường, cộng thêm mọi đội thuộc top 3 của mô hình mà thị trường chưa có.
  // Không có dữ liệu thị trường thì lấy top 6 của mô hình.
  const teams = (mOut.length ? mOut.slice(0, 6) : modOut.slice(0, 6)).map((o) => o.team);
  modOut.slice(0, 3).forEach((o) => { if (!teams.includes(o.team)) teams.push(o.team); });
  const marketTop = mOut.length ? mOut[0].team : null;
  const modelTop = modOut.length ? modOut[0].team : null;
  const bar = (p, cls) => (p == null ? `<span class="muted">—</span>`
    : `<div class="sbar" role="img" aria-label="${pct(p * 100, 1)}%"><div class="${cls}" style="width:${Math.max(1.5, p * 100)}%"></div></div><span class="num small">${pct(p * 100, 1)}%</span>`);
  const rows = teams.map((team) => {
    const m = mByTeam.get(team), md = modByTeam.get(team);
    const chips = [];
    if (team === marketTop) chips.push(`<span class="chip">Ứng viên số 1 (thị trường)</span>`);
    if (team === modelTop) chips.push(`<span class="chip">Mô hình Tymex đánh giá cao nhất</span>`);
    return `<tr><td><b>${esc(team)}</b>${chips.length ? `<div style="margin-top:.25rem">${chips.join(" ")}</div>` : ""}</td>`
      + `<td class="r num">${m ? Number(m.odds).toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}</td>`
      + `<td>${bar(m ? m.prob : null, "sb-h")}</td><td>${bar(md ? md.prob : null, "sb-a")}</td></tr>`;
  }).join("");
  let notes = "";
  if (!market.available) notes += `<p class="block-sub">Tỉ lệ thị trường: ${esc(market.reason || "chưa có dữ liệu.")}</p>`;
  else notes += `<p class="block-sub">Thị trường: ${esc(market.bookmakers ?? "?")} nhà cái · lấy lúc ${esc(fmtStamp(market.fetched_at))}.</p>`;
  if (!model.available) notes += `<p class="block-sub">Mô hình Tymex: ${esc(model.note || model.reason || "chưa đủ dữ liệu để mô phỏng.")}</p>`;
  else if (model.note) notes += `<p class="block-sub">Mô hình Tymex: ${esc(model.note)}</p>`;
  else if (model.n_sims) notes += `<p class="block-sub">Mô hình Tymex: ${Number(model.n_sims).toLocaleString("vi-VN")} lần mô phỏng${model.fixtures_remaining != null ? ` · còn ${model.fixtures_remaining} trận chưa đá` : ""}.</p>`;
  return `<section class="block"><h2>${esc(lg.name)}</h2>${notes}`
    + (rows ? `<div class="t-scroll"><table class="t"><thead><tr><th>Đội</th><th class="r">Tỉ lệ vô địch</th><th>Xác suất thị trường</th><th>Xác suất mô hình Tymex</th></tr></thead><tbody>${rows}</tbody></table></div>`
            : emptyBox("Chưa có ứng viên nào cho giải này."))
    + `</section>`;
}

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
    <h1>Tymex — Phân tích & dự đoán bóng đá</h1><p class="muted">Đăng nhập để xem dữ liệu.</p>
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
  window.__tymexStarted = true;
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
