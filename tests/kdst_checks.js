// Kicker and D/ST checks on a fixed database (tests/run_tests.py reads the JSON this prints).
//   node tests/kdst_checks.js ENGINE.js DB.json
// scoring: the engine's K/DST scoring of a few stat lines (run_tests compares them with pipeline/kdst.py)
// lineup:  K and D/ST slots take only kickers and defenses; FLEX and superflex never do
// league:  a simulated draft gives every team one kicker and one defense; values, trade prices, the finder
// sim:     simulated means match the projections; spreads near the box-score values; links to the offenses
// espn:    an ESPN league with kickers, defenses and their scoring rules imports them
const fs = require("fs");
const [enginePath, dbPath] = process.argv.slice(2);
const mod = { exports: {} };
new Function("module", fs.readFileSync(enginePath, "utf8"))(mod);
const E = mod.exports;
const DB = JSON.parse(fs.readFileSync(dbPath, "utf8"));
const byId = new Map(DB.players.map((p) => [p.id, p]));
const out = {};
const sc = E.DEFAULT_SETTINGS.scoring;
const kv = [2, 1, 1, 1, 1, 1, 1, 0, 1], dv = [3, 1, 1, 0, 1, 0, 1, 17.4, 310].concat([0, 0, 0.1, 0.2, 0.3, 0.2, 0.1, 0.1, 0], [0, 0, 0.1, 0.3, 0.3, 0.2, 0.1, 0, 0]);
out.scoring = { defaults: Object.fromEntries([...E.K_KEYS, ...E.D_KEYS, "paTier", "yaTier"].map((k) => [k, sc[k]])), k: E.kScore(kv, sc), d: E.dScore(dv, sc), kv, dv };
// lineup codes: QB RB WR TE K DST, two of each kicker/defense, one flex and one superflex slot
const pos = Int8Array.from([4, 5, 4, 5, 0, 1, 2, 3, 1]), pts = Float64Array.from([30, 29, 28, 27, 20, 10, 9, 8, 7]);
const [, k] = E.lineupFast(pos, pts, pos.length, -1, { QB: 1, RB: 1, WR: 1, TE: 1, K: 1, DST: 1, FLEX: 1, OP: 1 });
out.lineup = { k, kd: 0 };
// the lineup took exactly one kicker and one defense even though they score the most
const L = E.sampleLeague(DB, 3);
const ctx = E.buildCtx(DB, L);
out.league = { teams: L.teams.length, kd: L.teams.map((t) => ["K", "DST"].map((x) => t.roster.filter((id) => byId.get(id).p === x).length).join("")),
  slots: E.lineupSlotList(L.settings, new Set(DB.players.map((p) => p.p))).map((x) => x.k) };
const lw = L.teams.map((t) => E.lineupForWeek(ctx, t.roster, "a", DB.curWeek));
out.league.lineupKd = lw.map((x) => x.ids.filter((id) => ["K", "DST"].includes(byId.get(id).p)).length + x.streamers.filter((p) => p === "K" || p === "DST").length);
out.league.flexKd = lw.every((x) => x.ids.length + x.streamers.length <= E.lineupSlotList(L.settings).length);
const kd = DB.players.filter((p) => p.p === "K" || p.p === "DST");
out.league.mu = { max: Math.max(...kd.map((p) => ctx.mkt.mu.get(p.id))), top: Math.max(...DB.players.filter((p) => p.p === "RB").map((p) => ctx.mkt.mu.get(p.id))) };
out.league.ppg = { K: kd.filter((p) => p.p === "K").map((p) => ctx.ppg.a.get(p.id)).sort((a, b) => b - a).slice(0, 12),
  DST: kd.filter((p) => p.p === "DST").map((p) => ctx.ppg.a.get(p.id)).sort((a, b) => b - a).slice(0, 12) };
const gen = E.findTrades(ctx, L.teams[0], { partnerIds: [L.teams[1].id, L.teams[2].id] });
let r; while (!(r = gen.next()).done);
out.league.finderKd = r.value.filter((x) => x.give.concat(x.get).some((id) => ["K", "DST"].includes(byId.get(id).p))).length;
const myK = L.teams[0].roster.find((id) => byId.get(id).p === "K"), thK = L.teams[1].roster.find((id) => byId.get(id).p === "K");
const e = E.evalTrade(ctx, L.teams[0], L.teams[1], [myK], [thK]);
out.league.kForK = { dA: e.dA, dB: e.dB, accept: e.accept };
// simulation
const sim = E.simWeek(ctx, [], { n: 4000, allTeams: true, seed: 17 });
const sd = (a) => { const m = a.reduce((u, v) => u + v, 0) / a.length; return Math.sqrt(a.reduce((u, v) => u + (v - m) ** 2, 0) / a.length); };
const stat = { K: [], DST: [] };
for (const p of kd) {
  const a = sim.pts.get(p.id), x = sim.inp.get(p.id);
  if (!a || x.proj < 2) continue;
  stat[p.p].push({ ratio: a.reduce((u, v) => u + v, 0) / a.length / (x.proj * x.pplay), sd: sd(a) });
}
const med = (v) => { const s = v.slice().sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
out.sim = {};
for (const p of ["K", "DST"]) out.sim[p] = { n: stat[p].length, ratioMin: Math.min(...stat[p].map((x) => x.ratio)), ratioMax: Math.max(...stat[p].map((x) => x.ratio)), sd: med(stat[p].map((x) => x.sd)) };
const corr = (a, b) => { const n = a.length; let ma = 0, mb = 0; for (let i = 0; i < n; i++) { ma += a[i]; mb += b[i]; } ma /= n; mb /= n; let c = 0, va = 0, vb = 0; for (let i = 0; i < n; i++) { c += (a[i] - ma) * (b[i] - mb); va += (a[i] - ma) ** 2; vb += (b[i] - mb) ** 2; } return c / Math.sqrt(va * vb); };
const qbDst = [], qbK = [];
for (const t of Object.keys(DB.opp || {})) {
  const qb = DB.players.filter((p) => p.t === t && p.p === "QB" && sim.pts.has(p.id)).sort((a, b) => sim.inp.get(b.id).proj - sim.inp.get(a.id).proj)[0];
  const d = DB.players.find((p) => p.p === "DST" && p.t === DB.opp[t] && sim.pts.has(p.id)), kk = DB.players.find((p) => p.p === "K" && p.t === t && sim.pts.has(p.id));
  if (qb && d) qbDst.push(corr(sim.pts.get(qb.id), sim.pts.get(d.id)));
  if (qb && kk) qbK.push(corr(sim.pts.get(qb.id), sim.pts.get(kk.id)));
}
const avg = (v) => v.reduce((a, b) => a + b, 0) / Math.max(1, v.length);
out.sim.corr = { qbOppDst: avg(qbDst), qbOwnK: avg(qbK), n: qbDst.length };
const ss = E.startSit(ctx, L.teams[0], L.teams[1], { n: 3000 });
out.sim.startSit = { kd: ss.kd, slots: ss.slots.length, best: ss.best.ids.length, bestKd: ss.best.ids.filter((id) => ["K", "DST"].includes(byId.get(id).p)).length };
// ESPN import: a kicker, a D/ST and their scoring rules
const kp = kd.find((p) => p.p === "K" && p.espn), dp = kd.find((p) => p.p === "DST");
const espn = { id: 1, seasonId: DB.season, scoringPeriodId: DB.curWeek, settings: {
  name: "Test", size: 2, scheduleSettings: { matchupPeriodCount: 14, playoffTeamCount: 4 },
  rosterSettings: { lineupSlotCounts: { 0: 1, 2: 2, 4: 2, 6: 1, 23: 1, 17: 1, 16: 1 } },
  scoringSettings: { scoringItems: [{ statId: 3, points: 0.04 }, { statId: 24, points: 0.1 }, { statId: 42, points: 0.1 }, { statId: 53, points: 1 },
    { statId: 86, points: 1 }, { statId: 80, points: 3 }, { statId: 77, points: 4 }, { statId: 74, points: 5 }, { statId: 85, points: -1 },
    { statId: 99, points: 1 }, { statId: 95, points: 2 }, { statId: 96, points: 2 }, { statId: 98, points: 2 }, { statId: 103, points: 6 }, { statId: 104, points: 6 },
    { statId: 101, points: 6 }, { statId: 102, points: 6 }, { statId: 97, points: 2 }, { statId: 89, points: 10 }, { statId: 90, points: 7 }, { statId: 125, points: -4 },
    { statId: 128, points: 5 }, { statId: 136, points: -7 }] } },
  teams: [{ id: 1, name: "A", roster: { entries: [{ playerId: kp.espn, playerPoolEntry: { player: { id: kp.espn, defaultPositionId: 5, fullName: kp.n } } },
    { playerId: dp.espn, playerPoolEntry: { player: { id: dp.espn, defaultPositionId: 16, fullName: dp.n } } }] } }, { id: 2, name: "B", roster: { entries: [] } }] };
const imp = E.parseEspn(espn, DB, {});
out.espn = { roster: imp.teams[0].roster, want: [kp.id, dp.id], slots: imp.settings.slots, report: imp.report,
  scoring: Object.fromEntries(["patMade", "fg0", "fg40", "fg50", "fg60", "fgMiss", "sack", "dInt", "dTd", "stTd", "paTier", "yaTier"].map((k) => [k, imp.settings.scoring[k]])) };
// The shape ESPN really sends (a public league's mSettings, Oct 2026): D/ST rules only as an override on the D/ST
// slot (16) with points 0, FG 50-59 as stat 198 and 60+ as 201. The first importer read `points` only and gave
// such leagues D/ST scoring of touchdowns alone and nothing for 50-59 yard field goals.
const real = [[85, -1], [86, 1], [80, 3], [77, 4], [198, 5], [201, 6]].map(([statId, points]) => ({ statId, points, pointsOverrides: {} }))
  .concat([[89, 5], [90, 4], [91, 3], [92, 1], [95, 2], [96, 2], [97, 2], [98, 2], [99, 1], [123, -1], [124, -3], [125, -5],
    [128, 5], [129, 3], [130, 2], [132, -1], [133, -3], [134, -5], [135, -6], [136, -7]].map(([statId, p]) => ({ statId, points: 0, pointsOverrides: { 16: p } })))
  .concat([93, 101, 102, 103, 104].map((statId) => ({ statId, points: 6, pointsOverrides: { 16: 6 } })));
const espn2 = JSON.parse(JSON.stringify(espn));
espn2.settings.scoringSettings.scoringItems = espn.settings.scoringSettings.scoringItems.slice(0, 4).concat(real);
const imp2 = E.parseEspn(espn2, DB, {});
const sc2 = imp2.settings.scoring;
out.espnReal = { scoring: Object.fromEntries([...E.K_KEYS, ...E.D_KEYS, "paTier", "yaTier"].map((k) => [k, sc2[k]])), ignored: imp2.report.ignoredScoring };
// projected points this week under the imported rules vs ESPN standard, averaged over every kicker and defense
const wk = String(DB.curWeek), mean = (a) => a.reduce((s, x) => s + x, 0) / Math.max(1, a.length);
for (const p of ["K", "DST"]) {
  const ps = kd.filter((x) => x.p === p && x.kw && x.kw[wk]);
  out.espnReal[p] = { imported: mean(ps.map((x) => E.scoreComp(x.kw[wk], sc2, p))), standard: mean(ps.map((x) => E.scoreComp(x.kw[wk], sc, p))) };
}
process.stdout.write(JSON.stringify(out));
