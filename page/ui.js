

/* ---------------- app state ---------------- */
const DB = JSON.parse(document.getElementById("db").textContent);
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x, d = 1) => (x == null || !isFinite(x) ? "–" : (+x).toFixed(d));
const sgn = (x, d = 1) => (x == null || !isFinite(x) ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));
const pct = (x) => Math.round(x * 100) + "%";

let state = newLeague(DB);
let ctx = buildCtx(DB, state);
let owner = new Map();
let tab = "teams";
let loaded = false;
const ui = {
  trade: { mine: "", partner: "", give: new Set(), get: new Set(), mg: 0, mr: 0 },
  finder: { partners: new Set(), shapes: new Set(["1-1", "2-1", "1-2"]), minAccept: 0.3, running: false, results: null, ranFor: "" },
  players: { q: "", pos: "", own: "all", sort: "a", dir: -1, sel: "" },
  imp: { input: "", season: 2026, status: { kind: "", text: "" }, pending: null, mine: null, busy: false },
  confirm: "",
};

const POSL = (pos) => POS_LABEL[pos] || pos;
function chipOf(pos, style) { return `<span class="chip ${pos}"${style ? ` style="${style}"` : ""}>${POSL(pos)}</span>`; }
const LABEL = (p) => `${p.n} · ${POSL(p.p)} ${p.t}`;
const byLabel = new Map(DB.players.map((p) => [LABEL(p).toLowerCase(), p]));
$("#playerList").innerHTML = DB.players.map((p) => `<option value="${esc(LABEL(p))}"></option>`).join("");
$("#dataStamp").textContent = `Stats through Week ${DB.doneWeek ?? DB.curWeek - 1} · data updated ${DB.builtAt ? new Date(DB.builtAt).toLocaleDateString([], { month: "short", day: "numeric" }) : ""}`;

function rebuild() {
  ctx = buildCtx(DB, state);
  owner = new Map();
  for (const t of state.teams) for (const id of t.roster) owner.set(id, t);
}
function myTeam() { return state.teams.find((t) => t.mine) || state.teams[0]; }
function teamById(id) { return state.teams.find((t) => t.id === id); }
function pl(id) { return ctx.byId.get(id); }
function perWeek(x) { return x / Math.max(1, ctx.wSum); }
function recordStr(t) {
  if (!t || (t.wins == null && t.losses == null)) return "";
  return `${+t.wins || 0}–${+t.losses || 0}${+t.ties ? "–" + +t.ties : ""}`;
}
function styleWord(v) {
  if (v == null || v === "") return "Average";
  v = +v;
  return v <= 0.15 ? "Very casual" : v < 0.4 ? "Casual" : v <= 0.6 ? "Average" : v < 0.85 ? "Dedicated" : "Very dedicated";
}
const NFL_NAMES = { ARI: "Cardinals", ATL: "Falcons", BAL: "Ravens", BUF: "Bills", CAR: "Panthers", CHI: "Bears", CIN: "Bengals", CLE: "Browns", DAL: "Cowboys", DEN: "Broncos", DET: "Lions", GB: "Packers", HOU: "Texans", IND: "Colts", JAX: "Jaguars", KC: "Chiefs", LA: "Rams", LAC: "Chargers", LV: "Raiders", MIA: "Dolphins", MIN: "Vikings", NE: "Patriots", NO: "Saints", NYG: "Giants", NYJ: "Jets", PHI: "Eagles", PIT: "Steelers", SEA: "Seahawks", SF: "49ers", TB: "Buccaneers", TEN: "Titans", WAS: "Commanders" };
function fanWord(v) { v = v == null || v === "" ? 0.5 : +v; return v <= 0.15 ? "Barely follows" : v < 0.4 ? "Casual fan" : v <= 0.6 ? "Fan" : v < 0.85 ? "Big fan" : "Diehard"; }
function styleLabel(v) { return v == null || v === "" || (v > 0.4 && v <= 0.6) ? "" : styleWord(v).toLowerCase(); }
function moodInfo(t) {
  const m = teamMood(t), M = state.settings.standings ?? 0.5;
  const edge = (+state.settings.stubborn) - M * m;
  const word = m >= 0.6 ? "Desperate" : m >= 0.2 ? "Restless" : m > -0.2 ? "Even" : m > -0.6 ? "Comfortable" : "Content";
  return { m, edge, word, cls: m >= 0.2 ? "hot" : m <= -0.2 ? "cool" : "soft" };
}
function byeOf(p) { return (DB.byes[p.t] || []).join(", ") || "–"; }
const ESPN_STATUS = { INJURY_RESERVE: "IR", OUT: "Out", DOUBTFUL: "Doubtful", QUESTIONABLE: "Questionable", SUSPENSION: "Suspended" };
/* What we know about a player's availability: the label, how serious, and why. */
function injInfo(p) {
  if (!p) return null;
  const cur = +state.settings.curWeek;
  const x = extOf(p.id), ij = p.ij || null;
  const eff = effOut(state, p, cur);
  const mine = state.out[p.id] != null && state.out[p.id] !== "";
  const why = [];
  if (ij && ij.inj) why.push(ij.inj);
  if (mine) why.push("your entry");
  else if (x && x.ret != null && state.autoOut[p.id] === x.ret) why.push("ESPN's expected return");
  else if (state.autoOut[p.id] != null && state.autoOut[p.id] > 0 && !(ij && ij.thru === state.autoOut[p.id])) why.push("ESPN status at import");
  else if (ij && ij.why) why.push(ij.why + (ij.src ? ` (${ij.src}${ij.upd ? ", " + fmtDate(ij.upd) : ""})` : ""));
  if (x && x.status && ESPN_STATUS[x.status]) why.push("ESPN: " + ESPN_STATUS[x.status]);
  if (eff != null && eff >= cur) {
    const label = eff >= 18 ? "Out for season" : eff > cur ? `Out · back wk ${eff + 1}` : (ij && ij.st === "Doubtful" && !mine ? "Doubtful" : "Out this week");
    return { label, cls: eff > cur ? "ir" : "q", why: why.join(" · "), eff };
  }
  if (x && x.status) {
    const lab = ESPN_STATUS[x.status];
    if (lab === "Questionable") return { label: "Questionable", cls: "q", why: why.join(" · "), eff: null };
    if (!lab) return null;
  }
  if (ij && ij.st) return { label: ij.st, cls: /practice/.test(ij.st) ? "soft" : "q", why: why.join(" · "), eff: null };
  return null;
}
function autoOutOf(p) {
  const a = state.autoOut[p.id];
  if (a != null && a !== "") return +a > 0 ? +a : null;
  return defaultOut(DB, p, +state.settings.curWeek);
}
function injTag(p) {
  const i = injInfo(p);
  return i ? `<span class="tag ${i.cls}" title="${esc(i.why || i.label)}">${esc(i.label)}</span>` : "";
}

/* ---------------- saving: one document per league ---------------- */
const LS_KEY = "fantasy-trader:leagues";
const LS_OLD = "fantasy-trader:league";
const ACTIVE_KEY = "fantasy-trader:active";
function canon(v) {
  if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
  if (v && typeof v === "object") return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
  return JSON.stringify(v);
}
const clone = (x) => JSON.parse(JSON.stringify(x));
let leagues = new Map();
let activeKey = "main";
try { activeKey = localStorage.getItem(ACTIVE_KEY) || "main"; } catch (e) {}
let dbNS = null, saveTimer = null, saving = false, again = false, dirty = false, storeMode = "none";
const lastSaved = {};

function setStatus(kind, text) {
  $("#saveStatus").innerHTML = `<i class="save-dot ${kind}"></i>${esc(text)}`;
}
function setActive(key) { activeKey = key; try { localStorage.setItem(ACTIVE_KEY, key); } catch (e) {} }
function saveLocal() { try { localStorage.setItem(LS_KEY, JSON.stringify(Object.fromEntries(leagues))); } catch (e) {} }
function changed(opts = {}) {
  if (!opts.keepCtx) rebuild();
  if (!opts.quiet) ui.finder.results = null;
  dirty = true;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flush, 700);
  setStatus("busy", "Saving…");
  if (!opts.quiet) render();
}
async function flush() {
  clearTimeout(saveTimer);
  if (saving) { again = true; return; }
  saving = true;
  const key = activeKey;
  const body = clone(state);
  const str = canon(body);
  try {
    leagues.set(key, body);
    if (dbNS) await dbNS.doc("leagues/" + key).set(body); else saveLocal();
    lastSaved[key] = str;
    if (key === activeKey) dirty = false;
    setStatus(dbNS ? "ok" : "local", dbNS ? "Saved" : "Saved in this browser only");
  } catch (e) {
    if (e && e.code === "unavailable") setTimeout(flush, 1500 + Math.random() * 1000);
    else if (e && e.code === "quota_exceeded") setStatus("err", "Storage is full. Delete a league you no longer need.");
    else setStatus("err", e && e.code === "invalid_argument" ? "You can view this league but not change it" : "Couldn't save. Your changes are kept on this page.");
  }
  saving = false;
  renderSwitcher();
  if (again) { again = false; flush(); }
}
function accept(data) {
  const L = newLeague(DB);
  Object.assign(L, data);
  const ds = data.settings || {};
  L.settings = { ...DEFAULT_SETTINGS, ...ds };
  L.settings.scoring = { ...DEFAULT_SETTINGS.scoring, ...(ds.scoring || {}) };
  L.settings.scoring.byPos = clone((ds.scoring && ds.scoring.byPos) || {});
  for (const k of ["paTier", "yaTier"]) L.settings.scoring[k] = clone((ds.scoring && ds.scoring[k]) || DEFAULT_SETTINGS.scoring[k]);
  L.settings.slots = { ...DEFAULT_SETTINGS.slots, ...(ds.slots || {}) };
  // leagues imported before kickers and defenses were modeled kept their slots as slotsK / slotsDST
  if (ds.slots && ds.slots.K == null && ds.slotsK != null) L.settings.slots.K = +ds.slotsK || 0;
  if (ds.slots && ds.slots.DST == null && ds.slotsDST != null) L.settings.slots.DST = +ds.slotsDST || 0;
  delete L.settings.slotsK; delete L.settings.slotsDST;
  L.settings.perc = { ...DEFAULT_SETTINGS.perc, ...(ds.perc || {}) };
  // leagues saved before the Week 4 backtest still carry the old 50% expert default
  if (!(+data.v >= 3) && +ds.expertWeight === 0.5) L.settings.expertWeight = DEFAULT_SETTINGS.expertWeight;
  // expert weights follow the model's tuned defaults until you move either slider yourself
  // (leagues saved before this still on the old defaults, 20% and 25%, count as following)
  if (ds.expertAuto == null) L.settings.expertAuto = (ds.expertWeight == null || +ds.expertWeight === 0.2) && (ds.weeklyExpert == null || +ds.weeklyExpert === 0.25);
  if (L.settings.expertAuto) { L.settings.expertWeight = DEFAULT_SETTINGS.expertWeight; L.settings.weeklyExpert = DEFAULT_SETTINGS.weeklyExpert; }
  L.v = 3;
  L.teams = (data.teams || []).map((t) => ({ ...t, roster: (t.roster || []).slice() }));
  L.out = { ...(data.out || {}) };
  L.autoOut = { ...(data.autoOut || {}) };
  L.overrides = { ...(data.overrides || {}) };
  L.espn = data.espn ? clone(data.espn) : null;
  // leagues saved before injury timelines: drop the old guessed absences in sample leagues
  if (!data.v || data.v < 2) { if (data.example) L.out = {}; L.autoOut = {}; L.v = 2; }
  // when the weekly data moves to a new week, move the league with it
  if (+L.settings.curWeek < +DB.curWeek) L.settings.curWeek = DB.curWeek;
  // ESPN-based absences stand only while the import is newer than the weekly data;
  // after a data refresh the new injury timelines take over (ESPN's own return dates excepted)
  const espnNewer = L.espn && L.espn.importedAt && new Date(L.espn.importedAt) > new Date(DB.builtAt || 0);
  for (const id of Object.keys(L.autoOut)) {
    const x = L.espn && L.espn.players && L.espn.players[id];
    if (x && x.ret != null && x.ret >= +L.settings.curWeek) continue;
    if (!espnNewer || !x) delete L.autoOut[id];
  }
  state = L;
  rebuild();
}
function resetUi() {
  ui.trade = { mine: "", partner: "", give: new Set(), get: new Set(), mg: 0, mr: 0 };
  if (ui.ss) Object.assign(ui.ss, { mine: "", opp: "", res: null, resFor: null, cands: [], left: { mine: new Set(), theirs: new Set() }, calc: null, calcFor: null, board: null, boardFor: null });
  ui.finder.results = null; ui.finder.partners = new Set();
  ui.players.sel = ""; ui.confirm = "";
  ui.imp.input = state.espn ? String(state.espn.leagueId) : ui.imp.input;
}
async function switchLeague(key) {
  if (dirty) await flush();
  setActive(key);
  const data = leagues.get(key);
  if (data) accept(clone(data)); else { state = newLeague(DB); rebuild(); }
  resetUi();
  tab = state.teams.length ? "trade" : "league";
  render(); renderSwitcher();
}
async function openLeague(key, L, nextTab) {
  if (dirty) await flush();
  setActive(key);
  accept(clone(L));
  resetUi();
  tab = nextTab || "trade";
  dirty = true;
  render();
  await flush();
}
async function removeLeague(key) {
  leagues.delete(key);
  delete lastSaved[key];
  dirty = false;
  try { if (dbNS) await dbNS.doc("leagues/" + key).delete(); else saveLocal(); } catch (e) {}
  const next = [...leagues.keys()][0];
  if (next) await switchLeague(next);
  else { setActive("main"); state = newLeague(DB); rebuild(); resetUi(); tab = "league"; render(); renderSwitcher(); }
}
function renderSwitcher() {
  const sel = $("#leagueSwitch");
  if (!sel) return;
  const keys = [...leagues.keys()];
  if (!keys.includes(activeKey)) keys.unshift(activeKey);
  const name = (k) => (k === activeKey ? state.name : (leagues.get(k) || {}).name) || "My league";
  sel.innerHTML = keys.map((k) => `<option value="${esc(k)}" ${k === activeKey ? "selected" : ""}>${esc(name(k))}</option>`).join("")
    + `<option value="__import">+ Import an ESPN league…</option><option value="__new">+ New blank league</option>`;
}
async function initStore() {
  let db = null;
  try { db = window.claude && window.claude.use ? await window.claude.use("db") : null; } catch (e) { db = null; }
  if (db) {
    storeMode = "db"; dbNS = db;
    setStatus("busy", "Loading leagues…");
    db.collection("leagues").onSnapshot((qs) => {
      const next = new Map();
      for (const d of qs.docs) next.set(d.id, d.data());
      leagues = next;
      if (!loaded && !leagues.has(activeKey)) setActive(leagues.has("main") ? "main" : ([...leagues.keys()][0] || activeKey));
      const data = leagues.get(activeKey);
      let redraw = !loaded;
      if (data && !dirty) {
        const str = canon(data);
        if (str !== lastSaved[activeKey]) { lastSaved[activeKey] = str; accept(clone(data)); if (loaded) ui.finder.results = null; redraw = true; }
      }
      if (!loaded) { resetUi(); tab = state.teams.length ? "trade" : "league"; setStatus("ok", leagues.size ? "Saved" : "Ready"); }
      loaded = true;
      renderSwitcher();
      if (redraw) render();
    }, () => setStatus("err", "Lost connection to your saved leagues. Reload to reconnect."));
  } else {
    storeMode = "local";
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) leagues = new Map(Object.entries(JSON.parse(raw)));
      else { const old = localStorage.getItem(LS_OLD); if (old) leagues.set("main", JSON.parse(old)); }
    } catch (e) {}
    if (!leagues.has(activeKey)) setActive(leagues.has("main") ? "main" : ([...leagues.keys()][0] || activeKey));
    const data = leagues.get(activeKey);
    if (data) { accept(clone(data)); lastSaved[activeKey] = canon(data); }
    resetUi();
    tab = state.teams.length ? "trade" : "league";
    loaded = true;
    setStatus("local", "Saved in this browser only");
    renderSwitcher(); render();
  }
}

/* ---------------- ESPN import ---------------- */
const BROWSER = "host:claude_browser";
let mcpNS = null, browserState = "checking";
const fmtNum = (x) => String(+(+x || 0).toFixed(2));
const SLOT_LABEL = { QB: "QB", RB: "RB", WR: "WR", TE: "TE", K: "K", DST: "D/ST", RBWR: "RB/WR", WRTE: "WR/TE", FLEX: "FLEX", OP: "superflex" };
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

async function initBrowser() {
  try { mcpNS = window.claude && window.claude.use ? await window.claude.use("mcp") : null; } catch (e) { mcpNS = null; }
  if (!mcpNS) { browserState = "none"; updateImport(); return; }
  try {
    const lt = await mcpNS.listTools();
    browserState = (lt.servers || []).some((s) => s.server === BROWSER && (s.tools || []).length) ? "ready" : "none";
  } catch (e) { browserState = "none"; }
  updateImport();
}
function resultText(r) {
  if (!r) return "";
  if (typeof r.payload === "string") return r.payload;
  const blocks = (r.content || []).filter((b) => b && b.type === "text").map((b) => b.text);
  if (blocks.length) return blocks.join("\n");
  return r.payload != null ? JSON.stringify(r.payload) : "";
}
function findTabId(r) {
  const p = r && (r.structuredContent || r.payload);
  if (p && typeof p === "object" && p.tabId != null) return p.tabId;
  const t = resultText(r);
  const m = t.match(/tab_?id["']?\s*[:=]?\s*["']?(\d+)/i) || t.match(/\btab\s*#?\s*(\d+)/i);
  return m ? +m[1] : null;
}
function importStatus(kind, text) {
  ui.imp.status = { kind, text };
  const el = $("#espnStatus");
  if (el) { el.className = "notice " + (kind === "err" ? "bad" : kind === "ok" ? "good" : ""); el.textContent = text; }
}
function handleEspnData(raw) {
  const I = ui.imp;
  const p = parseLeagueInput(I.input);
  try {
    const imp = parseEspn(raw, DB, { leagueId: p.leagueId, season: p.season || I.season });
    I.pending = imp;
    const prev = leagues.get("espn-" + imp.leagueId);
    const prevMine = prev && ((prev.teams || []).find((t) => t.mine) || {}).espnTeamId;
    I.mine = p.teamId && p.leagueId === imp.leagueId ? p.teamId : prevMine != null ? prevMine : (imp.teams[0] || {}).espnTeamId;
    if (!p.leagueId) I.input = imp.leagueId;
    importStatus("ok", "Read your league from ESPN. Check the details below, then import.");
  } catch (e) {
    I.pending = null;
    importStatus("err", e.message || "That isn't ESPN league data.");
  }
  updateImport();
}
async function autoImport() {
  const I = ui.imp;
  const p = parseLeagueInput(I.input);
  if (!p.leagueId || !mcpNS) return;
  const url = espnApiUrl(p.leagueId, p.season || I.season);
  I.busy = true; importStatus("busy", "Opening your league in Claude's browser…"); updateImport();
  try {
    const opened = await mcpNS.callTool(BROWSER, "preview_start", { url }, { cache: false });
    const tabId = findTabId(opened);
    let json = null;
    for (let attempt = 0; attempt < 3 && !json; attempt++) {
      await sleep(attempt ? 2500 : 1500);
      importStatus("busy", "Reading the league data…");
      const got = await mcpNS.callTool(BROWSER, "get_page_text", tabId != null ? { tabId } : {}, { cache: false });
      try { json = extractJson(resultText(got)); } catch (e) { if (attempt === 2) throw e; }
    }
    I.busy = false;
    handleEspnData(json);
  } catch (e) {
    I.busy = false;
    const code = e && e.code;
    const msg = code === "server_not_connected" ? "Claude's browser isn't reachable from here. Open this page in the Claude desktop app, or use the two steps below."
      : code === "cancelled" ? "The browser request was declined. Use the two steps below instead."
      : code === "not_in_manifest" || code === "blocked_by_policy" ? "Browser access is turned off for this page. Use the two steps below instead."
      : code === "not_json" ? "Claude's browser didn't get complete league data. If the league is private, sign in to ESPN in Claude's browser and try again, or use the two steps below."
      : code === "tool_error" ? "Claude's browser reported a problem: " + (e.message || "unknown error") + ". Use the two steps below instead."
      : "Automatic import didn't work (" + (e && (e.message || code) || "unknown error") + "). Use the two steps below instead.";
    importStatus("err", msg);
    updateImport();
  }
}
function autoHTML() {
  const p = parseLeagueInput(ui.imp.input);
  if (browserState === "ready") return `<div class="row"><button class="btn primary" data-act="espnAuto" ${!p.leagueId || ui.imp.busy ? "disabled" : ""}>${ui.imp.busy ? "Importing…" : "Import automatically"}</button><span class="notice">Uses Claude's browser in the desktop app. For a private league, sign in to ESPN there once.</span></div>`;
  if (browserState === "checking") return "";
  return `<p class="notice" style="margin:0">Open this page in the Claude desktop app for one-click import. Anywhere else, use the two steps below.</p>`;
}
function parsedHTML() {
  const I = ui.imp, p = parseLeagueInput(I.input);
  if (!I.input.trim()) return "Enter a league ID, or paste the address of any page in your ESPN league.";
  if (!p.leagueId) return `<span class="bad">No league ID found. It's the number after <code>leagueId=</code> in your ESPN address.</span>`;
  return `League <b class="num">${esc(p.leagueId)}</b> · ${p.season || I.season} season${p.teamId ? ` · your team is #${p.teamId}` : ""}`;
}
function previewHTML() {
  const imp = ui.imp.pending;
  if (!imp) return "";
  const matched = Object.keys(imp.players).length;
  const un = [...new Set(imp.report.unmatched)];
  const sc = imp.settings.scoring, sl = imp.settings.slots;
  const te = sc.byPos && sc.byPos.TE && sc.byPos.TE.rec != null ? ` (${fmtNum(sc.byPos.TE.rec)} for TEs)` : "";
  const slotTxt = Object.entries(sl).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${SLOT_LABEL[k]}`).join(", ");
  const exists = leagues.has("espn-" + imp.leagueId);
  return `<div class="callout stack">
    <div><b>${esc(imp.name)}</b> · ${imp.teams.length} teams · ${imp.season} season · week ${imp.settings.curWeek}</div>
    <div class="notice">${matched} players matched${imp.report.kdst ? ` · ${imp.report.kdst} kickers and defenses skipped (not modeled)` : ""}${un.length ? ` · not in the player data: ${esc(un.slice(0, 8).join(", "))}${un.length > 8 ? ` and ${un.length - 8} more` : ""}` : ""}</div>
    <div class="notice">Scoring: ${fmtNum(sc.rec)} per reception${te}, ${fmtNum(sc.passTd)}-point passing TDs. Lineup: ${slotTxt}. Playoffs start week ${imp.settings.playoffStart}.</div>
    ${imp.report.warnings.map((w) => `<div class="notice bad">${esc(w)}</div>`).join("")}
    <label class="field" style="max-width:380px"><span class="label">Which team is yours?</span><select id="espnMine" data-act="espnMine">${imp.teams.map((t) => `<option value="${t.espnTeamId}" ${+ui.imp.mine === t.espnTeamId ? "selected" : ""}>${esc(t.name)}${t.owner ? " · " + esc(t.owner) : ""}</option>`).join("")}</select></label>
    <div class="row"><button class="btn primary" data-act="espnApply">${exists ? "Update this league" : "Import league"}</button><button class="btn" data-act="espnCancel">Cancel</button></div>
  </div>`;
}
function importBoxHTML() {
  const I = ui.imp, p = parseLeagueInput(I.input);
  const url = p.leagueId ? espnApiUrl(p.leagueId, p.season || I.season) : "";
  const when = state.espn && state.espn.importedAt ? new Date(state.espn.importedAt) : null;
  return `<div class="box stack" id="importBox">
    <div class="row"><h3>Import from ESPN</h3><span class="spacer"></span>${when ? `<span class="notice">This league was last imported ${when.toLocaleDateString([], { month: "short", day: "numeric" })} at ${when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>` : ""}</div>
    <div class="row" style="align-items:end">
      <label class="field" style="flex:1;min-width:min(100%,16em)"><span class="label">League ID or ESPN link</span><input type="text" class="wide" id="espnInput" value="${esc(I.input)}" placeholder="1989275344, or https://fantasy.espn.com/football/team?leagueId=…" autocomplete="off" spellcheck="false"></label>
      <label class="field"><span class="label">Season</span><input type="number" id="espnSeason" value="${p.season || I.season}" min="2018" max="2030"></label>
    </div>
    <div class="notice" id="espnParsed">${parsedHTML()}</div>
    <div id="espnAuto">${autoHTML()}</div>
    <ol class="steps">
      <li><a class="btn ${url ? "" : "disabled-link"}" id="espnLink" href="${esc(url || "#")}" target="_blank" rel="noopener" ${url ? "" : 'aria-disabled="true" tabindex="-1"'}>Open league data on ESPN ↗</a><span class="notice">Opens a page of raw text in a new tab. For a private league, be signed in to ESPN in that browser.</span></li>
      <li><span>Select everything on that page (Ctrl+A or ⌘A), copy it, and paste it here. In Firefox, choose <b>Raw Data</b>, then <b>Copy</b>.</span></li>
    </ol>
    <textarea id="espnPaste" spellcheck="false" placeholder="Paste the ESPN page here"></textarea>
    <div class="row"><label class="btn small" for="espnFile">Or choose a saved file</label><input type="file" id="espnFile" accept=".json,.txt,application/json,text/plain" hidden></div>
    <div id="espnStatus" class="notice ${I.status.kind === "err" ? "bad" : I.status.kind === "ok" ? "good" : ""}">${esc(I.status.text)}</div>
    <div id="espnPreview">${previewHTML()}</div>
  </div>`;
}
function updateImport() {
  const set = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };
  set("#espnParsed", parsedHTML());
  set("#espnAuto", autoHTML());
  set("#espnPreview", previewHTML());
  const link = $("#espnLink");
  if (link) {
    const p = parseLeagueInput(ui.imp.input);
    const url = p.leagueId ? espnApiUrl(p.leagueId, p.season || ui.imp.season) : "";
    link.href = url || "#";
    link.classList.toggle("disabled-link", !url);
    if (url) { link.removeAttribute("aria-disabled"); link.removeAttribute("tabindex"); } else { link.setAttribute("aria-disabled", "true"); link.setAttribute("tabindex", "-1"); }
  }
}
function readPasted(text) {
  if (!text || text.trim().length < 2) return;
  let json;
  try { json = extractJson(text); }
  catch (e) { ui.imp.pending = null; importStatus("err", e.message); updateImport(); return; }
  handleEspnData(json);
  const ta = $("#espnPaste");
  if (ta && ui.imp.pending) ta.value = "";
}

/* ---------------- shared bits ---------------- */
function emptyLeague() {
  return `<div class="empty stack" style="justify-items:center">
    <h3>No teams yet</h3>
    <p style="margin:0;max-width:56ch">Import your ESPN league to bring in every roster, your scoring and your lineup settings. You can also enter teams by hand, or try a sample league built from a simulated draft.</p>
    <div class="row" style="justify-content:center">
      <button class="btn primary" data-act="gotoImport">Import from ESPN</button>
      <button class="btn" data-act="sample">Load sample league</button>
      <button class="btn" data-act="goto" data-tab="teams">Add teams by hand</button>
    </div></div>`;
}
function exampleBanner() {
  return state.example ? `<div class="callout row" style="margin-bottom:14px"><span class="tag ex">Sample</span><span>This is a simulated league for trying the tool. Import your own on the League tab, or switch leagues at the top.</span><button class="btn small" data-act="gotoImport">Import from ESPN</button></div>` : "";
}

/* ---------------- TRADE ---------------- */
function renderTrade() {
  const el = $("#panel-trade");
  if (!state.teams.length) { el.innerHTML = `<h2>Trade analyzer</h2><p class="lede">Pick players on both sides to see who actually wins and how likely the other manager is to accept.</p>` + emptyLeague(); return; }
  const T = ui.trade;
  if (!teamById(T.mine)) T.mine = myTeam().id;
  if (!teamById(T.partner) || T.partner === T.mine) T.partner = (state.teams.find((t) => t.id !== T.mine) || {}).id || "";
  const A = teamById(T.mine), B = teamById(T.partner);
  for (const id of [...T.give]) if (!A.roster.includes(id)) T.give.delete(id);
  for (const id of [...T.get]) if (!B || !B.roster.includes(id)) T.get.delete(id);
  const opts = (sel, skip) => state.teams.filter((t) => t.id !== skip).map((t) => `<option value="${t.id}" ${t.id === sel ? "selected" : ""}>${esc(t.name)}${t.mine ? " (mine)" : ""}</option>`).join("");
  const side = (team, set, which) => {
    if (!team) return `<div class="empty">Add a second team to trade with.</div>`;
    const rows = team.roster.filter((id) => pl(id)).sort((x, y) => ctx.ppg.a.get(y) - ctx.ppg.a.get(x)).map((id) => {
      const p = pl(id);
      return `<label class="pick ${set.has(id) ? "on" : ""}">
        <input type="checkbox" id="pick-${which}-${id}" data-act="pick" data-side="${which}" data-id="${id}" ${set.has(id) ? "checked" : ""}>
        ${chipOf(p.p)}
        <span style="min-width:0"><span class="pname">${esc(p.n)}</span> ${injTag(p)}<br><span class="sub">${p.t} · bye ${byeOf(p)}</span></span>
        <span class="num" title="Projected / market points per game">${ctx.val.get(id).plays ? fmt(ctx.ppg.a.get(id)) : "out"} <span class="muted">/ ${fmt(ctx.ppg.q.get(id))}</span></span>
      </label>`;
    }).join("");
    const money = state.settings.faab ? `<label class="money-row"><span>Add FAAB</span><span class="money-in">$<input type="number" id="money-${which}" min="0" max="${faabOf(ctx, team)}" step="1" value="${which === "give" ? T.mg || "" : T.mr || ""}" placeholder="0" data-act="money" data-side="${which}" aria-label="FAAB dollars"></span><span class="sub">of $${fmt(faabOf(ctx, team), 0)} left</span></label>` : "";
    return (rows || `<div class="empty">This roster is empty.</div>`) + money;
  };
  if (A) T.mg = Math.min(T.mg || 0, faabOf(ctx, A));
  if (B) T.mr = Math.min(T.mr || 0, faabOf(ctx, B));
  let result = `<div class="empty">Select at least one player on each side.</div>`;
  if (B && (T.give.size || T.get.size || T.mg || T.mr)) result = verdictHTML(A, B, [...T.give], [...T.get], { give: state.settings.faab ? T.mg : 0, get: state.settings.faab ? T.mr : 0 });
  el.innerHTML = `${exampleBanner()}<h2>Trade analyzer</h2>
    <p class="lede">Numbers are points per game for the rest of the season: <b>our projection</b> / <span class="muted">what the market sees</span>. Values change week to week as teammates get hurt or return, and the results below count every week. Results are measured as the change in each team's starting lineup, per week, through Week ${state.settings.lastWeek}.</p>
    <div class="grid cols-2" style="margin-bottom:14px">
      <div class="box side"><div class="row"><span class="label">You give</span><span class="spacer"></span><select id="tradeMine" data-act="tmine">${opts(T.mine, "")}</select></div>${side(A, T.give, "give")}</div>
      <div class="box side"><div class="row"><span class="label">You get</span><span class="spacer"></span><select id="tradePartner" data-act="tpartner">${opts(T.partner, T.mine)}</select></div>${side(B, T.get, "get")}</div>
    </div>
    <div class="box" id="tradeResult">${result}</div>`;
}

function verdictHTML(A, B, give, get, money) {
  const e = evalTrade(ctx, A, B, give, get, money);
  const me = perWeek(e.dA), them = perWeek(e.dB), seen = perWeek(e.perceived);
  const names = (ids) => ids.map((id) => esc(pl(id).n)).join(" + ") || "nothing";
  let head;
  if (me > 0.15 && them < -0.15) head = `You win this trade by ${fmt(me - them, 1)} pts/week of swing`;
  else if (me > 0.15 && them >= -0.15) head = `Both lineups get better. You gain ${fmt(me)} pts/week`;
  else if (me <= 0.15 && me >= -0.15) head = `This barely changes your lineup`;
  else head = `You lose this trade: ${fmt(me)} pts/week for you`;
  const span = Math.max(3, Math.abs(me), Math.abs(them));
  const dbar = (v) => {
    const w = Math.min(50, Math.abs(v) / span * 50);
    return `<div class="dbar"><i style="${v >= 0 ? `left:50%;width:${w}%;background:var(--good)` : `left:${50 - w}%;width:${w}%;background:var(--bad)`}"></i></div>`;
  };
  const fa = (id, who) => id ? `<li>${who} fills the open roster spot with free agent <b>${esc(pl(id).n)}</b> (${POSL(pl(id).p)}).</li>` : "";
  const wk = state.settings.curWeek;
  const lineupDiff = (team, newRoster, you) => {
    const td = teamDepth(ctx, team);
    const b = lineupForWeek(ctx, team.roster, "a", wk, td).ids, a = lineupForWeek(ctx, newRoster, "a", wk, td).ids;
    const inn = a.filter((x) => !b.includes(x)), out = b.filter((x) => !a.includes(x));
    if (!inn.length && !out.length) return you ? "keep the same starters" : "keeps the same starters";
    const v1 = you ? "start " : "starts ", v2 = you ? "bench or lose " : "benches or loses ";
    return `${inn.length ? v1 + names(inn) : ""}${inn.length && out.length ? "; " : ""}${out.length ? v2 + names(out) : ""}`;
  };
  const a1 = A.roster.filter((x) => !give.includes(x)).concat(get), b1 = B.roster.filter((x) => !get.includes(x)).concat(give);
  const streamNote = (team, newRoster, who, you) => {
    const td = teamDepth(ctx, team);
    const before = lineupForWeek(ctx, team.roster, "a", wk, td).streamers, after = lineupForWeek(ctx, newRoster, "a", wk, td).streamers;
    const add = after.filter((x) => !before.includes(x));
    return add.length ? `<li>${who} would stream ${add.join(" and ")} from the waiver wire after this trade; that's counted at the free-agent level, not zero.</li>` : "";
  };
  return `<div class="verdict">
    <div class="verdict-head">${head}</div>
    <div class="metric-grid">
      <div class="metric"><span class="label">Your real change</span><span class="big ${me >= 0 ? "good" : "bad"}">${sgn(me)}</span><span class="note">pts/week · ${sgn(e.dA, 0)} rest of season</span>${dbar(me)}</div>
      <div class="metric"><span class="label">${esc(B.name)} real change</span><span class="big ${them >= 0 ? "good" : "bad"}">${sgn(them)}</span><span class="note">pts/week · ${sgn(e.dB, 0)} rest of season</span>${dbar(them)}</div>
      <div class="metric"><span class="label">What ${esc(B.name)} sees</span><span class="big">${sgn(seen)}</span><span class="note">pts/week, judged on market numbers</span></div>
      <div class="metric"><span class="label">Chance they accept</span><span class="big">${pct(e.accept)}</span><div class="meter"><i style="width:${Math.round(e.accept * 100)}%"></i></div></div>
    </div>
    <ul class="notice" style="margin:0;padding-left:18px">
      <li>Their view mixes lineup need (${sgn(perWeek(e.needQ))}/wk) with the trade value of the players moving (${sgn(perWeek(e.rawQ))}/wk), weighted ${Math.round(e.needW * 100)}% need.</li>
      <li>${esc(B.name)}: ${styleWord(B.style).toLowerCase()} manager${B.style != null && Math.abs(B.style - 0.5) > 0.05 ? ` (${B.style < 0.5 ? "goes by results and big names" : "goes by rankings, projections and usage"})` : ""}${recordStr(B) ? `, ${recordStr(B)} and ${moodInfo(B).word.toLowerCase()}` : ""}. Needs ${sgn(e.edge, 2)} pts/wk of edge to say yes. Set both on the Teams tab.</li>
      ${(() => { const f = fanOf(B); const ids = give.concat(get).filter((id) => pl(id) && f.fav && f.fan > 0.005 && pl(id).t === f.fav); return ids.length ? `<li>${esc(B.name)} is a${f.fan >= 0.85 ? " diehard" : ""} ${esc(NFL_NAMES[f.fav] || f.fav)} fan: he knows ${ids.map((id) => esc(pl(id).n)).join(" and ")} well, so he sees ${ids.length > 1 ? "their" : "his"} real value (plus a small homer bump) instead of the market's.</li>` : ""; })()}
      ${tradeValueNote(give, get)}
      <li>This week, you ${lineupDiff(A, a1, true)}. ${esc(B.name)} ${lineupDiff(B, b1)}.</li>
      ${streamNote(A, a1, "You", true)}${streamNote(B, b1, esc(B.name), false)}
      ${fa(e.faA, "You")}${fa(e.faB, esc(B.name))}
      ${moneyNote(A, B, e)}
    </ul>
  </div>`;
}

/* What managers think each player in the deal is worth per week, and why QBs/TEs come out low. */
function tradeValueNote(give, get) {
  const ids = give.concat(get);
  if (!ids.length) return "";
  const tv = (id) => `${esc(pl(id).n)} ${fmt(Math.max(0, marketPrice(ctx, id)))}`;
  const qt = ids.some((id) => ["QB", "TE"].includes(pl(id).p)), kdx = ids.some((id) => KD_POS.includes(pl(id).p));
  const sf = ctx.mkt && ctx.mkt.b > 0.5;
  return `<li>Trade value per week, as managers see it: ${ids.map(tv).join(" · ")}.${qt ? sf ? " Your league starts two quarterbacks, so QBs are priced at their full points." : " QBs and TEs are priced the way the consensus overall rankings price them: in a one-QB league only the top few are worth much more than a streamer." : ""}${kdx ? " Kickers and defenses are priced the same way: the overall rankings list only a handful of them, far down, so most are worth next to nothing in a trade even when they help a lineup." : ""}</li>`;
}

/* What the FAAB in a trade is worth to each side. */
function moneyNote(A, B, e) {
  const net = (e.money.get || 0) - (e.money.give || 0);
  if (!state.settings.faab || !net) return "";
  const va = faabValue(ctx, A, net), vb = faabValue(ctx, B, -net);
  const part = (v) => `${sgn(perWeek(v.total), 2)} pts/wk (${sgn(perWeek(v.stream), 2)} from better weekly pickups, ${sgn(perWeek(v.breakout), 2)} from future breakouts)`;
  return `<li>FAAB: you ${net > 0 ? "receive" : "pay"} $${Math.abs(net)}. Worth ${part(va)} to you and ${part(vb)} to ${esc(B.name)}. Both are already in the numbers above.</li>`;
}

/* ---------------- FINDER ---------------- */
function renderFinder() {
  const el = $("#panel-finder");
  if (state.teams.length < 2) { el.innerHTML = `<h2>Trade finder</h2><p class="lede">Searches every 1-for-1 and 2-for-1 deal between your team and the rest of the league, then ranks them by what you gain times the chance they say yes.</p>` + emptyLeague(); return; }
  const F = ui.finder, me = myTeam();
  const shapes = [["1-1", "1 for 1"], ["2-1", "2 for 1 (you give 2)"], ["1-2", "1 for 2 (you get 2)"], ["2-2", "2 for 2 (slow)"]];
  let body = "";
  if (F.running) body = `<div class="stack"><div class="progress"><i id="finderBar"></i></div><div class="notice" id="finderMsg">Starting…</div></div>`;
  else if (!F.results) body = `<div class="empty">Run a search to see ranked trade ideas for <b>${esc(me.name)}</b>.</div>`;
  else if (!F.results.length) body = `<div class="empty">No trades cleared your minimum acceptance chance. Lower it or allow more trade shapes.</div>`;
  else body = `<div class="tablewrap"><table>
    <thead><tr><th>Partner</th><th>You give</th><th>You get</th><th class="n">Your gain</th><th class="n">Their real</th><th class="n">They see</th><th class="n">Accept</th><th></th></tr></thead>
    <tbody>${F.results.map((r, i) => {
      const t = teamById(r.partner);
      if (!t) return "";
      const list = (ids, dollars) => ids.map((id) => pl(id) ? `<div class="row" style="gap:6px;flex-wrap:nowrap">${chipOf(pl(id).p)}<span class="pname">${esc(pl(id).n)}</span>${injTag(pl(id))}</div>` : "").join("")
        + (dollars ? `<div class="row" style="gap:6px"><span class="chip faab">$</span><span class="pname">$${dollars} FAAB</span><span class="tag q">sweetener</span></div>` : "");
      const them = perWeek(r.dB);
      const ask = r.askFor ? `<div class="sub" style="white-space:normal;margin-top:4px" title="They'd still be ${pct(r.askFor.accept)} likely to accept, and your gain becomes ${sgn(perWeek(r.askFor.dA))} pts/wk">Room to ask for $${r.askFor.amount} FAAB too (${pct(r.askFor.accept)})</div>` : "";
      return `<tr><td>${esc(t.name)}${recordStr(t) || t.style != null ? `<div class="sub">${[recordStr(t), styleLabel(t.style)].filter(Boolean).join(" · ")}</div>` : ""}</td><td>${list(r.give, r.money && r.money.give)}</td><td>${list(r.get, r.money && r.money.get)}${ask}</td>
        <td class="n good">${sgn(perWeek(r.dA))}</td><td class="n ${them >= 0 ? "good" : "bad"}">${sgn(them)}</td><td class="n">${sgn(perWeek(r.perceived))}</td>
        <td class="n">${pct(r.accept)}</td><td><button class="btn small" data-act="openTrade" data-i="${i}">Open</button></td></tr>`;
    }).join("")}</tbody></table></div>
    <p class="notice" style="margin:10px 0 0">All columns are points per week. "Their real" below zero with a high acceptance chance is a deal the market is mispricing in your favor.</p>`;
  el.innerHTML = `${exampleBanner()}<h2>Trade finder</h2>
    <p class="lede">Searches deals between <b>${esc(me.name)}</b> and the rest of the league, then ranks them by your real gain times the chance the other manager says yes.</p>
    <div class="box stack" style="margin-bottom:14px">
      <div class="row">
        <div class="field" style="flex:1 1 100%"><span class="label">Trade partners <span class="notice" style="text-transform:none;letter-spacing:0;font-family:var(--body)">· ${F.partners.size ? `${F.partners.size} picked` : "all teams"}</span></span>
          <div class="row" style="gap:6px">
            <button class="pchip ${F.partners.size ? "" : "on"}" data-act="fpartAll" aria-pressed="${!F.partners.size}">All teams</button>
            ${state.teams.filter((t) => t.id !== me.id).map((t) => `<button class="pchip ${F.partners.has(t.id) ? "on" : ""}" data-act="fpart" data-team="${t.id}" aria-pressed="${F.partners.has(t.id)}">${esc(t.name)}${recordStr(t) ? ` <span class="pchip-rec">${recordStr(t)}</span>` : ""}</button>`).join("")}
            ${state.teams.some((t) => t.id !== me.id && teamMood(t) > 0.2) ? `<button class="btn small ghost" data-act="fpartLosing" title="Teams with a losing record">Losing teams only</button>` : ""}
          </div></div>
        <div class="field" style="min-width:200px;flex:1;max-width:320px"><span class="label">Minimum chance they accept: <span id="minAccLabel">${pct(F.minAccept)}</span></span><input type="range" id="finderMin" min="0.05" max="0.9" step="0.05" value="${F.minAccept}" data-act="fmin"></div>
      </div>
      <div class="row">${shapes.map(([k, l]) => `<label class="row" style="gap:6px"><input type="checkbox" id="shape-${k}" data-act="fshape" data-k="${k}" ${F.shapes.has(k) ? "checked" : ""}>${l}</label>`).join("")}</div>
      <div class="row"><button class="btn primary" data-act="runFinder" ${F.running ? "disabled" : ""}>${F.running ? "Searching…" : "Find trades"}</button>${F.results && !F.running ? `<span class="notice">${F.ranFor}</span>` : ""}</div>
    </div>
    <div class="box">${body}</div>`;
}
async function runFinder() {
  const F = ui.finder, me = myTeam();
  F.running = true; F.results = null;
  renderFinder();
  const gen = findTrades(ctx, me, { shapes: [...F.shapes], minAccept: F.minAccept, partnerIds: [...F.partners].filter((id) => teamById(id)) });
  let r, t0 = performance.now();
  while (!(r = gen.next()).done) {
    if (performance.now() - t0 > 40) {
      const bar = $("#finderBar"), msg = $("#finderMsg");
      if (bar) bar.style.width = Math.round((r.value.pi - 1) / r.value.of * 100) + "%";
      if (msg) msg.textContent = `Checked ${r.value.n.toLocaleString()} trades · now ${r.value.partner}`;
      await new Promise((res) => setTimeout(res, 0));
      t0 = performance.now();
    }
  }
  F.results = r.value;
  F.ranFor = `${r.value.length} ideas for ${me.name}${F.partners.size ? ` with ${[...F.partners].map((id) => (teamById(id) || {}).name).filter(Boolean).join(", ")}` : ""}, searched ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  F.running = false;
  if (tab === "finder") renderFinder();
}

/* ---------------- TEAMS ---------------- */
/* Average starter points by position for every team this week, and the league average. */
function leagueNeeds() {
  const wk = +state.settings.curWeek, by = new Map(), sum = {}, cnt = {};
  for (const t of state.teams) {
    const lw = lineupForWeek(ctx, t.roster, "a", wk, teamDepth(ctx, t)), o = {};
    for (const id of lw.ids) { const p = pl(id); if (!p) continue; (o[p.p] = o[p.p] || []).push(ctx.wkA.get(id)[0]); }
    for (const pos of lw.streamers) (o[pos] = o[pos] || []).push((ctx.waiver.a[pos] || [])[0] || 0);
    const avg = {};
    for (const pos of POSITIONS) if (o[pos] && o[pos].length) { avg[pos] = o[pos].reduce((a, b) => a + b, 0) / o[pos].length; sum[pos] = (sum[pos] || 0) + avg[pos]; cnt[pos] = (cnt[pos] || 0) + 1; }
    by.set(t.id, avg);
  }
  const lg = {};
  for (const pos of POSITIONS) if (cnt[pos]) lg[pos] = sum[pos] / cnt[pos];
  return { by, lg };
}
/* What a manager's fandom does: which players it touches and how. */
function fanFact(t) {
  const f = fanOf(t);
  if (!f.fav || f.fan < 0.005) return "";
  const me = myTeam();
  const his = t.roster.filter((id) => pl(id) && pl(id).t === f.fav), mine = me && me !== t ? me.roster.filter((id) => pl(id) && pl(id).t === f.fav) : [];
  const names = (ids) => ids.slice(0, 3).map((id) => esc(pl(id).n)).join(", ") + (ids.length > 3 ? ` +${ids.length - 3}` : "");
  return `<div><b>${esc(f.fav)} fan</b> <span class="sub" style="white-space:normal">sees ${esc(NFL_NAMES[f.fav] || f.fav)} players ${Math.round(FAN_KNOW * f.fan * 100)}% of the way to their real value, plus ${Math.round(FAN_PREMIUM * f.fan * 100)}% homer bump${his.length ? ` · his: ${names(his)}` : ""}${mine.length ? ` · yours: ${names(mine)}` : ""}</span></div>`;
}
/* Manager details on a team card: record, style, how the standings move him, needs, and where his
   view of players differs from our projection. */
function managerHTML(t, needs) {
  const rec = (k, l) => `<label class="row" style="gap:4px">${l}<input type="number" id="rec-${k}-${t.id}" min="0" max="17" value="${t[k] ?? ""}" placeholder="0" data-act="trec" data-k="${k}" data-team="${t.id}" aria-label="${l === "W" ? "Wins" : l === "L" ? "Losses" : "Ties"}"></label>`;
  const mi = moodInfo(t);
  const recRow = `<div class="mgr-rec"><span class="label">Record</span>${rec("wins", "W")}${rec("losses", "L")}${rec("ties", "T")}${t.streak ? `<span class="sub">streak ${esc(t.streak)}</span>` : ""}${recordStr(t) && !t.mine ? `<span class="tag ${mi.cls}">${mi.word}</span>` : ""}</div>`;
  if (t.mine) return `<div class="mgr">${recRow}</div>`;
  const st = t.style ?? 0.5;
  const n = needs.by.get(t.id) || {}, lg = needs.lg;
  const short = POSITIONS.filter((pos) => n[pos] != null && lg[pos] != null && n[pos] < lg[pos] - 1.5).sort((a, b) => (n[a] - lg[a]) - (n[b] - lg[b]));
  const deep = POSITIONS.filter((pos) => n[pos] != null && lg[pos] != null && n[pos] > lg[pos] + 1.5);
  // where his view differs from ours: your players he'd overrate (sell), his players he underrates (buy)
  const cB = perspective(ctx, t), me = myTeam();
  const gap = (id) => cB.ppg.q.get(id) - ctx.ppg.a.get(id);
  const usable = (id) => pl(id) && ctx.val.get(id).plays && ctx.ppg.a.get(id) >= 5;
  const over = me && me !== t ? me.roster.filter(usable).map((id) => [id, gap(id)]).filter((x) => x[1] >= 1).sort((a, b) => b[1] - a[1]).slice(0, 2) : [];
  const under = t.roster.filter(usable).map((id) => [id, gap(id)]).filter((x) => x[1] <= -1).sort((a, b) => a[1] - b[1]).slice(0, 2);
  const nm = ([id, g]) => `${esc(pl(id).n)} <span class="num">${sgn(g)}</span>`;
  const edgeTxt = recordStr(t) ? `${mi.word} at ${recordStr(t)}: needs ${sgn(mi.edge, 2)} pts/wk of edge to say yes (league setting ${sgn(+state.settings.stubborn, 2)}).` : "Add a record to factor in the standings.";
  return `<div class="mgr">
    ${recRow}
    <label class="field"><span class="label">Manager: <span class="num">${styleWord(st)}</span></span>
      <input type="range" id="style-${t.id}" min="0" max="1" step="0.1" value="${st}" data-act="tstyle" data-team="${t.id}" aria-label="Casual to dedicated">
      <span class="mgr-ends"><span>Casual: results and big names</span><span>Dedicated: rankings, projections, usage</span></span></label>
    <div class="row" style="align-items:end;gap:8px 14px">
      <label class="field" style="flex:1 1 9em"><span class="label">Favorite NFL team</span>
        <select id="fav-${t.id}" data-act="tfav" data-team="${t.id}"><option value="">None</option>${Object.keys(DB.teams || {}).sort().map((k) => `<option value="${k}" ${t.fav === k ? "selected" : ""}>${k} ${NFL_NAMES[k] || ""}</option>`).join("")}</select></label>
      ${t.fav ? `<label class="field" style="flex:2 1 12em"><span class="label">Fan level: <span class="num">${fanWord(t.fan)}</span></span><input type="range" id="fan-${t.id}" min="0" max="1" step="0.1" value="${t.fan ?? 0.5}" data-act="tfan" data-team="${t.id}" aria-label="Fan level"><span class="mgr-ends"><span>Barely follows</span><span>Diehard</span></span></label>` : ""}
    </div>
    <div class="mgr-facts">
      <div class="notice">${edgeTxt}</div>
      ${fanFact(t)}
      ${short.length || deep.length ? `<div>${short.length ? `<b>Needs</b> ${short.map((pos) => `${chipOf(pos)}`).join(" ")}` : ""}${short.length && deep.length ? " · " : ""}${deep.length ? `<b>Deep at</b> ${deep.map((pos) => `${chipOf(pos)}`).join(" ")}` : ""} <span class="sub">starters vs league average this week</span></div>` : ""}
      ${over.length ? `<div><b>Would overrate</b> of yours: ${over.map(nm).join(", ")} <span class="sub">pts/g above our projection: sell to him</span></div>` : ""}
      ${under.length ? `<div><b>Underrates</b> on his roster: ${under.map(nm).join(", ")} <span class="sub">buy from him</span></div>` : ""}
    </div>
  </div>`;
}
function renderTeams() {
  const el = $("#panel-teams");
  const wk = +state.settings.curWeek;
  const needs = leagueNeeds();
  const cards = state.teams.map((t) => {
    const td = teamDepth(ctx, t);
    const lw = lineupForWeek(ctx, t.roster, "a", wk, td), starters = new Set(lw.ids);
    const va = perWeek(teamValue(ctx, t.roster, "a", true, td)), vq = perWeek(teamValue(perspective(ctx, t), t.roster, "q", true, td));
    const rows = t.roster.map((id) => {
      const p = pl(id);
      if (!p) return `<tr><td colspan="6" class="muted">Unknown player (${esc(id)})</td><td><button class="x" data-act="rm" data-team="${t.id}" data-id="${esc(id)}" aria-label="Remove">×</button></td></tr>`;
      return `<tr>
        <td>${starters.has(id) ? '<i class="starter-dot" title="Starts this week"></i>' : '<i class="bench-dot" title="Bench this week"></i>'}${chipOf(p.p)}</td>
        <td style="min-width:0"><span class="pname">${esc(p.n)}</span> ${injTag(p)}<br><span class="sub">${p.t} · bye ${byeOf(p)}</span></td>
        <td class="n">${fmt(ctx.ppg.a.get(id))}</td><td class="n muted">${fmt(ctx.ppg.q.get(id))}</td>
        <td><input type="number" id="out-${id}" min="0" max="${state.settings.lastWeek}" placeholder="${autoOutOf(p) ?? "–"}" value="${state.out[id] ?? ""}" data-act="out" data-id="${id}" title="${autoOutOf(p) != null ? esc(`Out through week ${autoOutOf(p)}: ${(injInfo(p) || {}).why || "injury report"}. Type a week to change it.`) : "Last week he'll miss. Leave blank if healthy."}" aria-label="Out through week"></td>
        <td><button class="x" data-act="rm" data-team="${t.id}" data-id="${id}" aria-label="Remove ${esc(p.n)}">×</button></td></tr>`;
    }).join("");
    const confirming = ui.confirm === "del-" + t.id;
    return `<div class="box team ${t.mine ? "is-mine" : ""}">
      <div class="team-head">
        <input type="text" id="name-${t.id}" value="${esc(t.name)}" data-act="tname" data-team="${t.id}" aria-label="Team name">
        ${t.mine ? '<span class="tag mine">My team</span>' : `<button class="btn small ghost" data-act="mine" data-team="${t.id}">Set as mine</button>`}
        ${confirming ? `<span class="confirm">Delete team? <button class="btn small danger" data-act="delTeam" data-team="${t.id}">Delete</button><button class="btn small" data-act="cancel">Keep</button></span>` : `<button class="x" data-act="askDel" data-team="${t.id}" aria-label="Delete team">×</button>`}
      </div>
      ${t.owner ? `<div class="sub" style="margin-top:-6px">${esc(t.owner)}</div>` : ""}
      <div class="team-stats"><span>Lineup <b>${fmt(va)}</b> pts/wk</span><span>Market sees <b>${fmt(vq)}</b></span><span>${t.roster.length} players</span>${state.settings.faab ? `<label class="money-in" title="FAAB left">FAAB $<input type="number" id="faab-${t.id}" min="0" max="${state.settings.faabBudget}" value="${t.faab ?? ""}" placeholder="${state.settings.faabBudget}" data-act="tfaab" data-team="${t.id}" aria-label="FAAB left" style="width:4.4em"></label>` : ""}</div>
      ${lw.streamers.length ? `<div class="notice" style="margin-top:-4px">Week ${wk}: a free agent ${lw.streamers.join(", ")} beats this roster's options, so the lineup counts a streamer.</div>` : ""}
      ${managerHTML(t, needs)}
      <div class="tablewrap"><table class="roster"><thead><tr><th></th><th>Player</th><th class="n" title="Our projection, points per game">Proj</th><th class="n" title="What the market sees, points per game">Mkt</th><th title="Out through week">Out thru</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="6" class="muted">No players yet.</td></tr>`}</tbody></table></div>
      <div class="row"><input type="text" class="wide" id="add-${t.id}" list="playerList" placeholder="Add a player: start typing a name" data-act="add" data-team="${t.id}" style="flex:1"></div>
    </div>`;
  }).join("");
  el.innerHTML = `${exampleBanner()}<div class="row" style="margin-bottom:6px"><h2>Teams</h2><span class="spacer"></span><button class="btn primary" data-act="addTeam">Add team</button></div>
    <p class="lede">${state.espn ? "Rosters come from your ESPN import; edits here last until the next import." : "Enter each team's roster, or import it from ESPN on the League tab."} <i class="starter-dot"></i>marks this week's starters. Each manager's card has his record, a casual-to-dedicated slider and his favorite NFL team, which change how he sizes up trades. <b>Out thru</b> is the last week a player will miss. Grey numbers are filled in automatically from expected return dates, the NFL's 4-game IR minimum and injury news (hover for the reason). Type a week to change it.</p>
    ${state.teams.length ? `<div class="grid cols-3">${cards}</div>` : emptyLeague()}`;
}

/* ---------------- PLAYERS ---------------- */
/* Expected carries / targets / attempts in the current week (or his next game), with teammates' injuries. */
function oppNow(p) {
  const U = ctx.val.usage, T = (DB.teams || {})[p.t];
  if (!U || !T || !p.m) return null;
  const v = ctx.val.get(p.id);
  let wi = v.avail.findIndex(Boolean);
  if (wi < 0) return null;
  const w = U.weeks[wi], d = [T.or, T.ot, T.op];
  for (const q of U.byTeam.get(p.t) || []) {
    const o = U.outNow.get(q.id);
    if (q.id === p.id || !(o != null && w <= o)) for (let c = 0; c < 3; c++) d[c] += q.m[c];
  }
  const car = d[0] > 0 ? (T.r * p.m[0]) / d[0] : 0, tgt = d[1] > 0 ? (T.t * p.m[1]) / d[1] : 0, att = d[2] > 0 ? (T.p * p.m[2]) / d[2] : 0;
  return p.p === "QB" ? { att, car: att * p.m[11], tgt: 0, w } : { car, tgt, att: 0, w };
}
/* A kicker's or defense's expected stat line this week, from the builder (DB.kdst), in words and a small table. */
function kdWeekHTML(p) {
  const w = +state.settings.curWeek, v = p.kw && p.kw[w];
  if (!v) return "";
  const sc = state.settings.scoring, T = (DB.teams || {})[p.t], opp = (DB.opp || {})[p.t];
  const imp = (t) => { const e = (DB.teams || {})[t] && DB.teams[t].env && DB.teams[t].env[w]; return e ? e[2] : null; };
  const row = (l, x, pts) => `<tr><td>${l}</td><td class="n">${x}</td><td class="n muted">${pts == null ? "" : sgn(pts, 2)}</td></tr>`;
  if (p.p === "K") {
    const pat = v[0] + v[1], fga = v[2] + v[3] + v[4] + v[5] + v[6] + v[7] + v[8], made = v[2] + v[3] + v[4] + v[5];
    const pts = (i, k) => v[i] * (+kdSet(sc, k) || 0);
    const missPts = (v[6] + v[7] + v[8]) * (+kdSet(sc, "fgMiss") || 0) + v[6] * (+kdSet(sc, "fgMiss0") || 0) + v[7] * (+kdSet(sc, "fgMiss40") || 0) + v[8] * (+kdSet(sc, "fgMiss50") || 0);
    return `<div class="stack" style="gap:6px"><div class="label">Week ${w}${opp ? ` vs ${esc(opp)}` : ""}: what he's expected to kick</div>
      <table class="mini"><tbody>${row("PATs made", `${fmt(v[0], 2)} of ${fmt(pat, 2)}`, pts(0, "patMade") + pts(1, "patMiss"))}
      ${row("Field goals made 0–39", fmt(v[2], 2), pts(2, "fg0"))}${row("40–49", fmt(v[3], 2), pts(3, "fg40"))}${row("50+", fmt(v[4] + v[5], 2), pts(4, "fg50") + pts(5, "fg60"))}
      ${row("Field goals missed", fmt(v[6] + v[7] + v[8], 2), missPts)}</tbody></table>
      <p class="notice" style="margin:0">${esc(p.t)} ${imp(p.t) != null ? `is implied for ${fmt(imp(p.t))} points` : "has no line yet"}: more points mean more PATs, while field-goal tries barely move with the total (favorites kick a few more). ${fmt(fga, 1)} tries expected, ${pct(fga > 0 ? made / fga : 0)} made at his distances (his own makes and mix, pulled toward the league's).</p></div>`;
  }
  const g = (k) => +kdSet(sc, k) || 0, pt = kdSet(sc, "paTier") || [], yt = kdSet(sc, "yaTier") || [];
  const paPts = PA_TIERS.reduce((a, _, i) => a + v[9 + i] * (+pt[i] || 0), 0) + v[7] * g("ptsAllowed");
  const yaPts = YA_TIERS.reduce((a, _, i) => a + v[18 + i] * (+yt[i] || 0), 0) + v[8] * g("ydsAllowed");
  const tiers = PA_TIERS.map((l, i) => ({ l, p: v[9 + i] })).filter((x) => x.p >= 0.05).map((x) => `${x.l}: ${pct(x.p)}`).join(" · ");
  return `<div class="stack" style="gap:6px"><div class="label">Week ${w}${opp ? ` vs ${esc(opp)}` : ""}: what the defense is expected to do</div>
    <table class="mini"><tbody>${row("Sacks", fmt(v[0], 2), v[0] * g("sack"))}${row("Interceptions", fmt(v[1], 2), v[1] * g("dInt"))}${row("Fumble recoveries", fmt(v[2], 2), v[2] * g("fumRec"))}
    ${row("Defensive and return TDs", fmt(v[4] + v[5], 2), v[4] * g("dTd") + v[5] * g("stTd"))}${row("Safeties, blocked kicks", fmt(v[3] + v[6], 2), v[3] * g("safety") + v[6] * g("blk"))}
    ${row("Points allowed", fmt(v[7], 1), paPts)}${row("Yards allowed", fmt(v[8], 0), yaPts)}</tbody></table>
    <p class="notice" style="margin:0">${opp ? `${esc(opp)} ${imp(opp) != null ? `is implied for ${fmt(imp(opp))} points` : "has no line yet"}.` : ""} Points allowed this week: ${tiers}. A weak offense gives up more sacks and turnovers; so does one whose team trails (the defense's team favored). Each defense's and offense's own rates count too, pulled toward the league's.</p></div>`;
}
function wkNow(p) {
  const v = ctx.val.get(p.id);
  if (!v || !v.avail.length || !v.avail[0]) return null;
  return ctx.wkA.get(p.id)[0];
}
function extOf(id) { return (state.espn && state.espn.players && state.espn.players[id]) || null; }
function adpOf(p) { const x = extOf(p.id); return x && x.adp ? x.adp : p.dr != null ? p.dr : null; }
function rostOf(p) { const x = extOf(p.id); return x && x.rost != null ? x.rost : p.own != null ? p.own : null; }
function renderPlayers() {
  const el = $("#panel-players");
  const P = ui.players;
  const q = P.q.trim().toLowerCase();
  let list = DB.players.filter((p) => (!P.pos || p.p === P.pos) && (!q || p.n.toLowerCase().includes(q) || p.t.toLowerCase() === q)
    && (P.own === "all" || (P.own === "fa" ? !owner.has(p.id) : owner.has(p.id))));
  const big = 1e6;
  const plays = (p) => ctx.val.get(p.id).plays;
  const val = (p) => P.sort === "a" ? (plays(p) ? ctx.ppg.a.get(p.id) : -1) : P.sort === "wk" ? wkNow(p) ?? -1 : P.sort === "q" ? ctx.ppg.q.get(p.id) : P.sort === "gap" ? (plays(p) ? ctx.ppg.a.get(p.id) - ctx.ppg.q.get(p.id) : -99)
    : P.sort === "ow" ? (plays(p) ? overWaiver(ctx, p.id) ?? -99 : -99) : P.sort === "er" ? -(p.er ?? big) : P.sort === "adp" ? -(adpOf(p) ?? big) : P.sort === "rost" ? (rostOf(p) ?? -1) : 0;
  list.sort((x, y) => P.sort === "n" ? x.n.localeCompare(y.n) * P.dir : (val(y) - val(x)) * -P.dir);
  const shown = list.slice(0, 150);
  const th = (k, l, n, title) => `<th class="sortable ${n ? "n" : ""}" data-act="psort" data-k="${k}" ${title ? `title="${esc(title)}"` : ""}>${l}${P.sort === k ? (P.dir < 0 ? " ↓" : " ↑") : ""}</th>`;
  const espnAdp = state.espn && Object.values(state.espn.players || {}).some((x) => x.adp);
  const rows = shown.map((p) => {
    const a = ctx.ppg.a.get(p.id), qv = ctx.ppg.q.get(p.id), gap = a - qv, o = state.overrides[p.id];
    const x = extOf(p.id), adp = adpOf(p), rost = rostOf(p);
    const wn = wkNow(p), vv = ctx.val.get(p.id), playsRos = vv.plays, ow = overWaiver(ctx, p.id);
    return `<tr class="clickable ${P.sel === p.id ? "sel" : ""}" data-act="psel" data-id="${p.id}">
      <td>${chipOf(p.p)}</td><td><span class="pname">${esc(p.n)}</span> ${injTag(p)}${o ? ' <span class="tag q" title="You set a custom number">edited</span>' : ""}${vv && vv.roleChanged ? ` <span class="tag role" title="Teammate injuries change his workload">${vv.roleShift > 0 ? "role ↑" : "role ↓"}</span>` : ""}<div class="sub">${p.t} · bye ${byeOf(p)}</div></td>
      <td class="n">${wn == null ? `<span class="muted">${(DB.byes[p.t] || []).includes(+state.settings.curWeek) ? "bye" : "out"}</span>` : fmt(wn)}</td>
      <td class="n">${playsRos ? fmt(a) : '<span class="muted">out</span>'}</td>
      <td class="n ${ow == null ? "muted" : ow >= 1 ? "" : "muted"}" title="Points per game over the streamer you could pick up at ${POSL(p.p)}">${playsRos && ow != null ? sgn(ow) : "–"}</td>
      <td class="n muted">${fmt(qv)}</td>
      <td class="n ${!playsRos ? "muted" : gap > 0.5 ? "good" : gap < -0.5 ? "bad" : "muted"}">${playsRos ? sgn(gap) : "–"}</td>
      <td class="n" title="${p.er ? `Expert std dev ${p.es ?? "–"} spots` : "Not in the expert rankings"}">${p.er ? p.p + p.er : "–"}</td>
      <td class="n">${adp != null ? (x && x.adp ? fmt(adp) : "#" + adp) : "–"}</td>
      <td class="n">${rost != null ? fmt(rost, rost >= 99.5 ? 1 : 0) + "%" : "–"}</td>
      <td class="sub owner-cell" title="${owner.has(p.id) ? esc(owner.get(p.id).name) : "Free agent"}">${owner.has(p.id) ? esc(owner.get(p.id).name) : "Free agent"}</td></tr>`;
  }).join("");
  el.innerHTML = `${exampleBanner()}<h2>Players</h2>
    <p class="lede"><b>Wk ${state.settings.curWeek}</b> is this week's projection and <b>Proj</b> the rest-of-season average: a usage model that shifts work when teammates are hurt and adjusts for each game's Vegas line, blended with the expert consensus (kickers and defenses: from the line, their own rates and their opponents'). <b>Mkt</b> is what a typical manager sees: season stats, form, position rank, the last two seasons, draft cost, roster and start rates${state.espn ? ", and ESPN's projection" : ""}. <b>Over FA</b> is how much better he is than the free agent you could stream at his position each week: most quarterbacks and tight ends are close to zero. A positive <b>Gap</b> means the market undervalues him. Click a player for the breakdown and his value to each team.</p>
    <div class="grid players-grid">
      <div class="box stack" style="min-width:0">
        <div class="row">
          <input type="search" id="pSearch" placeholder="Search name or NFL team" value="${esc(P.q)}" data-act="psearch" style="flex:1;min-width:10em">
          <select id="pPos" data-act="ppos"><option value="">All positions</option>${POSITIONS.map((x) => `<option value="${x}" ${P.pos === x ? "selected" : ""}>${POSL(x)}</option>`).join("")}</select>
          <select id="pOwn" data-act="pown"><option value="all" ${P.own === "all" ? "selected" : ""}>Everyone</option><option value="fa" ${P.own === "fa" ? "selected" : ""}>Free agents</option><option value="ros" ${P.own === "ros" ? "selected" : ""}>Rostered</option></select>
        </div>
        <div class="tablewrap"><table><thead><tr><th></th>${th("n", "Player")}${th("wk", "Wk " + state.settings.curWeek, 1, "Our projection for this week, with teammates' injuries")}${th("a", "Proj", 1, "Our projection, points per game for the rest of the season (weeks he plays)")}${th("ow", "Over FA", 1, "Points per game over the free agent you could stream at his position. This is what he's really worth to a lineup.")}${th("q", "Mkt", 1, "Market view, points per game")}${th("gap", "Gap", 1, "Proj minus Mkt")}${th("er", "Experts", 1, "FantasyPros rest-of-season consensus position rank")}${th("adp", "ADP", 1, espnAdp ? "ESPN average draft position (pick number); # = preseason consensus rank where ESPN has none" : "Preseason consensus draft rank (FantasyPros), used where ESPN ADP isn't imported")}${th("rost", "Rost", 1, state.espn ? "ESPN percent rostered" : "Percent rostered, average across ESPN and Yahoo")}<th>Owner</th></tr></thead><tbody>${rows}</tbody></table></div>
        ${list.length > shown.length ? `<p class="notice" style="margin:0">Showing ${shown.length} of ${list.length}. Search to narrow.</p>` : ""}
      </div>
      <div class="box stack" id="playerDetail" style="position:sticky;top:calc(env(safe-area-inset-top, 0px) + 12px)">${playerDetail()}</div>
    </div>`;
}
const SIG_LABEL = { season: "Season average", form: "Form, last 2 games", prk: "PRK, position rank by points", track: "Track record, last 2 seasons", adp: "ADP, draft cost", rost: "Roster %", start: "Start %", espn: "ESPN projection", experts: "Expert rank", news: "Injury news" };
function sigNote(k, s, p) {
  const hot = s.raw0 != null && Math.abs(s.raw0 - s.v) >= 0.1 ? ` · ${fmt(s.raw0)} before regressing a small sample` : "";
  if (k === "season") return `${p.g26} game${p.g26 === 1 ? "" : "s"}${hot}`;
  if (k === "form") return hot.replace(/^ · /, "");
  if (k === "experts") return `FantasyPros ${POSL(p.p)}${s.rank}`;
  if (k === "track") {
    const yr = (y, g) => y != null && g > 0 ? `${fmt(y)} in ${g} g` : "";
    return [s.y25 != null && s.g25 ? "2025 " + yr(s.y25, s.g25) : "", s.y24 != null && s.g24 ? "2024 " + yr(s.y24, s.g24) : ""].filter(Boolean).join(" · ")
      + ` · ${POSL(p.p)}${s.rank}${s.full >= 0.95 ? " · steadies his market view" : ""}`;
  }
  if (k === "prk") return `${POSL(p.p)}${s.rank}${s.src === "ESPN" ? " on ESPN" : ""}${hot}`;
  if (k === "adp") return s.src === "ESPN" ? `pick ${fmt(s.raw)} on ESPN · ${POSL(p.p)}${s.rank}` : `preseason #${s.raw} · ${POSL(p.p)}${s.rank}`;
  if (k === "rost" || k === "start") return `${fmt(s.raw, 1)}%${s.ties > 3 ? ` · tied with ${s.ties - 1} others` : ""}`;
  if (k === "news") return `role ${s.shift > 0 ? "+" : "−"}${fmt(Math.abs(s.shift))} pts/g with teammates out`;
  return "";
}
/* A small bar per remaining week: projected points if he plays, marked when he's out or on bye. */
/* Trade value: what managers think a player is worth in a trade, and how it's built. */
function tradeValueHTML(p) {
  const m = ctx.mkt;
  if (!m) return "";
  const id = p.id, x = m.parts.get(id), mu = m.mu.get(id), plays = ctx.val.get(id).plays;
  const qt = ["QB", "TE", "K", "DST"].includes(p.p);
  const sf = p.p === "QB" && m.b > 0.5;
  const own = state.overrides[id] && state.overrides[id].q != null && state.overrides[id].q !== "";
  const c = own ? 0 : m.c;
  const rank = x.listed ? `#${Math.round(x.eo)} overall` : `about #${Math.round(x.eo)} overall, estimated from his position rank`;
  const sigTxt = x.sig <= 0 ? `he's ${fmt(-x.sig)} market pts below a replacement ${POSL(p.p)}` : qt ? `${fmt(x.sig)}, the price of his rank at ${POSL(p.p)}` : `${fmt(x.sig)} market pts over a replacement ${POSL(p.p)}`;
  const how = sf ? `Your league starts two quarterbacks, so QBs are priced at their full market points.`
    : `${pct(1 - c)} from the market signals (${sigTxt})${c > 0 ? ` and ${pct(c)} from the consensus overall rankings (${rank}: ${fmt(x.con)})` : own ? ", because you set his market view" : ""}.`;
  const prem = x.prem > 0.005 ? ` Proven-player premium: +${fmt(x.prem)}, for ${x.proven >= 0.95 ? "two good seasons" : "a good track record"} backing his value.` : "";
  return `<div class="row" style="margin-top:4px"><span class="label">Trade value</span><span class="spacer"></span><span class="num">${plays ? fmt(Math.max(0, mu)) + " pts/wk" : "none while out"}</span></div>
    <p class="notice" style="margin:0">What managers think he's worth in a trade, per week he plays, over a replacement ${POSL(p.p)}. ${how}${prem}</p>`;
}

function weeklyHTML(p, v) {
  const wk = ctx.wkA.get(p.id), weeks = ctx.weeks.map((x) => x.w), byes = DB.byes[p.t] || [];
  if (!wk || !weeks.length) return "";
  let mx = 1;
  for (let i = 0; i < weeks.length; i++) if (v.avail[i]) mx = Math.max(mx, wk[i]);
  const cur = wk[0];
  const cells = weeks.map((w, i) => {
    const bye = byes.includes(w), on = v.avail[i];
    const h = on ? Math.max(3, Math.round((wk[i] / mx) * 56)) : 0;
    const ev = !KD_POS.includes(p.p) && v.env && v.env[i];
    const tip = bye ? `Week ${w}: bye` : on ? `Week ${w}: ${fmt(wk[i])} pts${ev ? ` · offense ${ev.x >= 0 ? "+" : "−"}${Math.round(Math.abs(ev.x) * 100)}% vs usual${i > 0 ? " (projected)" : ""}` : ""}` : `Week ${w}: out`;
    const playoff = w >= +state.settings.playoffStart;
    return `<div class="wk-cell ${playoff ? "po" : ""}" title="${tip}" aria-label="${tip}">
      <div class="wk-plot">${on ? `<i class="${p.p}" style="height:${h}px"></i>` : `<span class="wk-off">${bye ? "B" : "out"}</span>`}</div>
      <div class="wk-n">${w}</div></div>`;
  }).join("");
  const onW = weeks.filter((_, i) => v.avail[i]);
  const lo = Math.min(...weeks.map((_, i) => (v.avail[i] ? wk[i] : Infinity))), hi = Math.max(...weeks.map((_, i) => (v.avail[i] ? wk[i] : -Infinity)));
  const summary = !onW.length ? "Out for the rest of the season." : hi - lo >= 1 ? `Ranges from ${fmt(lo)} to ${fmt(hi)} pts with matchups and teammates coming and going.` : `Steady around ${fmt(hi)} pts when he plays.`;
  return `<div class="stack" style="gap:6px"><div class="row"><span class="label">Week by week</span><span class="spacer"></span><span class="notice">${esc(summary)}</span></div>
    <div class="wk-strip" role="img" aria-label="Projected points by week">${cells}</div>
    <p class="notice" style="margin:0">Bar height = projected points that week. Shaded weeks are your playoffs. Hover a bar for the game environment.</p></div>`;
}
function playerDetail() {
  const id = ui.players.sel, p = id && pl(id);
  if (!p) return `<h3>Breakdown</h3><p class="muted" style="margin:0">Pick a player to see how his projection and market value are built, and how many points per week he adds to each team's lineup.</p>`;
  const o = state.overrides[id] || {};
  const v = ctx.val.get(id);
  let ctxRows = `<p class="muted" style="margin:0">Add teams to see what he's worth to each of them.</p>`;
  if (state.teams.length) {
    const cv = contextValues(ctx, id).map((x) => ({ ...x, d: perWeek(x.delta) })).sort((a, b) => b.d - a.d);
    const mx = Math.max(0.5, ...cv.map((x) => Math.abs(x.d)));
    ctxRows = cv.map((x) => `<div class="ctx-row"><span class="${x.has ? "pname" : ""}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(x.team.name)}${x.has ? " (owns)" : ""}</span><div><div class="bar ${x.has ? "own" : ""}" style="width:${Math.max(0, x.d) / mx * 100}%"></div></div><span class="num" style="text-align:right">${sgn(x.d, 2)}</span></div>`).join("");
  }
  const op = oppNow(p), kd = KD_POS.includes(p.p);
  const usage = op ? (p.p === "QB" ? `this week ~${fmt(op.att, 0)} pass attempts, ${fmt(op.car, 1)} carries` : `this week ~${fmt(op.car, 1)} carries, ${fmt(op.tgt, 1)} targets`) : "";
  const x = extOf(id);
  const ii = injInfo(p);
  const status = "";
  const staleExp = Math.abs(v.model - v.modelEcr) >= 0.5;
  const projRows = `<tr><td>${kd ? "Line-based model" : "Usage model"} <span class="sub">rest of season</span></td><td class="n">${fmt(v.model)}</td><td class="n muted"></td></tr>
    <tr><td>Expert consensus <span class="sub">${v.ranked ? `${POSL(p.p)}${p.er}${p.es != null ? (p.es < 0.05 ? ", unanimous" : `, std dev ${fmt(p.es)} spots`) : ""}` : `unranked (below ${POSL(p.p)}${(DB.rosN || {})[p.p] || ""})`} = ${fmt(v.expert)} pts/g</span></td><td class="n">${sgn(v.corr)}</td><td class="n muted">${pct(v.w)}</td></tr>`;
  const thisWeek = (() => {
    const e = v.env && v.env[0], out = [];
    if (!v.avail[0]) return "";
    if (kd) return kdWeekHTML(p) + (v.wkExp != null ? `<p class="notice" style="margin:0">FantasyPros weekly rank ${POSL(p.p)}${v.wkRank} (${fmt(v.wkExp)} pts) gets ${pct(state.settings.weeklyExpert ?? 0.25)} of this week's number.</p>` : "");
    if (e) out.push(`Week ${state.settings.curWeek} game: ${esc(p.t)} ${e.imp ? `implied for ${fmt(e.imp)} points, ` : ""}${e.x >= 0 ? "+" : "−"}${Math.round(Math.abs(e.x) * 100)}% vs their usual${Math.abs(e.s) >= 1 ? `, ${e.s > 0 ? "favored" : "underdog"} by ${fmt(Math.abs(e.s))}` : ""}.`);
    if (v.back && v.back[0] < 1) out.push(`First game back after missing time, so his share counts at ${pct(v.back[0])}.`);
    if (v.wkExp != null) out.push(`FantasyPros weekly rank ${POSL(p.p)}${v.wkRank} (${fmt(v.wkExp)} pts) gets ${pct(state.settings.weeklyExpert ?? 0.25)} of this week's number.`);
    return out.length ? `<p class="notice" style="margin:0">${out.join(" ")}</p>` : "";
  })();
  const roles = roleNotes(ctx, id);
  const roleHTML = roles.length ? `<div class="stack" style="gap:4px"><div class="label">Teammate injuries that change his role</div>${roles.slice(0, 4).map((r) => `<div class="role-row"><span><b>${esc(r.name)}</b> <span class="sub">${r.pos} · out ${r.thru >= 18 ? "for the season" : "thru wk " + r.thru}</span></span><span class="num ${r.delta > 0 ? "good" : "bad"}">${sgn(r.delta)} pts/g</span></div>`).join("")}<p class="notice" style="margin:0">${roles[0].delta > 0 ? "Points per game he gains while each is out." : "Points per game he loses while each is out."}${roles[0].thru < 18 ? " His workload shifts back when they return." : ""}</p></div>` : "";
  let den = 0;
  for (const k of SIGNALS) if (v.sig[k] && v.sig[k].wt) den += v.sig[k].wt;
  const mktRows = SIGNALS.map((k) => {
    const s = v.sig[k];
    if (!s) return `<tr class="muted"><td>${SIG_LABEL[k]}</td><td class="n">–</td><td class="n">–</td></tr>`;
    return `<tr><td>${SIG_LABEL[k]} <span class="sub">${esc(sigNote(k, s, p))}</span></td><td class="n">${fmt(s.v)}</td><td class="n muted">${s.wt && den ? pct(s.wt / den) : "0%"}</td></tr>`;
  }).join("");
  return `<div class="row">${chipOf(p.p)}<h3>${esc(p.n)}</h3>${injTag(p)}</div>
    <div class="sub" style="white-space:normal">${p.t} · bye ${byeOf(p)} · ${p.g26} games in 2026${usage ? " · " + esc(usage) : ""}</div>
    ${ii ? `<div class="callout ${ii.cls === "ir" ? "inj-callout" : ""}" style="padding:8px 12px"><b>${esc(ii.label)}</b>${ii.why ? ` <span class="notice">· ${esc(ii.why)}</span>` : ""}</div>` : ""}
    <div class="stack" style="gap:6px">
      <div class="row"><span class="label">Our projection</span><span class="spacer"></span><span class="num">${fmt(ctx.ppg.a.get(id))} pts/g${o.a != null ? " (yours)" : ""}</span></div>
      ${(() => { const ow = overWaiver(ctx, id); if (ow == null || state.settings.waiver === false) return ""; const who = (ctx.waiverWho[p.p] || []).slice(0, 3).map((x) => pl(x).n).join(", ");
        return `<div class="callout" style="padding:8px 12px"><b>${sgn(ow)} pts/g over a streamer.</b> <span class="notice">The ${["", "best", "second-best", "third-best", "fourth-best"][Math.min(4, +state.settings.waiverDepth || 2)]} free agent ${POSL(p.p)} projects ${fmt(ctx.waiverAvg.a[p.p])} pts/g${who ? ` (now: ${esc(who)})` : ""}. That is the most a lineup loses without him.</span></div>`; })()}
      <table class="mini"><tbody>${projRows}</tbody></table>
      ${thisWeek}
      <p class="notice" style="margin:0">The expert line moves the model toward the consensus by ${pct(v.w)} of the gap${staleExp ? ", measured against the injuries the experts knew about when they ranked (" + esc(fmtDate((DB.sources || {}).ros)) + "), so later news isn't undone by stale ranks" : ""}.${v.why ? " Expert share lowered: " + esc(v.why) + "." : ""}</p>
    </div>
    ${weeklyHTML(p, v)}
    ${roleHTML}
    <div class="stack" style="gap:6px">
      <div class="row"><span class="label">Market view</span><span class="spacer"></span><span class="num">${fmt(ctx.ppg.q.get(id))} pts/g${o.q != null ? " (yours)" : ""}</span></div>
      ${ctx.faAdj && ctx.faAdj.get(id) ? `<p class="notice" style="margin:0">Free agent in your league: every manager passed on him, so the market judges him by his projection on the market's scale (${fmt(ctx.faAdj.get(id).qm)}) rather than his signals below (${fmt(ctx.faAdj.get(id).q0)}).</p>` : ""}
      <table class="mini"><tbody>${mktRows}</tbody></table>
      <p class="notice" style="margin:0">Ranks are turned into points using this season's points by rank at ${POSL(p.p)}, blended with the model's until more games are played. Shares come from the weights on the League tab.</p>
      ${tradeValueHTML(p)}
    </div>
    <div><div class="label" style="margin-bottom:6px">Points per week he adds, by team</div><div class="stack" style="gap:6px">${ctxRows}</div>
    <p class="notice" style="margin:8px 0 0">For the team that owns him, the number is what they'd lose without him. Measured on our projection, rest of season, averaged per week.</p></div>
    <div class="stack"><div class="label">Your numbers (points per game)</div>
      <div class="row">
        <label class="field"><span class="hint">Projection</span><input type="number" step="0.1" id="ovA-${id}" placeholder="${fmt(v.actual)}" value="${o.a ?? ""}" data-act="ov" data-k="a" data-id="${id}"></label>
        <label class="field"><span class="hint">Market view</span><input type="number" step="0.1" id="ovQ-${id}" placeholder="${fmt(v.perceived)}" value="${o.q ?? ""}" data-act="ov" data-k="q" data-id="${id}"></label>
        <label class="field"><span class="hint">Out thru week</span><input type="number" id="ovOut-${id}" placeholder="${autoOutOf(p) ?? "–"}" value="${state.out[id] ?? ""}" data-act="out" data-id="${id}"></label>
        ${state.overrides[id] ? `<button class="btn small" data-act="ovReset" data-id="${id}" style="align-self:end">Reset</button>` : ""}
      </div>
      <p class="notice" style="margin:0">Leave a box empty to use the computed number shown in grey. Your edits are saved with the league and survive re-imports.</p></div>`;
}

/* ---------------- LEAGUE ---------------- */
const PRESETS = {
  ppr: { label: "PPR (ESPN default)", rec: 1 }, half: { label: "Half PPR", rec: 0.5 }, std: { label: "Standard", rec: 0 },
};
function renderLeague() {
  const S = state.settings, sc = S.scoring, sl = S.slots;
  const noByPos = !sc.byPos || !Object.keys(sc.byPos).length;
  const presetKey = Object.keys(PRESETS).find((k) => noByPos && sc.rec === PRESETS[k].rec && sc.passYd === 0.04 && sc.passTd === 4 && sc.int === -2 && sc.rushYd === 0.1 && sc.rushTd === 6 && sc.recYd === 0.1 && sc.recTd === 6 && sc.fumble === -2 && sc.twoPt === 2) || "custom";
  const num = (id, path, v, attrs = "") => `<input type="number" id="${id}" value="${v}" data-act="set" data-path="${path}" ${attrs}>`;
  const scoreFields = [["passYd", "Per passing yard"], ["passTd", "Passing TD"], ["int", "Interception"], ["rushYd", "Per rushing yard"], ["rushTd", "Rushing TD"], ["rec", "Reception"], ["recYd", "Per receiving yard"], ["recTd", "Receiving TD"], ["fumble", "Fumble lost"], ["twoPt", "2-pt conversion"]];
  const slotFields = [["QB", "QB"], ["RB", "RB"], ["WR", "WR"], ["TE", "TE"], ["RBWR", "RB/WR flex"], ["WRTE", "WR/TE flex"], ["FLEX", "FLEX (RB/WR/TE)"], ["OP", "Superflex (OP)"], ["K", "K"], ["DST", "D/ST"]];
  const kFields = [["patMade", "PAT made"], ["patMiss", "PAT missed"], ["fg0", "FG 0–39"], ["fg40", "FG 40–49"], ["fg50", "FG 50–59"], ["fg60", "FG 60+"], ["fgMiss", "FG missed"], ["fgMiss0", "Extra: missed 0–39"], ["fgMiss40", "Extra: missed 40–49"], ["fgMiss50", "Extra: missed 50+"]];
  const dFields = [["sack", "Sack"], ["dInt", "Interception"], ["fumRec", "Fumble recovered"], ["safety", "Safety"], ["dTd", "INT or fumble return TD"], ["stTd", "Kick or punt return TD"], ["blk", "Blocked kick"], ["ptsAllowed", "Per point allowed"], ["ydsAllowed", "Per yard allowed"]];
  const tierFields = (key, labels, unit) => labels.map((l, i) => `<label class="field"><span class="label">${l} ${unit}</span><input type="number" id="sc-${key}-${i}" step="0.5" value="${(kdSet(sc, key) || [])[i] ?? 0}" data-act="tier" data-key="${key}" data-i="${i}"></label>`).join("");
  const teRec = sc.byPos && sc.byPos.TE && sc.byPos.TE.rec != null ? sc.byPos.TE.rec : "";
  const P = S.perc;
  const pSum = SIGNALS.reduce((a, k) => a + (+P[k] || 0), 0) || 1;
  const hasEspn = !!state.espn;
  const sigHint = { season: "Points per game so far this season.", form: "Points per game over his last two games.", prk: "His position rank by total points this season (ESPN's PRK column).", adp: hasEspn ? "Where he went in ESPN drafts." : "Preseason consensus draft rank until you import ESPN.", rost: "Share of leagues that roster him. Counts less when many players are tied near 100%.", start: hasEspn ? "Share of leagues that start him." : "Comes with an ESPN import.", espn: hasEspn ? "ESPN's projection for him, averaged over the season and this week." : "Comes with an ESPN import.", experts: "FantasyPros rest-of-season consensus position rank. Managers read rankings too.", track: "Points per game over the last two seasons (last season counts double), as a position rank. A long record also makes a hot or cold start move him less.", news: "For backups and starters whose workload changes because a teammate is hurt: managers read injury news but only partly adjust. Uses our injury-adjusted projection." };
  const confirming = ui.confirm === "delLeague";
  const el = $("#panel-league");
  el.innerHTML = `${exampleBanner()}<h2>League</h2>
    <p class="lede">Bring your league in from ESPN, then fine-tune how players are valued. An import brings your scoring for kickers and defenses too; without one they use ESPN's standard rules.</p>
    <div class="stack" style="margin-bottom:14px">${importBoxHTML()}</div>
    <div class="grid cols-2" style="align-items:start">
      <div class="box stack">
        <h3>Player data</h3>
        <p style="margin:0">Stats through <b>Week ${DB.doneWeek ?? DB.curWeek - 1}</b>, rebuilt ${DB.builtAt ? esc(new Date(DB.builtAt).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })) : ""}. A scheduled refresh rebuilds it every Tuesday morning after Monday night's game (new stats, the latest expert rankings and roster rates, updated injury timelines), and again before Thursday night's game and on Sunday morning after the 1 pm inactives, for the latest injury news.</p>
        <p class="notice" style="margin:0">Your league's rosters, injury designations, start and roster rates come from ESPN whenever you import, so re-import any time for the latest. Current week in this league: ${state.settings.curWeek}${+state.settings.curWeek < +DB.curWeek ? ` <span class="bad">(the data is on week ${DB.curWeek}; update it under Basics or re-import)</span>` : ""}.</p>
      </div>
      <div class="box stack">
        <h3>Our projection</h3>
        ${""}<label class="field"><span class="label">Expert consensus weight: <span class="num">${pct(S.expertWeight)}</span>${S.expertAuto ? ' <span class="muted">(model default)</span>' : ""}</span><input type="range" id="set-expert" min="0" max="1" step="0.05" value="${S.expertWeight}" data-act="set" data-path="expertWeight"><span class="hint">How much of each projection comes from the FantasyPros rest-of-season consensus (rankings from many experts, ${esc(fmtDate(DB.sources && DB.sources.ros))}). The rest comes from the usage model. It drops automatically for players the experts disagree on. Backtested best: about 20%.</span></label>
        <label class="field"><span class="label">Weekly expert rankings, this week only: <span class="num">${pct(S.weeklyExpert ?? 0.25)}</span></span><input type="range" id="set-wexpert" min="0" max="1" step="0.05" value="${S.weeklyExpert ?? 0.25}" data-act="set" data-path="weeklyExpert"><span class="hint">FantasyPros weekly rankings fold in matchups and coaching news. ${DB.ewWeek ? `The data has them for Week ${DB.ewWeek}.` : "The current data doesn't have this week's rankings yet; the next refresh adds them."} Skipped for players with an injury tag, since their rank prices in the chance they sit.</span></label>
      </div>
      <div class="box stack">
        <h3>Waiver wire</h3>
        <label class="row" style="gap:8px"><input type="checkbox" id="set-waiver" data-act="waiver" ${S.waiver !== false ? "checked" : ""}>Count streaming from free agents</label>
        <label class="field"><span class="label">Who you'd get each week</span>
          <select id="set-wdepth" data-act="set" data-path="waiverDepth">${[1, 2, 3, 4].map((k) => `<option value="${k}" ${+S.waiverDepth === k ? "selected" : ""}>${["", "The best free agent", "The second-best (default)", "The third-best", "The fourth-best"][k]}</option>`).join("")}</select>
          <span class="hint">Every lineup can start a free agent at any position, so a player is only worth what he adds over that streamer. Pick deeper if your league is active on waivers.</span></label>
        <table class="mini"><tbody>${POSITIONS.map((pos) => `<tr><td>${chipOf(pos)}</td><td class="n">${fmt(ctx.waiverAvg.a[pos])} pts/g</td><td class="sub" style="white-space:normal">${esc((ctx.waiverWho[pos] || []).slice(0, 3).map((x) => pl(x).n).join(", "))}</td></tr>`).join("")}</tbody></table>
        <p class="notice" style="margin:0">Streaming level by position, rest of season (top free agents this week). ${!(state.teams.length >= +S.teams && state.teams.reduce((a, x) => a + x.roster.length, 0) >= +S.teams * 12) ? "Your rosters look incomplete, so players rostered in at least half of leagues are treated as taken." : "Free agents are players on no roster in this league."}</p>
      </div>
      <div class="box stack">
        <h3>Free agent budget (FAAB)</h3>
        <label class="row" style="gap:8px"><input type="checkbox" id="set-faab" data-act="faabOn" ${S.faab ? "checked" : ""}>This league bids on free agents</label>
        <label class="field"><span class="label">Starting budget</span><span class="money-in">$<input type="number" id="set-faabBudget" min="1" max="10000" value="${S.faabBudget}" data-act="set" data-path="faabBudget"></span></label>
        ${S.faab ? (() => { const pd = faabPerDollar(ctx), w = ctx.wSum;
          return `<p style="margin:0">Right now <b>$10 ≈ ${fmt((10 * pd + (myTeam() ? faabValue(ctx, myTeam(), 10).stream : 0)) / w, 2)} pts/wk</b> for ${myTeam() ? esc(myTeam().name) : "a team"}: ${fmt(pd, 2)} pts per dollar over the rest of the season from future breakouts, plus better weekly pickups. Teams average $${fmt(ctx.faabAvg, 0)} left.</p>
          <p class="notice" style="margin:0">Enter each team's remaining budget on the Teams tab (an ESPN import fills it in). Add dollars to either side of a trade on the Trade tab; the finder also suggests FAAB sweeteners for near misses. ESPN may not let you include FAAB in a trade; check your league's settings or ask your commissioner.</p>`; })() : `<p class="notice" style="margin:0">Turn this on if your league uses blind bidding. Budgets then change what each team can pick up, and FAAB can be added to trades.</p>`}
      </div>
      <div class="box stack">
        <h3>What the market looks at</h3>
        <p class="notice" style="margin:0">Relative weights for the signals behind each player's market value. A player missing a signal skips it and the rest rescale.</p>
        <div class="stack" style="gap:8px">${SIGNALS.map((k) => `<label class="field"><span class="label">${SIG_LABEL[k]}: <span class="num">${pct((+P[k] || 0) / pSum)}</span></span><input type="range" id="perc-${k}" min="0" max="0.5" step="0.05" value="${P[k]}" data-act="set" data-path="perc.${k}"><span class="hint">${sigHint[k]}</span></label>`).join("")}</div>
      </div>
      <div class="box stack">
        <h3>Basics</h3>
        <div class="fields" style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr))">
          <label class="field" style="grid-column:1/-1"><span class="label">League name</span><input type="text" class="wide" id="leagueName" value="${esc(state.name)}" data-act="lname"></label>
          <label class="field"><span class="label">Teams in league</span>${num("set-teams", "teams", S.teams, 'min="4" max="20"')}</label>
          <label class="field"><span class="label">Current week</span>${num("set-cur", "curWeek", S.curWeek, 'min="1" max="18"')}</label>
          <label class="field"><span class="label">Count through week</span>${num("set-last", "lastWeek", S.lastWeek, 'min="1" max="18"')}</label>
          <label class="field"><span class="label">Playoffs start</span>${num("set-po", "playoffStart", S.playoffStart, 'min="1" max="18"')}</label>
          <label class="field"><span class="label">Playoff week weight</span>${num("set-pow", "playoffWeight", S.playoffWeight, 'min="0" max="5" step="0.25"')}<span class="hint">1 = same as a regular week</span></label>
        </div>
        <h3 style="margin-top:6px">Starting lineup</h3>
        <div class="fields">${slotFields.map(([k, l]) => `<label class="field"><span class="label">${l}</span>${num("slot-" + k, "slots." + k, sl[k] || 0, 'min="0" max="4"')}</label>`).join("")}</div>
      </div>
      <div class="box stack">
        <div class="row"><h3>Scoring</h3><span class="spacer"></span>
          <select id="preset" data-act="preset">${Object.entries(PRESETS).map(([k, v]) => `<option value="${k}" ${presetKey === k ? "selected" : ""}>${v.label}</option>`).join("")}<option value="custom" ${presetKey === "custom" ? "selected" : ""}>Custom</option></select></div>
        <div class="fields" style="grid-template-columns:repeat(auto-fill,minmax(130px,1fr))">${scoreFields.map(([k, l]) => `<label class="field"><span class="label">${l}</span>${num("sc-" + k, "scoring." + k, sc[k], 'step="0.01"')}</label>`).join("")}
          <label class="field"><span class="label">Reception (TE)</span><input type="number" id="sc-teRec" step="0.05" value="${teRec}" placeholder="${sc.rec}" data-act="teRec"><span class="hint">Blank = same as everyone</span></label></div>
        <details><summary class="label" style="cursor:pointer">Kickers and defenses (D/ST)</summary>
          <div class="stack" style="margin-top:8px">
            <div class="fields" style="grid-template-columns:repeat(auto-fill,minmax(130px,1fr))">${kFields.map(([k, l]) => `<label class="field"><span class="label">${l}</span>${num("sc-" + k, "scoring." + k, kdSet(sc, k), 'step="0.5"')}</label>`).join("")}</div>
            <p class="notice" style="margin:0">"FG missed" counts every miss; the extras are on top, for leagues that charge more for short misses.</p>
            <div class="fields" style="grid-template-columns:repeat(auto-fill,minmax(130px,1fr))">${dFields.map(([k, l]) => `<label class="field"><span class="label">${l}</span>${num("sc-" + k, "scoring." + k, kdSet(sc, k), 'step="0.1"')}</label>`).join("")}</div>
            <div class="label">Points allowed</div>
            <div class="fields" style="grid-template-columns:repeat(auto-fill,minmax(90px,1fr))">${tierFields("paTier", PA_TIERS, "pts")}</div>
            <div class="label">Yards allowed</div>
            <div class="fields" style="grid-template-columns:repeat(auto-fill,minmax(90px,1fr))">${tierFields("yaTier", YA_TIERS, "yds")}</div>
            <p class="notice" style="margin:0">Points allowed leave out the other team's defensive touchdowns (a pick-six isn't on your defense) but count return touchdowns against your special teams, as ESPN does.</p>
          </div></details>
      </div>
      <div class="box stack">
        <h3>How managers judge trades</h3>
        <p class="notice" style="margin:0">These set the acceptance model. Tune them to your league: some leagues trade freely, some never do.</p>
        <label class="field"><span class="label">Lineup need vs trade value: <span class="num">${Math.round(S.needWeight * 100)}% need</span></span><input type="range" id="set-need" min="0" max="1" step="0.05" value="${S.needWeight}" data-act="set" data-path="needWeight"><span class="hint">0% = they only compare trade values. 100% = they only ask "does my lineup get better?"</span></label>
        <label class="field"><span class="label">Consensus rankings in trade talks: <span class="num">${pct(S.consensus ?? 0.5)}</span></span><input type="range" id="set-cons" min="0" max="1" step="0.05" value="${S.consensus ?? 0.5}" data-act="set" data-path="consensus"><span class="hint">How much a player's trade value follows the FantasyPros overall rankings (every position on one list) rather than the market signals. Either way, QBs and TEs are priced the way those rankings price them: in a one-QB league only the top few are worth much more than a streamer.</span></label>
        <label class="field"><span class="label">Proven-player premium: <span class="num">${pct(S.proven ?? DEFAULT_SETTINGS.proven)}</span></span><input type="range" id="set-proven" min="0" max="0.4" step="0.05" value="${S.proven ?? DEFAULT_SETTINGS.proven}" data-act="set" data-path="proven"><span class="hint">Extra trade value managers pay for a player who produced at this level for the last two seasons: they pay for certainty. Casual managers pay up to half again as much, dedicated ones half as much. Not applied to quarterbacks in one-QB leagues, where a streamer is always available.</span></label>
        <label class="field"><span class="label">Edge they need to say yes: <span class="num">${fmt(S.stubborn, 2)} pts/wk</span></span><input type="range" id="set-stub" min="-1" max="3" step="0.25" value="${S.stubborn}" data-act="set" data-path="stubborn"><span class="hint">A trade they see as this good is a coin flip. Raise it for a stubborn league.</span></label>
        <label class="field"><span class="label">How predictable they are: <span class="num">${fmt(S.spread, 2)}</span></span><input type="range" id="set-spread" min="0.5" max="4" step="0.25" value="${S.spread}" data-act="set" data-path="spread"><span class="hint">Lower = acceptance flips sharply around the edge. Higher = more randomness.</span></label>
        <label class="field"><span class="label">Attachment to their own players: <span class="num">×${fmt(S.attachment, 2)}</span></span><input type="range" id="set-att" min="1" max="1.6" step="0.05" value="${S.attachment}" data-act="set" data-path="attachment"><span class="hint">How much more a manager values players they already have.</span></label>
        <label class="field"><span class="label">How much the standings matter: <span class="num">${fmt(S.standings ?? 0.5, 2)} pts/wk</span></span><input type="range" id="set-standings" min="0" max="1.5" step="0.25" value="${S.standings ?? 0.5}" data-act="set" data-path="standings"><span class="hint">A winless manager needs this much less edge to say yes; an unbeaten one needs this much more. Early records count less. Each manager's record and style (casual to dedicated) are on the Teams tab.</span></label>
        <label class="row" style="gap:8px"><input type="checkbox" id="set-cushion" data-act="cushion" ${S.cushion ? "checked" : ""}>Count bench depth as injury insurance</label>
      </div>
      <div class="box stack">
        <h3>League data</h3>
        <div class="row">
          <button class="btn" data-act="sample">${state.example ? "Redraw sample league" : "Open sample league"}</button>
          ${confirming ? `<span class="confirm">Delete “${esc(state.name)}” and all its edits? <button class="btn small danger" data-act="doDelLeague">Delete</button><button class="btn small" data-act="cancel">Keep</button></span>` : `<button class="btn danger" data-act="askDelLeague">Delete this league</button>`}
        </div>
        <label class="field"><span class="label">Backup</span><textarea id="backup" spellcheck="false" placeholder="Paste a league backup here, then press Load backup.">${esc(JSON.stringify(state))}</textarea></label>
        <div class="row"><button class="btn" data-act="copyBackup">Copy backup</button><button class="btn" data-act="loadBackup">Load backup</button><span class="notice" id="backupMsg"></span></div>
      </div>
    </div>`;
}
function fmtDate(d) {
  if (!d) return "";
  const dt = new Date(d + "T12:00:00");
  return isNaN(dt) ? d : dt.toLocaleDateString([], { month: "short", day: "numeric" });
}

/* ---------------- METHOD ---------------- */
// kicker and D/ST backtest, 2024-26 (backtest/kdst_backtest.py --baselines): average miss, standard scoring
const KD_BT = { dst: 4.62, dstAvg: 5.10, k: 3.76, kAvg: 3.90 };
function renderMethod() {
  const src = DB.sources || {};
  $("#panel-method").innerHTML = `<div class="prose"><h2>How the numbers work</h2>
  <p class="lede">Two values per player, one lineup model per team, and an acceptance model built on the gap between them.</p>
  <h3>1. Our projection (Proj)</h3>
  <p>It starts from a <b>usage model</b> built around each team's work: carries by running backs, receivers and tight ends, targets, and quarterback pass attempts. Each player has a share weight for each pool. In any week, the pool is split among the players who are healthy, in proportion to their weights:</p>
  <div class="formula">his carries this week = team carries per game × his weight / sum of weights of healthy teammates (him included)
points = carries, targets, attempts × his efficiency per opportunity, scored with your settings</div>
  <p>That is what moves work to backups. When a starter is out, his weight drops out of the sum and the rest of the room splits his work by their own weights; when he returns, it shifts back. Aaron Jones carries most of Minnesota's backfield while Jordan Mason is out, then shares it. A quarterback's backup takes nearly all the passes only in weeks the starter misses. When a teammate misses just a week or two (not a stint on a reserve list), 30% of his carries and targets go to depth players we don't model instead of all of it going to the regulars; in past seasons the regulars gained less than a full split implies.</p>
  <p>The weights are fitted to this season's games, using who was actually active in each one, so a player's numbers while a teammate was out don't inflate his normal role. A starter hurt early in a game and placed on IR afterward counts as absent for that game. Recent games count more: each older week is weighted 10% less, so a role change shows up quickly. Last season's fitted shares, adjusted for age, act as a prior worth about 3 games (1.5 if he changed teams). Quarterbacks use the team's current depth chart instead, because a backup's past numbers come only from games he started.</p>
  <p><b>Efficiency</b> (yards and touchdowns per opportunity, catch rate) blends this season with last season at 80% weight and 2024 at 40%, then is pulled toward a typical rate for the position, most of all for touchdowns. For players with little history that typical rate is what low-volume players produce, not the league average: backup quarterbacks average 6.4 yards per attempt and a 2.9% touchdown rate against 7.3 and 4.8% for starters, and the same gap shows up for fringe running backs and receivers. A historically strong player off to a slow start keeps much of his track record.</p>
  <p><b>Game environment.</b> Each week's team volume and per-play production move with the Vegas line: the team's implied total compared with its usual level, and the spread. From 2,000+ team games in 2022–25, a team expected to score 10% more than usual throws for about 6% more yards and 7% more touchdowns and runs for 2% more yards; each point a team is favored by adds about 0.7% to its carries and takes 0.35% off its pass attempts. This week uses the actual line. Later weeks use power ratings fitted to this season's lines (offense, opponent defense, home field), with the effect scaled back to 74% because a line projected weeks ahead explains only part of the real one.</p>
  <div class="formula">team volume and yards per play this week × e^(elasticity · (implied ÷ usual − 1) + spread effect)</div>
  <p><b>First game back.</b> A player returning from a missed game gets 85% of his usual share that week; in past seasons players in their first game back scored about 20% below projection, mostly from fewer snaps.</p>
  <p><b>Age</b>: last season's numbers are adjusted by a positional aging curve before they're used (for example, −9% for a 28-year-old running back, −7% for a 30-year-old receiver, +5% for a 24-year-old receiver), and for veterans (running backs 28+, receivers and tight ends 30+, quarterbacks 35+) the past seasons also count 40% less.</p>
  <p>The model is then blended with the <b>expert consensus</b>: FantasyPros' rest-of-season rankings, which average many experts (${esc(fmtDate(src.ros))}). Averaging independent forecasts cancels much of their individual error, and a model and a crowd of humans make different mistakes. The rank is turned into points by reading off what the model projects for the player at that rank, and the gap is added to every week:</p>
  <div class="formula">projection(week) = model(week) + e · (expert points − model as of the experts' date)</div>
  <p>"As of the experts' date" means the model run with only the injuries the experts knew about. A backup whose starter got hurt after the rankings was ranked as a backup; measuring the gap that way keeps the stale rank from cancelling the news. <code>e</code> is the expert weight on the League tab (20% to start, the best weight in the backtest below). It shrinks when experts disagree about a player more than usual for his rank, falls to half for players they don't rank, and goes to zero for players out two or more weeks.</p>
  <p><b>Weekly rankings.</b> For the current week only, FantasyPros' weekly rankings (which fold in matchups and late news) are read off the same points-by-rank curve and get 25% of that week's number. They're skipped for players with an injury tag, whose rank prices in the chance they sit.</p>
  <p><b>How well it predicts.</b> The formula was replayed on every week of 2024–2026: each week projected from only the data before it, with each team's work split among the players who actually played. The changes above were tuned on 2024 and checked on 2025–26 (4,400 player-games): the average miss fell from 5.28 to 5.10 PPR points per player and the correlation with actual scores rose from 0.56 to 0.58, with every position improving. On Week 4 of 2026, as the page would have shown it on Oct 2, the average miss fell from 5.75 to 5.64 and the rank correlation rose from 0.47 to 0.51. FantasyPros' weekly rankings missed by 5.87 that week. Opponent defense against a position added nothing once the Vegas line was known, so it isn't used. A single week is mostly noise: the season-long numbers matter more.</p>
  <h3>1b. Kickers and defenses (K, D/ST)</h3>
  <p>They don't share a team's carries and targets, so they get their own model, built from the same Vegas lines:</p>
  <ul>
    <li><b>Kickers.</b> PAT tries rise with the team's implied total (about 0.15 per point); field-goal tries barely move with it (about 2 a game; favorites kick a few more). A team whose coach kicks more than the line says keeps part of that habit. Tries are split by distance (0–39, 40–49, 50–59, 60+) using his own mix, pulled toward the league's, and made at his own rate at each distance, pulled toward the league's rate there (attempts count three seasons back, older ones less). Then your league's kicking rules score the expected makes and misses.</li>
    <li><b>Defenses.</b> Sacks, interceptions and fumble recoveries come from the league's rates for the opponent's implied total (a weak offense gives up more) and the spread (an opponent that trails throws more), times the defense's own rate and the opposing offense's (both pulled toward average). Return touchdowns and blocked kicks use the league rate with a small team lean; defensive touchdowns follow takeaways. Points allowed start from the opponent's implied total with the spread of real games around it, so each points-allowed tier gets a probability (a 3% shutout chance pays your 0-points bonus about 3% of the time). Yards allowed come from the same line plus each side's yardage habits.</li>
  </ul>
  <p>Replaying 2024–26 week by week with only the data before each week, defenses missed by ${esc(fmt(KD_BT.dst, 2))} points per game against ${esc(fmt(KD_BT.dstAvg, 2))} for each defense's season average; kickers by ${esc(fmt(KD_BT.k, 2))} against ${esc(fmt(KD_BT.kAvg, 2))}. Kicking is mostly luck from week to week; the line and the kicker's leg are all there is to go on. The improvement loop tunes these settings every week like the rest of the model, and the scorecard grades them against FantasyPros.</p>
  <h3>2. What the market sees (Mkt)</h3>
  <p>A manager sizing up a player looks at a handful of numbers. Each is converted to points per game and averaged with the weights on the League tab:</p>
  <ul>
    <li><b>Season average</b> and <b>form</b> (last two games) come straight from the box scores.</li>
    <li><b>PRK</b> (position rank by total points), <b>ADP</b> (draft cost), <b>Roster %</b> and <b>Start %</b> are ranks or rates, so each is converted the same way: rank the players at his position on that signal, then take this season's points per game for that rank. Players tied on a rate share the average, and a rate where many players are tied near 100% counts less, because it can't tell them apart.</li>
    <li><b>Track record</b>: points per game over the last two seasons, last season counting double (a player needs about 6 games of it), converted like the ranks: a top-5 back the last two years reads as a top-5 back. It covers the name value of a player who has done it before.</li>
    <li><b>ESPN's projection</b> is used as is. It is often slow to catch up when a starter gets hurt.</li>
    <li><b>Expert rank</b>, the FantasyPros rest-of-season position rank, converted like the other ranks. Managers read rankings, and without them the market view ran almost entirely on early-season production.</li>
    <li><b>Injury news</b>, for players whose workload changes because of a teammate's injury, is our injury-adjusted projection. Managers react to news, but only partly, so it gets a modest weight.</li>
  </ul>
  <p><b>Small samples.</b> Managers know three games is a small sample. Season average, form and PRK are pulled toward what the market believed before them (draft cost, expert rank, ESPN's projection, roster and start rates, track record), with that prior counting like 3 games. A quarterback with a hot first month still looks good, but not like a top-5 starter.</p>
  <p><b>Proven players.</b> A player who produced for two full seasons has a sturdier prior: it counts like ${3 + TRACK_K} games instead of 3 (less for a shorter record), so a slow start costs a proven back much less market value, and a hot start from a career backup buys him less. Managers also pay a premium in trades for that certainty (the "proven-player premium" setting, ${pct(state.settings.proven ?? DEFAULT_SETTINGS.proven)} now): it scales with how long his record is and how much of his current value it backs up. This is how managers behave, not how players score: replaying 2024–26, players with strong track records did not beat our projections, and leaning harder on the last two seasons made the projections less accurate, so our own projection is unchanged. That gap is what makes proven names good players to sell.</p>
  <p><b>Free agents.</b> Every manager in your league passed on its free agents, so the market doesn't take a free agent's hot start at face value. It judges him by his projection, read on the market's own scale (the market points of whoever holds his projection rank), and never above his own signals. Without this, a deep league's best free-agent tight end with a big September looked better than tight ends managers actually start, and every trade value near the waiver line collapsed.</p>
  <p>Before an ESPN import, ADP is the FantasyPros preseason consensus draft rank (${esc(fmtDate(src.pre))}), roster % is the cross-platform average (${esc(fmtDate(src.own))}), and Start % and ESPN projection are skipped. After an import, all of them come from your league's ESPN data for every rostered player.</p>
  <h3>3. A player's value depends on the team</h3>
  <div class="formula">V(team) = Σ over weeks  weight(w) · E[best lineup in week w]
value of player P to team T = V(T with P) − V(T without P)</div>
  <p>Byes and "Out thru" weeks remove players from specific weeks. The lineup fills QB/RB/WR/TE (and K and D/ST, which only ever fill their own slots) first, then RB/WR and WR/TE flex, then FLEX, then superflex. With injury insurance on, each starter has a 7% chance to miss any week, so a good backup is worth something.</p>
  <p><b>The waiver wire.</b> Every lineup can also start a free agent at each position, every week. The streaming level is the second-best free agent at the position that week (players on no roster in your league who are healthy and not on bye). So losing a quarterback costs only the gap between him and the streamer, not his whole score. Most quarterbacks and tight ends sit only a point or two above what you can pick up; elite ones and the top running backs and receivers stay valuable because their waiver alternatives are weak. The same streaming level sets the replacement floor for trade values, so managers are assumed to know a streamer is available too. Week-specific streamers include backups who start because of injuries, for example a backup quarterback in the weeks his starter is out.</p>
  <h3>FAAB</h3>
  <p>When your league bids on free agents, budgets matter two ways, and both are added to a trade when dollars change hands:</p>
  <ul>
    <li><b>Better weekly pickups.</b> A team with an average budget gets the league's usual streamer (the second-best free agent). Twice the average budget gets the best one; an empty budget gets one pick deeper. This flows through the lineup model, so it's worth most to teams that stream quarterbacks and tight ends.</li>
    <li><b>Future breakouts.</b> Every season some waiver players become starters: a backup promoted by an injury, a rookie who takes the job. In 2024 and 2025, players outside the preseason consensus top 20 QB/TE, 50 RB and 70 WR who then produced like starters scored about ${esc(fmt(((DB.faabPool || {}).ppr || {})[String(Math.max(1, +state.settings.curWeek))] || 0, 0))} PPR points above a startable level from this week on. FAAB is what teams use to compete for them, so one dollar is worth that pool divided by all the budget left in your league. The pool shrinks as the season goes, and so does the value of a dollar.</li>
  </ul>
  <p>The acceptance model counts dollars the other manager receives at face value and is a little more reluctant to part with his own (the attachment setting). The trade finder tries adding your FAAB to near misses, up to 60% of what you have left, and on deals the other manager would accept easily it notes how much of his FAAB (up to half) you could also ask for.</p>
  <h3>4. Who wins, and will they accept?</h3>
  <p>"Real change" is the change in V for each side using our projections. When a team ends up with fewer players, it fills the open spot with the best free agent.</p>
  <div class="formula">they see  = need · ΔV_mkt(their team) + (1 − need) · (value in − attachment × value out)
P(accept) = 1 / (1 + e^−((they see per week − edge) / predictability))</div>
  <p><b>Trade value.</b> Managers don't trade on raw points. Consensus rankings put the top quarterback around 25th overall in a one-QB league, about one good RB2 or WR2, and price most tight ends barely above a streamer, because both positions are easy to stream. A manager won't give two real starters for an elite QB, however many points he scores. So each player gets a trade value per week, built from two halves (the split is the "consensus rankings" setting):</p>
  <ul>
    <li><b>From the market signals.</b> For RBs and WRs, his market points above the replacement-level starter at his position. For QBs and TEs, the signals only decide where he ranks at his position, and that rank is worth what the consensus pays for it. ${ctx && ctx.mkt && ctx.mkt.ladder ? `Right now the QB1 is worth ${esc(fmt(ctx.mkt.ladder.QB[0] || 0))} pts/wk, QB3 ${esc(fmt(ctx.mkt.ladder.QB[2] || 0))}, QB6 ${esc(fmt(ctx.mkt.ladder.QB[5] || 0))}; TE1 ${esc(fmt(ctx.mkt.ladder.TE[0] || 0))}, TE3 ${esc(fmt(ctx.mkt.ladder.TE[2] || 0))}.` : ""} Players near each other in market points share a price.</li>
    <li><b>From his overall consensus rank.</b> The FantasyPros rest-of-season PPR overall rankings (${esc(fmtDate(src.ros))}) put every position on one list. A rank is turned into points by matching running backs and receivers: the 10th RB or WR on the list gets the 10th-highest market points above replacement among RBs and WRs, and a QB or TE gets the value of the RBs and WRs ranked around him. Players outside the list get a rank estimated from their position rank.</li>
  </ul>
  <p>The rankings assume 12 teams, one QB and PPR, so values are rescaled to your league's scoring, roster size and TE premium. In superflex and two-QB leagues, quarterbacks are scarce and priced at their full market points instead. Players below replacement level keep their full shortfall, so a streamer never looks closer to a starter than he is. Trade values also drive the market side of lineup need at quarterback: a team's QB is valued at replacement plus his trade value, so an elite QB looks like a 5 or 6 point weekly upgrade over a streamer, not 12. Other positions use plain market points in the lineup math, so a starting tight end or running back still counts for his edge over the backup or the waiver wire. Out weeks count as zero.</p>
  <p><b>Loss aversion.</b> People weigh a loss about twice as heavily as an equal gain, so when the other manager sees a trade as a loss, that loss counts double in the acceptance formula. A deal they see as even is still possible; one they see as a clear loss rarely happens.</p>
  <div class="formula">felt = they see per week, doubled when it's negative
P(accept) = 1 / (1 + e^−((felt − edge) / predictability))</div>
  <p><b>Each manager is different.</b> Every other team has its own settings on the Teams tab:</p>
  <ul>
    <li><b>Casual to dedicated.</b> A casual manager goes by results: season average, recent games, position rank and track record count up to 75% more, a hot start is taken nearly at face value, and he pays up to half again the proven-player premium for big names. A dedicated manager reads expert rankings, ESPN's projections and injury news (up to 75% more weight), discounts small samples more (like 5 games of prior belief instead of 3), pays half the proven-player premium, and at the far end also sees what usage data says (our projection). Average uses the League-tab weights exactly. Everything a manager sees follows from his own view: which free agents he believes in, his replacement levels, the trade value of each player and his lineup math.</li>
    <li><b>Favorite NFL team and fan level.</b> A fan follows his team closely, so he sees its players close to their real value (our projection): a diehard goes ${Math.round(FAN_KNOW * 100)}% of the way from the market's view, a middling fan half that. He also values them a little extra (up to ${Math.round(FAN_PREMIUM * 100)}%). Selling a Cowboys fan an overhyped Cowboy is harder, and so is prying an underrated Cowboy away from him.</li>
    <li><b>Record.</b> A losing manager wants to shake things up: a winless one needs less edge to say yes (the "how much the standings matter" setting, ${esc(fmt(state.settings.standings ?? 0.5, 2))} pts/wk) and leans 10% more on this week's lineup; an unbeaten one needs that much more. A record counts in full after 4 games and partly before. ESPN imports fill records in; you can type them too.</li>
  </ul>
  <div class="formula">edge for him = edge − standings × mood      mood = 2 × (0.5 − win%) × min(1, games ÷ 4)</div>
  <p>The Teams tab also lists, for each manager, the positions where his starters trail the league, which of your players he'd overrate and which of his own he underrates, by his view against our projection. The trade finder can search any group of managers at once. The best trades to send are ones where your real change is positive and "they see" is positive too.</p>
  <h3>5. Injuries and absences</h3>
  <p>Each injured player gets a last week he's expected to miss, which removes him from those weeks of the lineup model. It comes from, in order of trust:</p>
  <ul>
    <li><b>ESPN's expected return</b>, when your league import includes one.</li>
    <li><b>News on major injuries</b>, checked each week (for example, a torn ACL ruled season-ending).</li>
    <li><b>CBS Sports' expected return week</b> from each team's injury page, plus this week's Out and Doubtful designations.</li>
    <li><b>The NFL's IR rule</b>: a player placed on injured reserve or PUP must miss at least four games, counted from the week he went on the list (byes don't count). This is a floor, not a forecast.</li>
  </ul>
  <p>The latest of these wins. A torn ACL or Achilles on IR with no return date is treated as season-ending. Questionable players and midweek practice absences don't count as missed games. Players out two or more weeks also drop the expert consensus from their projection, because expert ranks already count missed games. If ESPN shows a player active after an import, that overrides an older timeline. Your own "Out thru" entries always win.</p>
  <h3>6. ESPN import</h3>
  <p>Paste a league ID or any ESPN league link and the page builds the request to ESPN's league API (settings, teams and rosters). It reads team names and owners, every roster, your scoring (including a TE reception bonus), your lineup slots, the current week, playoff weeks, IR and injury designations, and each player's ADP, PRK, roster %, start % and ESPN projection. A link that includes <code>teamId=</code> also tells it which team is yours. Re-importing keeps your own numbers, "Out thru" entries and settings.</p>
  <h3>6b. Start/sit: floors, ceilings and the chance to win</h3>
  <p>A projection is an average. Two players projected for 11 points can have very different weeks: one gets 18 carries and almost always lands between 7 and 16; the other needs a long catch or a touchdown and lands anywhere from 2 to 25. Start/Sit turns every projection into a whole distribution by simulating each game a few thousand times, built from the same expected stat line as the projection:</p>
  <ul>
    <li><b>The game.</b> A passing-environment shock both teams share (a shootout, or wind and rain, moves both passing games) and a script shock that splits them (the team that leads runs more; the one that trails throws more).</li>
    <li><b>The team.</b> Its own swings in pass volume, rush volume and efficiency. Touchdowns move with efficiency.</li>
    <li><b>The player.</b> His role that week (his share of carries and targets moves around, and when one back gets more work his teammate gets less), a small chance he leaves the game early (his teammates absorb the rest), and his own efficiency.</li>
    <li><b>The plays.</b> Carries and targets are counted out (Poisson), catches come from targets, yards are the sum of the plays (each carry or catch with the spread measured from box scores: a carry's yards vary about 1.4 times their average, a receiver's catch about 0.8 times), and touchdowns, interceptions and fumbles are counted at their per-play rates.</li>
    <li><b>The quarterback.</b> His passing line is his receivers' receiving line, so a QB and his receivers rise and fall together and stacking them adds variance.</li>
  </ul>
  <p>The spread of each piece was fitted on 2024–26 games replayed with the same projection model, so the simulated weeks look like real ones: actual scores fall below the simulated 10th, 50th and 90th percentiles about 10%, 50% and 90% of the time, and when the simulation says a player has a 30% chance of 15 points, about 30% of them get there. Trained on 2024 only and tested on 2025–26, it beat a role-blind version (past players with the same projection) on every position. The mean is calibrated to what really happened: our projection is tuned to the smallest average miss, which puts it between a player's median and his average, so the simulated average sits a few percent above it, mostly from touchdowns.</p>
  <p><b>Injuries.</b> A player listed Questionable plays with the chance past Questionable regulars with the same final practice played (2023–25 injury reports): about 94% after a full practice, 75% after a limited one, 55% after missing practice, less if he missed his team's last game, and quarterbacks listed Questionable sit far more often. Doubtful players almost never play. When he sits, his work goes to his teammates in that simulated game. Once his team's inactives are out (90 minutes before kickoff) it's settled either way.</p>
  <p><b>Chance to win.</b> Your starters' simulated points are added up in every simulated week and compared with your opponent's likely lineup, kickers and defenses included. A kicker's PATs follow his own offense's simulated touchdowns, and a defense's points and yards allowed follow the offense it faces (in box scores they move with that offense's touchdowns and yards almost one for one), so starting a defense against your own quarterback costs you correlation. Sacks, takeaways, return touchdowns and field goals are counted out at their expected rates. The best lineup is found by swapping starters for bench players while the chance to win goes up. It usually matches the highest-projection lineup; it differs when a starter might not play, or when one player's range suits the matchup better: an underdog needs ceiling, a favorite needs floor.</p>
  <p><b>Floor vs ceiling.</b> The calculator answers one decision: who gives you the best chance of the points you need (or, with the players still to play on both sides, the best chance to win). The chart shows each player's chance of at least x points; where two lines cross is the target at which the steadier player stops being the better bet.</p>
  <p><b>What really sets a player's range.</b> His projection, his position, his game and the chance he sits. His style matters less than it looks: replaying 2024–26, players whose points lean on long plays and touchdowns had about the same week-to-week spread as volume players with the same projection (receivers who catch a high share of their targets were about 4% steadier, deep threats about 4% wilder, and even that didn't hold from one season to the next). At the same projection, running backs actually had a slightly higher floor and ceiling than receivers. So the high-volume back isn't capped: when you need 15, compare the chances, not the labels.</p>
  <p class="notice">Not modeled yet: opponent-specific matchups beyond the Vegas line, and live in-game scores (type the deficit yourself). In the backtest, a QB and his top receiver move together a little more in the simulation than in real games (0.45 vs 0.38), and opposing receivers a little less (0.05 vs 0.18).</p>
  <h3>Limits</h3>
  <p>Projections don't adjust for opponent strength beyond the Vegas line (a defense's and an offense's own sack and turnover rates excepted). A player new to the league since this data was built won't match on import until the data is refreshed. When you know something the data doesn't, type your own number on the Players tab.</p>
  <h3>7. Weekly updates</h3>
  <p>A scheduled task runs every Tuesday morning. It downloads the newest stats, rosters and schedule, the latest FantasyPros consensus and roster rates, reads every team's injury page, checks news on major injuries, rebuilds the player data and republishes this page at the same link. Your saved leagues and edits are untouched. The current week moves forward automatically.</p>
  <p>Two more runs bring the injury news up to kickoff: Thursday evening after the Thursday game's inactives (about 6:45 pm ET), and Sunday morning after the 1 pm inactives (about 11:30 am ET), with the final injury reports, Saturday's activations and every game-day inactive posted so far. The NFL's own Out and Doubtful designations count as missed games even before a team's injury page catches up.</p>
  <p class="notice">Sources: nflverse weekly stats, rosters, injury reports and schedule (${esc(DB.asOf)}); CBS Sports team injury pages and news reports (injury timelines, ${esc(fmtDate(src.inj))}); FantasyPros expert consensus via DynastyProcess (rest of season ${esc(fmtDate(src.ros))}, preseason ${esc(fmtDate(src.pre))}, roster % ${esc(fmtDate(src.own))}); ESPN league data when you import.</p></div>`;
}

/* ---------------- START / SIT ---------------- */
// Lineups are ranked by the chance to win the week (simulated games), not only by projected points; the
// floor-vs-ceiling calculator answers "who gives me the best shot at the points I need?"
ui.ss = { mine: "", opp: "", res: null, resFor: null, cands: [], need: 15, left: { mine: new Set(), theirs: new Set() }, kdst: false,
  calc: null, calcFor: null, board: null, boardFor: null, bpos: "", bown: "mine", bsort: "p", showBoard: false };
const SS_N = 4000, BOARD_N = 1500;
const kickOf = (p) => (DB.kick && DB.kick[p.t]) || null;
function kickTxt(p) {
  const k = kickOf(p);
  if (!k) return "";
  const d = new Date(k);
  return isNaN(d) ? "" : d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
}
function started(p) { const k = kickOf(p); return !!k && new Date(k).getTime() <= Date.now(); }
function playTxt(pp) {
  if (pp == null) return "";
  const c = pp < 0.5 ? "low" : pp < 0.9 ? "mid" : "";
  return `<span class="pplay ${c}" title="Chance he plays">${pp >= 0.995 ? "" : pct(pp)}</span>`;
}
function ssDefaults() {
  const S = ui.ss;
  if (!teamById(S.mine)) S.mine = (myTeam() || {}).id || "";
  if (!teamById(S.opp) || S.opp === S.mine) {
    // this week's ESPN matchup when the import has the schedule
    const sch = (state.espn && state.espn.schedule) || [];
    const m = sch.find((x) => +x.w === +state.settings.curWeek && (x.h === S.mine || x.a === S.mine));
    S.opp = m ? (m.h === S.mine ? m.a : m.h) : ((state.teams.find((t) => t.id !== S.mine) || {}).id || "");
  }
}
function rangeBar(sum, max, pos) {
  if (!sum) return "";
  const x = (v) => Math.max(0, Math.min(100, (v / max) * 100));
  return `<div class="rbar" title="10th–90th percentile ${fmt(sum.p10)}–${fmt(sum.p90)}, middle half ${fmt(sum.p25)}–${fmt(sum.p75)}, median ${fmt(sum.p50)}" role="img" aria-label="Range ${fmt(sum.p10)} to ${fmt(sum.p90)}, median ${fmt(sum.p50)}">
    <i class="r90 ${pos}" style="left:${x(sum.p10)}%;width:${Math.max(1, x(sum.p90) - x(sum.p10))}%"></i><i class="r50 ${pos}" style="left:${x(sum.p25)}%;width:${Math.max(1, x(sum.p75) - x(sum.p25))}%"></i><i class="med" style="left:calc(${x(sum.p50)}% - 1px)"></i></div>`;
}
/* His status this week as start/sit reads it (the same source as the chance he plays). */
function ssTag(p) {
  const st = weekStatus(ctx, p);
  if (st.gs) {
    const cls = /Out|Inactive|Doubtful/.test(st.gs) ? "ir" : st.gs === "Active" ? "soft" : "q";
    return `<span class="tag ${cls}" title="${esc(pPlay(ctx, p).why || st.gs)}">${esc(st.gs)}</span>`;
  }
  const i = injInfo(p);
  return i && i.eff != null ? injTag(p) : "";
}
/* Games already started: those players can't be moved. In or out comes from a this-week ESPN import when
   there is one (its lineup slot), otherwise from the highest-projection lineup. */
function lockedSets(team) {
  const locked = team.roster.filter((id) => pl(id) && started(pl(id)));
  const imp = state.espn && state.espn.importedAt, x = (id) => state.espn && state.espn.players && state.espn.players[id];
  const thisWeek = imp && DB.weekDates && new Date(imp) >= new Date((DB.weekDates[state.settings.curWeek] || "2000-01-01") + "T00:00:00") - 3 * 864e5;
  const lockedIn = thisWeek ? locked.filter((id) => x(id) && x(id).slot != null && x(id).slot !== 20 && x(id).slot !== 21) : null;
  return { locked, lockedIn, fromEspn: !!thisWeek };
}
function ssCompute() {
  const S = ui.ss, mine = teamById(S.mine), opp = teamById(S.opp);
  if (!mine) return;
  const t0 = performance.now();
  const ids = mine.roster.concat(opp ? opp.roster : []);
  const sim = simWeek(ctx, ids, { n: SS_N });
  const lk = lockedSets(mine);
  const res = startSit(ctx, mine, opp, { sim, locked: lk.locked, lockedIn: lk.lockedIn || [] });
  res.lk = lk;
  // spread of each lineup's total, for the score line
  const totArr = (idList) => { const a = new Float64Array(sim.n); for (const id of idList) { const x = sim.pts.get(id); if (x) for (let s = 0; s < sim.n; s++) a[s] += x[s]; } return a; };
  const A = totArr(res.best.ids), B = totArr(res.opp);
  res.myTot = distSummary(A, 0); res.oppTot = distSummary(B, 0);
  res.margin = distSummary(A.map((x, s) => x - B[s]), 0);
  res.sum = new Map([...sim.pts].map(([id, a]) => [id, distSummary(a, sim.inp.get(id).proj)]));
  res.ms = Math.round(performance.now() - t0);
  S.res = res; S.resFor = { ctx, mine: mine.id, opp: opp ? opp.id : "" };
  // calculator defaults: the flex starter and the best bench options at flex positions
  if (!S.cands.length || S.cands.some((id) => !mine.roster.includes(id))) {
    const flexy = (id) => ["RB", "WR", "TE"].includes((pl(id) || {}).p) && res.sum.has(id) && !started(pl(id));
    const start = res.best.lineup.filter((x) => ["FLEX", "RBWR", "WRTE", "OP"].includes(x.slot) && flexy(x.id)).map((x) => x.id);
    const bench = mine.roster.filter((id) => flexy(id) && !res.best.ids.includes(id)).sort((a, b) => res.sum.get(b).mean - res.sum.get(a).mean);
    S.cands = start.concat(bench).slice(0, 3);
  }
}
function ssStale() {
  const S = ui.ss, f = S.resFor;
  return !S.res || !f || f.ctx !== ctx || f.mine !== S.mine || f.opp !== S.opp;
}
/* Why the win-probability lineup differs from the projection lineup, in a sentence per swap. */
function swapReasons(res) {
  const out = [], P = res.proj.ids, B = res.best.ids;
  const ins = B.filter((id) => !P.includes(id)), outs = P.filter((id) => !B.includes(id));
  const under = res.myTot.mean < res.oppTot.mean;
  ins.forEach((inId, i) => {
    const outId = outs[i];
    if (!outId) return;
    const a = res.sum.get(inId), b = res.sum.get(outId), pa = res.sim.inp.get(inId).pplay, pb = res.sim.inp.get(outId).pplay;
    let why;
    if (pb < 0.85 && pa > pb + 0.1) why = `${esc(pl(outId).n)} plays only ${pct(pb)} of the time (${esc(pPlay(ctx, pl(outId)).why)}); ${esc(pl(inId).n)} ${pa >= 0.97 ? "is expected to play" : "is likelier to play"}`;
    else if (under && a.p90 > b.p90) why = `you're the underdog (projected ${fmt(res.myTot.mean, 0)}–${fmt(res.oppTot.mean, 0)}), and his ceiling (${fmt(a.p90)} at the 90th percentile vs ${fmt(b.p90)}) matters more than ${esc(pl(outId).n)}'s steadier floor`;
    else if (!under && a.p10 > b.p10) why = `you're favored, so his floor (${fmt(a.p10)} at the 10th percentile vs ${fmt(b.p10)}) is worth more than a little extra projection`;
    else why = `his week moves with the rest of your lineup and theirs in a way that helps (same game or offense)`;
    out.push(`Start <b>${esc(pl(inId).n)}</b> over <b>${esc(pl(outId).n)}</b>: ${why}.`);
  });
  return out;
}
function matchupHTML() {
  const S = ui.ss, res = S.res, mine = teamById(S.mine), opp = teamById(S.opp);
  if (!res) return `<div class="empty">Simulating ${SS_N.toLocaleString()} games…</div>`;
  const all = [...res.best.ids, ...res.opp].map((id) => res.sum.get(id)).filter(Boolean);
  const mx = Math.max(10, ...all.map((x) => x.p90)) * 1.05;
  const delta = res.best.p - res.proj.p;
  const rowFor = (id, slot, cls = "", alt = null) => {
    const p = pl(id), sm = res.sum.get(id), x = res.sim.inp.get(id);
    if (!p || !sm) return "";
    const st = started(p);
    return `<tr class="${cls}${st ? " locked" : ""}"><td class="slot-lab">${slot ? esc(SLOT_LABEL[slot] || slot) : "Bench"}</td>
      <td>${chipOf(p.p)} <span class="pname">${esc(p.n)}</span> ${ssTag(p)}<div class="sub">${p.t} · ${st ? "locked: game started" : esc(kickTxt(p))}</div></td>
      <td class="n">${playTxt(x.pplay)}</td><td class="n">${fmt(x.proj)}</td><td class="n">${fmt(sm.p10)}</td><td class="n">${fmt(sm.p50)}</td><td class="n">${fmt(sm.p90)}</td>
      <td style="min-width:110px">${rangeBar(sm, mx, p.p)}</td>
      <td class="n">${alt ? `<span title="${esc(alt.title)}">${alt.txt}</span>` : ""}</td></tr>`;
  };
  const altFor = (id) => {
    const a = res.alts.find((x) => x.id === id);
    if (a && a.locked) return { txt: "locked", title: "His game has started" };
    if (!a || !a.alts.length) return null;
    const b = a.alts[0];
    return { txt: `${esc(pl(b.id).n.split(" ").slice(-1)[0])} ${sgn((b.p - a.p) * 100, 0)}%`, title: `Starting ${pl(b.id).n} instead: ${pct(b.p)} to win` };
  };
  const bench = mine.roster.filter((id) => !res.best.ids.includes(id) && res.sum.has(id)).sort((a, b) => res.sum.get(b).mean - res.sum.get(a).mean);
  const out = mine.roster.filter((id) => pl(id) && !res.sum.has(id));
  const reasons = swapReasons(res);
  if (res.lk && res.lk.locked.length) reasons.push(`Already playing or played: ${res.lk.locked.map((id) => esc(pl(id).n)).join(", ")}. ${res.lk.fromEspn ? "They stay where your ESPN lineup had them at import" : "They stay where the highest-projection lineup puts them (import from ESPN this week to use your real lineup)"}; their numbers are pre-game, so for the rest of the week use the calculator below with the score so far.`);
  const oppRows = res.opp.map((id) => rowFor(id, "", "")).join("");
  const espnSch = !!(state.espn && state.espn.schedule);
  return `<div class="metric-grid" style="margin-bottom:12px">
      <div class="metric"><span class="label">Chance to win, best lineup</span><span class="big">${pct(res.best.p)}</span><div class="meter"><i style="width:${Math.round(res.best.p * 100)}%"></i></div><span class="note">${Math.abs(delta) >= 0.005 ? `${sgn(delta * 100, 0)} points over the highest-projection lineup (${pct(res.proj.p)})` : "the highest-projection lineup is already the best"}</span></div>
      <div class="metric"><span class="label">Projected score</span><span class="big">${fmt(res.myTot.mean, 0)} <span class="muted">–</span> ${fmt(res.oppTot.mean, 0)}</span><span class="note">You ${fmt(res.myTot.p10, 0)}–${fmt(res.myTot.p90, 0)}, ${esc(opp ? opp.name : "them")} ${fmt(res.oppTot.p10, 0)}–${fmt(res.oppTot.p90, 0)} (10th–90th percentile)</span></div>
      ${res.kd > 0 ? `<div class="metric"><span class="label">Not modeled</span><span class="big">±${fmt(res.kd / Math.SQRT2, 0)}</span><span class="note">Kickers and defenses aren't in this data: their usual swing is added to both sides, so a lopsided matchup still isn't a lock.</span></div>`
        : `<div class="metric"><span class="label">Your margin</span><span class="big">${sgn(res.margin.p50, 0)}</span><span class="note">Middle 80% of simulated weeks: ${sgn(res.margin.p10, 0)} to ${sgn(res.margin.p90, 0)}. Kickers and defenses included: a kicker's PATs follow his offense's touchdowns, a defense's points allowed follow the offense it faces.</span></div>`}
    </div>
    ${reasons.length ? `<div class="callout stack" style="gap:4px;margin-bottom:12px">${reasons.map((r) => `<div>${r}</div>`).join("")}</div>` : ""}
    <div class="tablewrap"><table>
      <thead><tr><th>Slot</th><th>Player</th><th class="n" title="Chance he plays (injury designation, last practice)">Plays</th><th class="n" title="Our projection if he plays">Proj</th><th class="n" title="10th percentile: a bad week">Floor</th><th class="n" title="Median: half his weeks are above">Median</th><th class="n" title="90th percentile: a big week">Ceiling</th><th>Range</th><th class="n" title="Best bench option for this spot and how it changes your chance to win">Next best</th></tr></thead>
      <tbody>${res.best.lineup.map((x) => rowFor(x.id, x.slot, res.proj.ids.includes(x.id) ? "" : "swap-in", altFor(x.id))).join("")}
      ${bench.map((id) => rowFor(id, "", "bench")).join("")}
      ${out.length ? `<tr class="bench"><td class="slot-lab">Out</td><td colspan="8" class="sub" style="white-space:normal">${out.map((id) => esc(pl(id).n)).join(", ")}</td></tr>` : ""}</tbody></table></div>
    <details style="margin-top:12px"><summary class="label" style="cursor:pointer">${esc(opp ? opp.name : "Opponent")}'s likely lineup</summary>
      <div class="tablewrap"><table><tbody>${oppRows}</tbody></table></div>
      <p class="notice" style="margin:6px 0 0">Assumed: their highest-projection lineup, sitting players unlikely to play.</p></details>
    <p class="notice" style="margin:10px 0 0">Floor, median and ceiling are the 10th, 50th and 90th percentile of ${SS_N.toLocaleString()} simulated games (they include the chance he doesn't play). Green rows are changes from the highest-projection lineup.${espnSch ? "" : " Re-import from ESPN to pick this week's opponent automatically."} ${res.ms ? `(${res.ms} ms)` : ""}</p>`;
}
/* ---- floor vs ceiling calculator */
function calcStale() {
  const S = ui.ss, f = S.calcFor;
  return !S.calc || !f || f.ctx !== ctx || f.key !== JSON.stringify([S.cands, S.need, [...S.left.mine], [...S.left.theirs], S.kdst]);
}
function calcCompute() {
  const S = ui.ss;
  if (!S.cands.length) { S.calc = []; S.calcFor = null; return; }
  S.calc = needCalc(ctx, S.cands, { need: S.need, mine: [...S.left.mine], theirs: [...S.left.theirs], kdst: S.kdst, n: 6000 });
  S.calcFor = { ctx, key: JSON.stringify([S.cands, S.need, [...S.left.mine], [...S.left.theirs], S.kdst]) };
}
const SER = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
function survivalSVG(rows, need) {
  const W = 640, H = 250, L = 40, R = 14, T = 12, B = 30;
  const xmax = Math.max(need + 8, ...rows.map((r) => r.sum ? r.sum.sorted[Math.floor(r.sum.sorted.length * 0.985)] : 0)) * 1.05;
  const X = (v) => L + (v / xmax) * (W - L - R), Y = (p) => T + (1 - p) * (H - T - B);
  const step = xmax / 120;
  let paths = "", dots = "", grid = "";
  for (const p of [0, 0.25, 0.5, 0.75, 1]) grid += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(p)}" y2="${Y(p)}"/><text x="${L - 6}" y="${Y(p) + 4}" text-anchor="end">${Math.round(p * 100)}%</text>`;
  const tick = xmax > 45 ? 10 : 5;
  for (let v = 0; v <= xmax; v += tick) grid += `<text x="${X(v)}" y="${H - B + 16}" text-anchor="middle">${v}</text>`;
  const labs = [];
  rows.forEach((r, i) => {
    if (!r.sum) return;
    let d = "";
    for (let v = 0; v <= xmax + 1e-9; v += step) d += `${d ? "L" : "M"}${X(v).toFixed(1)},${Y(r.sum.ge(v)).toFixed(1)}`;
    paths += `<path d="${d}" fill="none" stroke="${SER[i]}" stroke-width="2" stroke-linejoin="round"/>`;
    const pn = r.sum.ge(need);
    labs.push({ i, y: Y(pn), p: pn });
  });
  // direct labels at the target line, nudged apart so they don't collide
  // stack from the bottom up so no label drops below the axis
  labs.sort((a, b) => b.y - a.y);
  labs[0] && (labs[0].y = Math.min(labs[0].y, Y(0) - 6));
  for (let k = 1; k < labs.length; k++) if (labs[k - 1].y - labs[k].y < 13) labs[k].y = labs[k - 1].y - 13;
  for (const l of labs) dots += `<circle cx="${X(need)}" cy="${Y(l.p)}" r="4" fill="${SER[l.i]}" stroke="var(--surface)" stroke-width="2"/><text x="${X(need) + 8}" y="${l.y + 4}" class="needlab">${Math.round(l.p * 100)}%</text>`;
  return `<svg class="ss-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Chance each player scores at least x points">
    ${grid}<line class="axis" x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}"/>
    <text x="${(L + W - R) / 2}" y="${H - 2}" text-anchor="middle">points</text>
    ${paths}<line class="need" x1="${X(need)}" x2="${X(need)}" y1="${T}" y2="${Y(0)}"/><text x="${X(need) - 6}" y="${T + 10}" text-anchor="end" class="needlab">need ${fmt(need, need % 1 ? 1 : 0)}</text>
    ${dots}<line class="xh" id="ssXh" x1="0" x2="0" y1="${T}" y2="${Y(0)}" style="display:none"/>
    <rect id="ssHit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" data-xmax="${xmax}" data-l="${L}" data-r="${R}" data-w="${W}"/></svg>`;
}
function calcHTML() {
  const S = ui.ss, mine = teamById(S.mine), opp = teamById(S.opp), res = S.res;
  if (!mine) return "";
  const avail = mine.roster.filter((id) => pl(id) && ctx.val.get(id) && ctx.val.get(id).avail[0] && !started(pl(id))).sort((a, b) => ctx.wkA.get(b)[0] - ctx.wkA.get(a)[0]);
  const chip = (id, on, act, extra = "") => `<button class="pchip ${on ? "on" : ""}" data-act="${act}" data-id="${id}" ${extra} aria-pressed="${on}">${chipOf(pl(id).p, "min-width:24px")} ${esc(pl(id).n)}</button>`;
  const rows = S.calc || [];
  const best = rows.length ? rows.reduce((a, b) => (b.p > a.p ? b : a)) : null;
  const topProj = rows.length ? rows.reduce((a, b) => ((b.sum ? b.sum.mean : 0) > (a.sum ? a.sum.mean : 0) ? b : a)) : null;
  const others = S.left.mine.size || S.left.theirs.size || S.kdst;
  const what = others ? "chance to win" : `chance of ${fmt(S.need, S.need % 1 ? 1 : 0)}+`;
  let insight = "";
  if (best && topProj && rows.length > 1) {
    if (best.id !== topProj.id && best.p > topProj.p + 0.01) insight = `<b>${esc(pl(best.id).n)}</b> gives you the best shot (${pct(best.p)} vs ${pct(topProj.p)}) even though <b>${esc(pl(topProj.id).n)}</b> scores more on average: ${others ? "you need a big week" : "the target is above both players' typical week"}, and ${esc(pl(best.id).n)} has more of his outcomes up there.`;
    else if (best.id === topProj.id) insight = `<b>${esc(pl(best.id).n)}</b> is the start either way: highest average and the best ${what} (${pct(best.p)}).`;
    else insight = `It's close: ${rows.map((r) => `${esc(pl(r.id).n)} ${pct(r.p)}`).join(", ")}.`;
  }
  const starters = res ? res.best.ids : [];
  return `<div class="stack">
    <div class="field"><span class="label">Players to compare <span class="notice" style="text-transform:none;letter-spacing:0;font-family:var(--body)">· up to 4 · ${S.cands.length} picked</span></span>
      <div class="row" style="gap:6px">${avail.map((id) => chip(id, S.cands.includes(id), "ssCand")).join("")}</div></div>
    <div class="row" style="align-items:end">
      <label class="field"><span class="label">Points you need</span><input type="number" id="ssNeed" step="0.5" min="-100" max="200" value="${S.need}" data-act="ssNeed" style="width:6em"><span class="hint">How far behind you are (negative if ahead)</span></label>
      ${DB.players.some((p) => p.p === "K") ? "" : `<label class="row" style="gap:6px;padding-bottom:22px"><input type="checkbox" id="ssKd" data-act="ssKd" ${S.kdst ? "checked" : ""}>Kickers and defenses still to play</label>`}
    </div>
    <details ${S.left.mine.size || S.left.theirs.size ? "open" : ""}><summary class="label" style="cursor:pointer">Other players still to play (optional)</summary>
      <div class="stack" style="margin-top:8px">
        <div class="field"><span class="hint">Yours, besides the spot you're deciding</span><div class="row" style="gap:6px">${starters.filter((id) => !S.cands.includes(id)).map((id) => chip(id, S.left.mine.has(id), "ssLeftMine")).join("") || '<span class="notice">Run the matchup above first.</span>'}</div></div>
        <div class="field"><span class="hint">${esc(opp ? opp.name : "Theirs")}</span><div class="row" style="gap:6px">${(res ? res.opp : []).map((id) => chip(id, S.left.theirs.has(id), "ssLeftTheirs")).join("")}</div></div>
        <p class="notice" style="margin:0">With nobody else left, it's simply the chance he scores more than you need. Add the players still to play on both sides (and the deficit on the scoreboard) to get the chance to win.</p>
      </div></details>
    ${rows.length ? `<div class="ss-viz">
      <div class="tablewrap"><table class="mini"><thead><tr><th>Player</th><th class="n">${others ? "Win" : "Reach"}</th><th class="n">Plays</th><th class="n">Proj</th><th class="n">Floor</th><th class="n">Median</th><th class="n">Ceiling</th></tr></thead>
        <tbody>${rows.map((r, i) => `<tr><td><span class="ss-key" style="color:${SER[i]}"></span><span class="pname">${esc(pl(r.id).n)}</span> <span class="sub">${POSL(pl(r.id).p)} ${pl(r.id).t}</span></td><td class="n"><b>${pct(r.p)}</b></td><td class="n">${playTxt(r.pplay)}</td><td class="n">${r.sum ? fmt(ctx.wkA.get(r.id)[0]) : "–"}</td><td class="n">${r.sum ? fmt(r.sum.p10) : "–"}</td><td class="n">${r.sum ? fmt(r.sum.p50) : "–"}</td><td class="n">${r.sum ? fmt(r.sum.p90) : "–"}</td></tr>`).join("")}</tbody></table></div>
      ${insight ? `<p style="margin:10px 0">${insight}</p>` : ""}
      <div style="position:relative">${survivalSVG(rows, S.need)}<div class="ss-tip" id="ssTip"></div></div>
      <p class="notice" style="margin:4px 0 0">Each line is the chance he scores at least that many points this week. Where the lines cross is where the steadier player stops being the better bet: below it, take the higher floor; above it, the higher ceiling.</p>
    </div>` : `<div class="empty">Pick two or more players to compare.</div>`}
  </div>`;
}
/* ---- boom/bust board */
function boardStale() { const f = ui.ss.boardFor; return !ui.ss.board || !f || f.ctx !== ctx; }
function boardCompute() {
  const sim = simWeek(ctx, [], { n: BOARD_N, allTeams: true, seed: 99 });
  const rows = [];
  for (const [id, a] of sim.pts) {
    const x = sim.inp.get(id);
    if (!x || x.proj < 1) continue;
    rows.push({ id, pos: x.pos, proj: x.proj, pplay: x.pplay, sum: distSummary(a, x.proj) });
  }
  ui.ss.board = rows; ui.ss.boardFor = { ctx };
}
function boardHTML() {
  const S = ui.ss;
  if (!S.board) return `<div class="empty">Simulating every game…</div>`;
  const mine = teamById(S.mine);
  let rows = S.board.filter((r) => (!S.bpos || r.pos === S.bpos) && (S.bown === "all" || (S.bown === "mine" ? mine && mine.roster.includes(r.id) : !owner.has(r.id))));
  const key = { p: (r) => r.proj, c: (r) => r.sum.p90, f: (r) => r.sum.p10, boom: (r) => r.sum.boom, play: (r) => r.pplay };
  rows.sort((a, b) => key[S.bsort](b) - key[S.bsort](a));
  rows = rows.slice(0, 80);
  const mx = Math.max(10, ...rows.map((r) => r.sum.p90)) * 1.05;
  const th = (k, l, title) => `<th class="n sortable" data-act="ssBsort" data-k="${k}" title="${esc(title)}">${l}${S.bsort === k ? " ↓" : ""}</th>`;
  return `<div class="row" style="margin-bottom:8px">
      <select id="ssBpos" data-act="ssBpos"><option value="">All positions</option>${POSITIONS.map((x) => `<option value="${x}" ${S.bpos === x ? "selected" : ""}>${POSL(x)}</option>`).join("")}</select>
      <select id="ssBown" data-act="ssBown"><option value="mine" ${S.bown === "mine" ? "selected" : ""}>My team</option><option value="fa" ${S.bown === "fa" ? "selected" : ""}>Free agents</option><option value="all" ${S.bown === "all" ? "selected" : ""}>Everyone</option></select>
    </div>
    <div class="tablewrap"><table><thead><tr><th>Player</th>${th("p", "Proj", "Our projection if he plays")}${th("play", "Plays", "Chance he plays")}${th("f", "Floor", "10th percentile: a bad week")}<th class="n">Median</th>${th("c", "Ceiling", "90th percentile: a big week")}${th("boom", "Boom", "Chance of 1.5x his projection or more")}<th class="n" title="Chance of less than half his projection">Bust</th><th>Range</th></tr></thead>
      <tbody>${rows.map((r) => { const p = pl(r.id); return `<tr><td>${chipOf(p.p)} <span class="pname">${esc(p.n)}</span> ${ssTag(p)}<div class="sub">${p.t} · ${started(p) ? "game started" : esc(kickTxt(p))}</div></td>
        <td class="n">${fmt(r.proj)}</td><td class="n">${playTxt(r.pplay) || '<span class="muted">✓</span>'}</td><td class="n">${fmt(r.sum.p10)}</td><td class="n">${fmt(r.sum.p50)}</td><td class="n">${fmt(r.sum.p90)}</td><td class="n">${pct(r.sum.boom)}</td><td class="n">${pct(r.sum.bust)}</td>
        <td style="min-width:110px">${rangeBar(r.sum, mx, p.p)}</td></tr>`; }).join("") || `<tr><td colspan="9" class="muted">No players here this week.</td></tr>`}</tbody></table></div>
    <p class="notice" style="margin:8px 0 0">What moves a player's range is his projection, his position, his game and the chance he sits. His style matters much less than it seems: in 13,700 past player-games, receivers who live on long catches and touchdowns had about the same spread as possession receivers with the same projection, and the same held for backs (differences under 5%, and not stable from season to season). So a "safe" player isn't the better start just for being steady; compare the chances of the points you need above. Boom is a week of 1.5 times his projection or more, bust under half of it (both include the chance he sits).</p>`;
}
function renderStartSit() {
  const el = $("#panel-startsit");
  if (state.teams.length < 1) { el.innerHTML = `<h2>Start/Sit</h2><p class="lede">Ranks lineups by your chance to win the week, and shows every player's floor and ceiling.</p>` + emptyLeague(); return; }
  ssDefaults();
  const S = ui.ss, opts = (sel, skip) => state.teams.filter((t) => t.id !== skip).map((t) => `<option value="${t.id}" ${t.id === sel ? "selected" : ""}>${esc(t.name)}${t.mine ? " (mine)" : ""}</option>`).join("");
  const gd = DB.gameday && DB.gameday.teams && DB.gameday.teams.length ? ` Game-day inactives are in for ${DB.gameday.teams.join(", ")}.` : "";
  const built = DB.builtAt ? new Date(DB.builtAt).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
  el.innerHTML = `${exampleBanner()}<h2>Start/Sit · Week ${state.settings.curWeek}</h2>
    <p class="lede">Every player's week is simulated a few thousand times from his projection: how his team's game goes, how much work he gets, how the plays break, and the chance he sits if he's hurt. That gives a floor and a ceiling, and it lets lineups be ranked by what you actually want: the chance to win this week. Injury news as of ${esc(built)}.${gd} The data refreshes before Thursday night's game and on Sunday morning after the 1 pm inactives.</p>
    <div class="box stack" style="margin-bottom:14px">
      <div class="ss-head"><label class="field"><span class="label">Your team</span><select id="ssMine" data-act="ssMine">${opts(S.mine, "")}</select></label><span class="ss-vs">vs</span>
        <label class="field"><span class="label">Opponent</span><select id="ssOpp" data-act="ssOpp">${opts(S.opp, S.mine)}</select></label></div>
      <div id="ssMatch">${matchupHTML()}</div>
    </div>
    <div class="box stack" style="margin-bottom:14px">
      <div><h3>Floor vs ceiling: who gets you the points you need?</h3><p class="notice" style="margin:4px 0 0">A steady player is the better start when you only need a normal week; when you need a big one, the player with more big weeks can be the better bet even with a lower projection. Set how many points you need and compare.</p></div>
      <div id="ssCalc">${calcHTML()}</div>
    </div>
    <div class="box stack">
      <div class="row"><h3>Floors and ceilings, every player</h3><span class="spacer"></span>${S.showBoard ? "" : `<button class="btn" data-act="ssBoard">Show the board</button>`}</div>
      <p class="notice" style="margin:0">Each player's bad week, typical week and big week, for your roster, the free agents or everyone. Sort by ceiling to find the best shot at a big week.</p>
      <div id="ssBoardBox">${S.showBoard ? boardHTML() : ""}</div>
    </div>`;
  // heavy work after the frame is on screen
  if (ssStale()) setTimeout(() => { if (tab !== "startsit") return; ssCompute(); calcCompute(); if (tab === "startsit") renderStartSit(); }, 30);
  else if (calcStale()) setTimeout(() => { if (tab !== "startsit") return; calcCompute(); const c = $("#ssCalc"); if (c) { c.innerHTML = calcHTML(); bindChart(); } }, 0);
  if (S.showBoard && boardStale()) setTimeout(() => { if (tab !== "startsit") return; boardCompute(); const b = $("#ssBoardBox"); if (b) b.innerHTML = boardHTML(); }, 60);
  bindChart();
}
/* Crosshair on the survival chart: every candidate's chance of at least x points, at the hovered x. */
function bindChart() {
  const hit = $("#ssHit"), tip = $("#ssTip"), xh = $("#ssXh");
  if (!hit || !tip || !ui.ss.calc) return;
  const svg = hit.ownerSVGElement, xmax = +hit.dataset.xmax, L = +hit.dataset.l, R = +hit.dataset.r, W = +hit.dataset.w;
  const show = (clientX) => {
    const r = svg.getBoundingClientRect(), sx = (clientX - r.left) / r.width * W;
    const v = Math.max(0, Math.min(xmax, Math.round(((sx - L) / (W - L - R)) * xmax)));
    const px = L + (v / xmax) * (W - L - R);
    xh.setAttribute("x1", px); xh.setAttribute("x2", px); xh.style.display = "";
    tip.textContent = "";
    const head = document.createElement("div"); head.className = "label"; head.textContent = `${v}+ points`; tip.appendChild(head);
    ui.ss.calc.forEach((c, i) => {
      if (!c.sum) return;
      const row = document.createElement("div"); row.className = "row";
      const k = document.createElement("span"); k.className = "ss-key"; k.style.color = SER[i];
      const b = document.createElement("b"); b.textContent = pct(c.sum.ge(v));
      const n = document.createElement("span"); n.textContent = pl(c.id).n;
      row.append(k, b, n); tip.appendChild(row);
    });
    tip.style.display = "block";
    const left = (px / W) * r.width;
    tip.style.left = Math.min(r.width - tip.offsetWidth, Math.max(0, left + 10)) + "px";
    tip.style.top = "8px";
  };
  hit.addEventListener("pointermove", (e) => show(e.clientX));
  hit.addEventListener("pointerleave", () => { tip.style.display = "none"; xh.style.display = "none"; });
}

/* ---------------- render + events ---------------- */
function render() {
  document.querySelectorAll("nav.tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false"));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== "panel-" + tab));
  ({ trade: renderTrade, finder: renderFinder, startsit: renderStartSit, teams: renderTeams, players: renderPlayers, league: renderLeague, method: renderMethod })[tab]();
}
function setPath(obj, path, v) {
  const ks = path.split(".");
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) o = o[ks[i]] = o[ks[i]] || {};
  o[ks[ks.length - 1]] = v;
}
function newId() { return "t" + Math.random().toString(36).slice(2, 8); }
function addPlayer(team, p) {
  const prev = owner.get(p.id);
  if (prev && prev.id !== team.id) prev.roster = prev.roster.filter((x) => x !== p.id);
  if (!team.roster.includes(p.id)) team.roster.push(p.id);
}
function loadSample() {
  const L = sampleLeague(DB, Math.floor(Math.random() * 100000) + 1);
  openLeague(state.example ? activeKey : "sample", L, "trade");
}

document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-act], nav.tabs button");
  if (!t) return;
  if (t.matches("nav.tabs button")) { tab = t.dataset.tab; ui.confirm = ""; render(); return; }
  const a = t.dataset.act, team = t.dataset.team && teamById(t.dataset.team);
  switch (a) {
    case "goto": tab = t.dataset.tab; render(); break;
    case "gotoImport": tab = "league"; render(); { const i = $("#espnInput"); if (i) { i.scrollIntoView({ block: "center" }); i.focus(); } } break;
    case "sample": loadSample(); break;
    case "askDelLeague": ui.confirm = "delLeague"; render(); break;
    case "doDelLeague": ui.confirm = ""; removeLeague(activeKey); break;
    case "cancel": ui.confirm = ""; render(); break;
    case "espnAuto": autoImport(); break;
    case "espnCancel": ui.imp.pending = null; importStatus("", ""); updateImport(); break;
    case "espnApply": {
      const imp = ui.imp.pending;
      if (!imp) break;
      const key = "espn-" + imp.leagueId;
      const prev = key === activeKey ? clone(state) : leagues.has(key) ? clone(leagues.get(key)) : null;
      const L = applyEspn(prev, imp, DB, ui.imp.mine);
      ui.imp.pending = null; ui.imp.input = imp.leagueId;
      importStatus("ok", `Imported ${imp.name}.`);
      openLeague(key, L, "trade");
      break;
    }
    case "addTeam": {
      const n = state.teams.length + 1;
      state.teams.push({ id: newId(), name: n === 1 ? "My team" : "Team " + n, mine: n === 1, roster: [] });
      changed(); break;
    }
    case "askDel": ui.confirm = "del-" + t.dataset.team; render(); break;
    case "delTeam": {
      const wasMine = team.mine;
      state.teams = state.teams.filter((x) => x !== team);
      if (wasMine && state.teams[0]) state.teams[0].mine = true;
      ui.confirm = ""; changed(); break;
    }
    case "mine": state.teams.forEach((x) => (x.mine = x === team)); ui.trade.mine = team.id; ui.finder.results = null; changed(); break;
    case "rm": team.roster = team.roster.filter((x) => x !== t.dataset.id); changed(); break;
    case "openTrade": {
      const r = ui.finder.results[+t.dataset.i];
      ui.trade = { mine: myTeam().id, partner: r.partner, give: new Set(r.give), get: new Set(r.get), mg: (r.money && r.money.give) || 0, mr: (r.money && r.money.get) || 0 };
      tab = "trade"; render(); window.scrollTo({ top: 0 }); break;
    }
    case "runFinder": runFinder(); break;
    case "ssCand": {
      const S = ui.ss, id = t.dataset.id;
      if (S.cands.includes(id)) S.cands = S.cands.filter((x) => x !== id);
      else { S.cands = S.cands.concat([id]).slice(-4); S.left.mine.delete(id); }
      renderStartSit(); break;
    }
    case "ssLeftMine": { const s = ui.ss.left.mine, id = t.dataset.id; s.has(id) ? s.delete(id) : s.add(id); renderStartSit(); break; }
    case "ssLeftTheirs": { const s = ui.ss.left.theirs, id = t.dataset.id; s.has(id) ? s.delete(id) : s.add(id); renderStartSit(); break; }
    case "ssBoard": ui.ss.showBoard = true; renderStartSit(); break;
    case "ssBsort": ui.ss.bsort = t.dataset.k; { const b = $("#ssBoardBox"); if (b) b.innerHTML = boardHTML(); } break;
    case "fpart": { const F = ui.finder, id = t.dataset.team; F.partners.has(id) ? F.partners.delete(id) : F.partners.add(id); F.results = null; renderFinder(); break; }
    case "fpartAll": ui.finder.partners = new Set(); ui.finder.results = null; renderFinder(); break;
    case "fpartLosing": ui.finder.partners = new Set(state.teams.filter((x) => !x.mine && teamMood(x) > 0.2).map((x) => x.id)); ui.finder.results = null; renderFinder(); break;
    case "psort": { const P = ui.players; if (P.sort === t.dataset.k) P.dir *= -1; else { P.sort = t.dataset.k; P.dir = t.dataset.k === "n" ? 1 : -1; } renderPlayers(); break; }
    case "psel": ui.players.sel = t.dataset.id; renderPlayers(); if (window.innerWidth < 800) $("#playerDetail").scrollIntoView({ block: "start" }); break;
    case "ovReset": delete state.overrides[t.dataset.id]; changed(); break;
    case "copyBackup": {
      const ta = $("#backup"), msg = $("#backupMsg");
      ta.value = JSON.stringify(state);
      navigator.clipboard.writeText(ta.value).then(() => (msg.textContent = "Copied."), () => { ta.select(); msg.textContent = "Selected. Press Ctrl+C or ⌘C to copy."; });
      break;
    }
    case "loadBackup": {
      const msg = $("#backupMsg");
      try {
        const data = JSON.parse($("#backup").value);
        if (!data || !Array.isArray(data.teams)) throw new Error();
        accept(data); resetUi(); changed(); $("#backupMsg") && ($("#backupMsg").textContent = "Loaded.");
      } catch (e) { msg.textContent = "That text isn't a league backup. Copy one from this box and try again."; }
      break;
    }
  }
});

document.addEventListener("change", (ev) => {
  const t = ev.target;
  const a = t.dataset && t.dataset.act;
  const team = t.dataset && t.dataset.team && teamById(t.dataset.team);
  switch (a || "") {
    case "pick": {
      const set = t.dataset.side === "give" ? ui.trade.give : ui.trade.get;
      t.checked ? set.add(t.dataset.id) : set.delete(t.dataset.id);
      renderTrade(); break;
    }
    case "tmine": ui.trade.mine = t.value; ui.trade.give.clear(); ui.trade.mg = 0; renderTrade(); break;
    case "tpartner": ui.trade.partner = t.value; ui.trade.get.clear(); ui.trade.mr = 0; renderTrade(); break;
    case "money": {
      const team = teamById(t.dataset.side === "give" ? ui.trade.mine : ui.trade.partner);
      const v = Math.max(0, Math.min(faabOf(ctx, team), Math.round(+t.value || 0)));
      if (t.dataset.side === "give") ui.trade.mg = v; else ui.trade.mr = v;
      renderTrade(); break;
    }
    case "tfaab": {
      const v = t.value === "" ? null : Math.max(0, Math.round(+t.value));
      team.faab = v; changed(); break;
    }
    case "trec": {
      const v = t.value === "" ? null : Math.max(0, Math.round(+t.value));
      team[t.dataset.k] = v; ui.finder.results = null; changed(); break;
    }
    case "tstyle": team.style = Math.max(0, Math.min(1, +t.value)); ui.finder.results = null; changed(); break;
    case "tfav": team.fav = t.value || null; if (team.fav && team.fan == null) team.fan = 0.5; ui.finder.results = null; changed(); break;
    case "tfan": team.fan = Math.max(0, Math.min(1, +t.value)); ui.finder.results = null; changed(); break;
    case "fmin": ui.finder.minAccept = +t.value; break;
    case "fshape": t.checked ? ui.finder.shapes.add(t.dataset.k) : ui.finder.shapes.delete(t.dataset.k); break;
    case "tname": team.name = t.value.trim() || team.name; changed({ quiet: true }); break;
    case "lname": state.name = t.value.trim() || "My league"; changed(); renderSwitcher(); break;
    case "espnMine": ui.imp.mine = +t.value; break;
    case "teRec": {
      const byPos = { ...(state.settings.scoring.byPos || {}) };
      const te = { ...(byPos.TE || {}) };
      if (t.value === "") delete te.rec; else te.rec = +t.value;
      if (Object.keys(te).length) byPos.TE = te; else delete byPos.TE;
      state.settings.scoring.byPos = byPos;
      changed(); break;
    }
    case "tier": {
      const key = t.dataset.key, v = +t.value;
      if (!isFinite(v)) return;
      const arr = (kdSet(state.settings.scoring, key) || []).slice();
      arr[+t.dataset.i] = v;
      state.settings.scoring[key] = arr;
      ui.finder.results = null; changed(); break;
    }
    case "add": {
      const p = byLabel.get(t.value.trim().toLowerCase()) || DB.players.find((x) => x.n.toLowerCase() === t.value.trim().toLowerCase());
      if (!p) { t.setCustomValidity("Pick a player from the list."); t.reportValidity(); return; }
      t.setCustomValidity("");
      addPlayer(team, p);
      changed();
      const again = $("#add-" + team.id); if (again) again.focus();
      break;
    }
    case "out": {
      const v = t.value === "" ? null : Math.round(+t.value);
      if (v == null) delete state.out[t.dataset.id]; else state.out[t.dataset.id] = v;
      changed(); break;
    }
    case "ov": {
      const id = t.dataset.id, o = { ...(state.overrides[id] || {}) };
      if (t.value === "") delete o[t.dataset.k]; else o[t.dataset.k] = +t.value;
      if (Object.keys(o).length) state.overrides[id] = o; else delete state.overrides[id];
      ui.finder.results = null; changed(); break;
    }
    case "set": {
      const path = t.dataset.path;
      const v = +t.value;
      if (!isFinite(v)) return;
      setPath(state.settings, path, v);
      if (path === "expertWeight" || path === "weeklyExpert") state.settings.expertAuto = false;
      ui.finder.results = null; changed(); break;
    }
    case "cushion": state.settings.cushion = t.checked; ui.finder.results = null; changed(); break;
    case "waiver": state.settings.waiver = t.checked; ui.finder.results = null; changed(); break;
    case "faabOn": state.settings.faab = t.checked; ui.finder.results = null; changed(); break;
    case "preset": {
      if (t.value === "custom") return;
      state.settings.scoring = { ...DEFAULT_SETTINGS.scoring, rec: PRESETS[t.value].rec, byPos: {} };
      ui.finder.results = null; changed(); break;
    }
    case "ssMine": ui.ss.mine = t.value; ui.ss.cands = []; ui.ss.left = { mine: new Set(), theirs: new Set() }; if (ui.ss.opp === t.value) ui.ss.opp = ""; renderStartSit(); break;
    case "ssOpp": ui.ss.opp = t.value; ui.ss.left.theirs = new Set(); renderStartSit(); break;
    case "ssNeed": { const v = +t.value; if (isFinite(v)) { ui.ss.need = v; renderStartSit(); } break; }
    case "ssKd": ui.ss.kdst = t.checked; renderStartSit(); break;
    case "ssBpos": ui.ss.bpos = t.value; { const b = $("#ssBoardBox"); if (b) b.innerHTML = boardHTML(); } break;
    case "ssBown": ui.ss.bown = t.value; { const b = $("#ssBoardBox"); if (b) b.innerHTML = boardHTML(); } break;
    case "ppos": ui.players.pos = t.value; renderPlayers(); break;
    case "pown": ui.players.own = t.value; renderPlayers(); break;
  }
  if (t.id === "leagueSwitch") {
    const v = t.value;
    if (v === "__import") { renderSwitcher(); tab = "league"; render(); const i = $("#espnInput"); if (i) { i.scrollIntoView({ block: "center" }); i.focus(); } }
    else if (v === "__new") { const L = newLeague(DB); openLeague("l" + Math.random().toString(36).slice(2, 8), L, "league"); }
    else if (v !== activeKey) switchLeague(v);
  }
  if (t.id === "espnFile" && t.files && t.files[0]) {
    const fr = new FileReader();
    fr.onload = () => readPasted(String(fr.result || ""));
    fr.onerror = () => importStatus("err", "Couldn't read that file. Try copying and pasting instead.");
    fr.readAsText(t.files[0]);
    t.value = "";
  }
  if (t.id === "espnSeason") { ui.imp.season = +t.value || 2026; updateImport(); }
});
document.addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.id === "pSearch") {
    ui.players.q = t.value;
    clearTimeout(t._tm);
    t._tm = setTimeout(() => { renderPlayers(); const s = $("#pSearch"); s.focus(); s.setSelectionRange(s.value.length, s.value.length); }, 180);
  }
  if (t.id === "finderMin") $("#minAccLabel").textContent = pct(+t.value);
  if (t.id === "espnInput") {
    ui.imp.input = t.value;
    const p = parseLeagueInput(t.value);
    if (p.season) ui.imp.season = p.season;
    updateImport();
  }
  if (t.id === "espnPaste") { clearTimeout(t._tm); t._tm = setTimeout(() => readPasted(t.value), 250); }
  if (t.dataset && t.dataset.act === "add" && byLabel.has(t.value.trim().toLowerCase())) t.dispatchEvent(new Event("change", { bubbles: true }));
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && ev.target.matches("input[data-act='add']")) ev.target.dispatchEvent(new Event("change", { bubbles: true }));
});

rebuild();
render();
renderSwitcher();
initStore();
initBrowser();
