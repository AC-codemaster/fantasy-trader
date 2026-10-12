// One trade, judged by the engine as it stood at the trade (tools/trade_autopsy.py drives this).
//
//   node tools/autopsy_runner.js --engine engine.js --db db.json --espn league_at_trade.json \
//        --trade trade.json [--saved saved_league.json]
//
// --espn   ESPN league JSON (mSettings, mTeam, mRoster) with rosters as they were just before the trade
// --saved  the page's saved league document (leagues/espn-<id>): the user's settings, manager styles and
//          favorite teams are kept, the way a re-import keeps them
// --trade  {"a": espnTeamId, "b": espnTeamId, "aGives": [espn player ids], "bGives": [...]}; a = proposer
// Prints {dA, dB, accept, perceived, perWeek, wSum, weeks, scoring, players: {dbId: {weekly, avail}}, unmatched}.
const fs = require("fs");
const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const mod = { exports: {} };
new Function("module", fs.readFileSync(opt("--engine"), "utf8"))(mod);
const E = mod.exports;
const DB = JSON.parse(fs.readFileSync(opt("--db"), "utf8").replace(/<\\\//g, "</"));
const raw = JSON.parse(fs.readFileSync(opt("--espn"), "utf8"));
const trade = JSON.parse(fs.readFileSync(opt("--trade"), "utf8"));
const saved = opt("--saved") && fs.existsSync(opt("--saved")) ? JSON.parse(fs.readFileSync(opt("--saved"), "utf8")) : null;

const imp = E.parseEspn(raw, DB, {});
let prev = null;
if (saved) {
  prev = E.newLeague(DB);
  Object.assign(prev, saved);
  const ds = saved.settings || {};
  prev.settings = { ...E.DEFAULT_SETTINGS, ...ds, scoring: { ...E.DEFAULT_SETTINGS.scoring, ...(ds.scoring || {}) },
    slots: { ...E.DEFAULT_SETTINGS.slots, ...(ds.slots || {}) }, perc: { ...E.DEFAULT_SETTINGS.perc, ...(ds.perc || {}) } };
}
const L = E.applyEspn(prev, imp, DB);
L.settings.curWeek = DB.curWeek;
// records at the trade date aren't in the data: managers are judged without a mood
for (const t of L.teams) { delete t.wins; delete t.losses; delete t.ties; delete t.streak; }
const byEspn = new Map(DB.players.filter((p) => p.espn).map((p) => [String(p.espn), p.id]));
const ids = (xs) => xs.map((x) => byEspn.get(String(x))).filter(Boolean);
const unmatched = [...trade.aGives, ...trade.bGives].filter((x) => !byEspn.get(String(x)));
const A = L.teams.find((t) => t.espnTeamId === +trade.a), B = L.teams.find((t) => t.espnTeamId === +trade.b);
if (!A || !B) throw new Error("trade teams not in the league data");
const give = ids(trade.aGives), get = ids(trade.bGives);
// the rolled-back rosters must hold the traded players on the right side
for (const id of give) if (!A.roster.includes(id)) A.roster.push(id);
for (const id of get) if (!B.roster.includes(id)) B.roster.push(id);
for (const t of L.teams) if (t !== A) t.roster = t.roster.filter((id) => !give.includes(id) || t === A);
for (const t of L.teams) if (t !== B) t.roster = t.roster.filter((id) => !get.includes(id) || t === B);
const ctx = E.buildCtx(DB, L);
const e = E.evalTrade(ctx, A, B, give, get);
const V = E.valuations(DB, L);
const players = {};
for (const id of [...give, ...get]) {
  const v = V.get(id);
  if (v) players[id] = { weekly: Array.from(v.weekly, (x) => Math.round(x * 1000) / 1000), avail: v.avail.map((x) => (x ? 1 : 0)) };
}
process.stdout.write(JSON.stringify({ dA: e.dA, dB: e.dB, accept: e.accept, perceived: e.perceived, wSum: e.wSum,
  perWeekA: e.dA / Math.max(1, e.wSum), perWeekB: e.dB / Math.max(1, e.wSum), weeks: V.weeks || null,
  curWeek: DB.curWeek, scoring: L.settings.scoring, lastWeek: L.settings.lastWeek, give, get, players, unmatched }));
