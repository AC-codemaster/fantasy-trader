// Start/sit and floor-ceiling checks on a fixed week (tests/run_tests.py reads the JSON this prints).
//   node tests/startsit_checks.js ENGINE.js DB.json LEAGUE.json [--dump frame.json]
// sim:    simulated means against the projection, determinism, QB-receiver correlation, speed
// lineup: the best lineup's chance to win is at least the highest-projection lineup's
// need:   the chance of reaching a target falls as the target rises
// --dump: the inputs of a few teams, uncalibrated, as backtest-style rows (dist/sim.py replays them for parity)
const fs = require("fs");
const [enginePath, dbPath, leaguePath] = process.argv.slice(2);
const dump = process.argv.includes("--dump") ? process.argv[process.argv.indexOf("--dump") + 1] : null;
const mod = { exports: {} };
new Function("module", fs.readFileSync(enginePath, "utf8"))(mod);
const E = mod.exports;
const DB = JSON.parse(fs.readFileSync(dbPath, "utf8"));
const data = JSON.parse(fs.readFileSync(leaguePath, "utf8"));
const L = E.newLeague(DB);
Object.assign(L, data);
const ds = data.settings || {};
L.settings = { ...E.DEFAULT_SETTINGS, ...ds, scoring: { ...E.DEFAULT_SETTINGS.scoring, ...(ds.scoring || {}) },
  slots: { ...E.DEFAULT_SETTINGS.slots, ...(ds.slots || {}) }, perc: { ...E.DEFAULT_SETTINGS.perc, ...(ds.perc || {}) } };
L.settings.curWeek = DB.curWeek;
L.out = {}; L.autoOut = {};
const ctx = E.buildCtx(DB, L);
const mine = L.teams.find((t) => t.mine), opp = L.teams.find((t) => !t.mine);
const out = {};
// --- simulation basics on the two rosters
let t0 = Date.now();
const sim = E.simWeek(ctx, mine.roster.concat(opp.roster), { n: 4000 });
out.ms = Date.now() - t0;
const sim2 = E.simWeek(ctx, mine.roster.concat(opp.roster), { n: 4000 });
out.deterministic = [...sim.pts].every(([id, a]) => { const b = sim2.pts.get(id); return b && a.every((v, i) => v === b[i]); });
const ratios = [];
for (const [id, a] of sim.pts) {
  const x = sim.inp.get(id);
  if (x.proj < 5 || x.pplay < 0.99) continue;
  ratios.push(a.reduce((s, v) => s + v, 0) / a.length / x.proj);
}
ratios.sort((a, b) => a - b);
out.meanRatio = { n: ratios.length, min: ratios[0], median: ratios[Math.floor(ratios.length / 2)], max: ratios[ratios.length - 1] };
out.teams = sim.teams.length;
// QB with his top receiver, whole league
const all = E.simWeek(ctx, [], { n: 3000, allTeams: true, seed: 5 });
const corr = (a, b) => { const n = a.length; let ma = 0, mb = 0; for (let i = 0; i < n; i++) { ma += a[i]; mb += b[i]; } ma /= n; mb /= n; let c = 0, va = 0, vb = 0; for (let i = 0; i < n; i++) { c += (a[i] - ma) * (b[i] - mb); va += (a[i] - ma) ** 2; vb += (b[i] - mb) ** 2; } return c / Math.sqrt(va * vb); };
const cs = [];
const byTeam = new Map();
for (const [id, a] of all.pts) { const x = all.inp.get(id), t = DB.players.find((p) => p.id === id).t; if (!byTeam.has(t)) byTeam.set(t, []); byTeam.get(t).push({ id, x, a }); }
for (const [t, ps] of byTeam) {
  const qb = ps.filter((y) => y.x.qb).sort((a, b) => b.x.proj - a.x.proj)[0];
  const wr = ps.filter((y) => y.x.pos === "WR").sort((a, b) => b.x.proj - a.x.proj)[0];
  const rbs = ps.filter((y) => y.x.pos === "RB").sort((a, b) => b.x.proj - a.x.proj);
  if (qb && wr && qb.x.proj > 8 && wr.x.proj > 5) cs.push(["qbwr", corr(qb.a, wr.a)]);
  if (rbs.length >= 2 && rbs[1].x.proj > 4) cs.push(["rbrb", corr(rbs[0].a, rbs[1].a)]);
}
const avg = (k) => { const v = cs.filter((c) => c[0] === k).map((c) => c[1]); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
out.corr = { qbwr: avg("qbwr"), rbrb: avg("rbrb"), n: cs.length };
// --- lineups
t0 = Date.now();
const ss = E.startSit(ctx, mine, opp, { sim });
out.startSit = { ms: Date.now() - t0, best: ss.best.p, proj: ss.proj.p, legal: !!E.fitSlots(E.lineupSlotList(L.settings), ss.best.ids.map((id) => DB.players.find((p) => p.id === id).p)), n: ss.best.ids.length, slots: E.lineupSlotList(L.settings).length };
// --- need calculator
const flex = mine.roster.filter((id) => { const p = DB.players.find((q) => q.id === id); return p && ["RB", "WR", "TE"].includes(p.p) && sim.pts.has(id); }).slice(0, 3);
const lo = E.needCalc(ctx, flex, { need: 5, sim }), hi = E.needCalc(ctx, flex, { need: 20, sim });
out.need = { n: flex.length, falls: lo.every((r, i) => r.p >= hi[i].p), lo: lo.map((r) => r.p), hi: hi.map((r) => r.p) };
if (dump) {
  // uncalibrated inputs for a handful of teams, as dist/sim.py rows
  const raw = E.simWeek(ctx, [], { n: 4000, allTeams: true, raw: true, seed: 11 });
  const rows = [];
  for (const [id, a] of raw.pts) {
    const x = raw.inp.get(id), p = DB.players.find((q) => q.id === id);
    const s = Float64Array.from(a).sort();
    rows.push({ id, season: DB.season, week: DB.curWeek, team: p.t, opp: (DB.opp || {})[p.t] || "BYE", pos: x.pos, pred: x.proj,
      car: x.qb ? 0 : x.car, tgt: x.tgt, att: x.att, qc: x.qb ? x.car : 0,
      c_py: x.py, c_ptd: x.ptd, c_int: x.att * x.ipa, c_ry: x.car * x.ypc, c_rtd: x.car * x.rtd, c_rec: x.tgt * x.cr,
      c_recy: x.tgt * x.cr * x.ypr, c_rectd: x.tgt * x.cr * x.ctd, c_fl: (x.car + x.tgt + x.att) * x.fl, c_two: (x.car + x.tgt + x.att) * x.two,
      js_q: [0.1, 0.5, 0.9].map((q) => s[Math.floor(q * (s.length - 1))]), js_mean: s.reduce((u, v) => u + v, 0) / s.length });
  }
  fs.writeFileSync(dump, JSON.stringify(rows));
  out.dumped = rows.length;
}
process.stdout.write(JSON.stringify(out));
