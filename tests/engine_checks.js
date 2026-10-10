// Trade-engine regression checks on a fixed week (tests/run_tests.py reads the JSON this prints).
//   node tests/engine_checks.js ENGINE.js DB.json LEAGUE.json
// allen: in simulated 12-team leagues, Josh Allen offered for two genuine starters (RB top 24, WR top 30,
//        TE top 10 by our projection) from the same team — managers should rarely accept (Oct 2 fix).
// shough: the user's league — Tyler Shough for Tyler Warren + Jaylen Warren should be unlikely (Oct 6 fix).
const fs = require("fs");
const [enginePath, dbPath, leaguePath] = process.argv.slice(2);
const mod = { exports: {} };
new Function("module", fs.readFileSync(enginePath, "utf8"))(mod);
const E = mod.exports;
const DB = JSON.parse(fs.readFileSync(dbPath, "utf8"));
const byName = (n) => DB.players.find((p) => p.n === n);
const out = {};

// --- Allen for two starters, sample leagues
const allen = byName("Josh Allen");
const accepts = [];
for (const seed of [1, 2, 3]) {
  const L = E.sampleLeague(DB, seed);
  const mine = L.teams[0];
  const holder = L.teams.find((t) => t.roster.includes(allen.id));
  if (holder !== mine) {
    const myQB = mine.roster.find((id) => DB.players.find((p) => p.id === id).p === "QB");
    holder.roster = holder.roster.filter((id) => id !== allen.id).concat(myQB ? [myQB] : []);
    mine.roster = mine.roster.filter((id) => id !== myQB).concat([allen.id]);
  }
  const ctx = E.buildCtx(DB, L);
  const rank = {};
  for (const pos of ["RB", "WR", "TE"]) {
    const ps = DB.players.filter((p) => p.p === pos).sort((a, b) => ctx.ppg.a.get(b.id) - ctx.ppg.a.get(a.id));
    ps.forEach((p, i) => { rank[p.id] = i + 1; });
  }
  const genuine = (id) => { const p = DB.players.find((q) => q.id === id); return p && ((p.p === "RB" && rank[id] <= 24) || (p.p === "WR" && rank[id] <= 30) || (p.p === "TE" && rank[id] <= 10)); };
  for (const t of L.teams.slice(1)) {
    const st = t.roster.filter(genuine);
    for (let i = 0; i < st.length; i++) for (let j = i + 1; j < st.length; j++) {
      accepts.push(E.evalTrade(ctx, mine, t, [allen.id], [st[i], st[j]]).accept);
    }
  }
}
accepts.sort((a, b) => a - b);
out.allen = { n: accepts.length, median: accepts.length ? accepts[Math.floor(accepts.length / 2)] : null,
  share50: accepts.filter((x) => x >= 0.5).length / Math.max(1, accepts.length) };

// --- Shough for the two Warrens, the user's league (loaded the way the page loads a saved league)
if (leaguePath && fs.existsSync(leaguePath)) {
  const data = JSON.parse(fs.readFileSync(leaguePath, "utf8"));
  const L = E.newLeague(DB);
  Object.assign(L, data);
  const ds = data.settings || {};
  L.settings = { ...E.DEFAULT_SETTINGS, ...ds, scoring: { ...E.DEFAULT_SETTINGS.scoring, ...(ds.scoring || {}) },
    slots: { ...E.DEFAULT_SETTINGS.slots, ...(ds.slots || {}) }, perc: { ...E.DEFAULT_SETTINGS.perc, ...(ds.perc || {}) } };
  L.settings.curWeek = DB.curWeek;
  const ctx = E.buildCtx(DB, L);
  const mine = L.teams.find((t) => t.mine);
  const sh = byName("Tyler Shough"), tw = byName("Tyler Warren"), jw = byName("Jaylen Warren");
  const other = L.teams.find((t) => t.roster.includes(tw.id));
  const e = E.evalTrade(ctx, mine, other, [sh.id], [tw.id, jw.id]);
  out.shough = { accept: e.accept, dA: e.dA };
}
process.stdout.write(JSON.stringify(out));
