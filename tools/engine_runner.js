// Run the Fantasy Trader engine headlessly on one week's data and print every player's projections.
//
//   node tools/engine_runner.js --engine engine.js --db db.json [--avail avail.json] [--lite]
//
// --engine  engine source (engine/engine.js with its PARAMS line set, or the engine cut out of a page)
// --db      the week's player database (db.json, as embedded in the page)
// --avail   hindsight availability: {"week": W, "played": [ids], "teams": [team codes whose game is final]}.
//           Players on those teams who played are set healthy, the rest out for the week, as if the
//           week's news had been known (a manual "out" entry, the same mechanism the page uses).
// --lite    skip half-PPR/standard and the per-component runs (faster; used by replays)
// Default league settings: 12 teams, PPR (kickers and defenses: ESPN standard). Output: {meta, players: [...]}, one row per player.
const fs = require("fs");
const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const flag = (k) => args.includes(k);
const src = fs.readFileSync(opt("--engine"), "utf8");
const DB = JSON.parse(fs.readFileSync(opt("--db"), "utf8").replace(/<\\\//g, "</"));
const mod = { exports: {} };
new Function("module", src)(mod);
const E = mod.exports;
const KEYS = ["passYd", "passTd", "int", "rushYd", "rushTd", "rec", "recYd", "recTd", "fumble", "twoPt"];
const avail = opt("--avail") ? JSON.parse(fs.readFileSync(opt("--avail"), "utf8")) : null;
const lite = flag("--lite");

const league = (sc, db = DB) => {
  const L = E.newLeague(db);
  L.settings.scoring = { ...sc, byPos: {} };
  if (avail) {
    const played = new Set(avail.played), teams = new Set(avail.teams);
    for (const p of db.players) if (teams.has(p.t)) L.out[p.id] = played.has(p.id) ? 0 : +db.curWeek;
  }
  return L;
};
const base = E.DEFAULT_SETTINGS.scoring;
const unit = (k) => Object.fromEntries(KEYS.map((x) => [x, x === k ? 1 : 0]));
const V = { ppr: E.valuations(DB, league({ ...base, rec: 1 })) };
if (!lite) for (const [name, rec] of [["half", 0.5], ["std", 0]]) V[name] = E.valuations(DB, league({ ...base, rec }));
const comp = lite ? null : KEYS.map((k) => E.usageModel(DB, league(unit(k))).res);
// opportunities: with catch rate, INT rate and fumble rate set to 1, those components count targets,
// pass attempts and (carries + targets) or (attempts + QB carries)
const DB2 = { ...DB, players: DB.players.map((p) => { if (!p.m) return p; const m = p.m.slice(); m[5] = 1; m[10] = 1; m[12] = 1; return { ...p, m }; }) };
// kickers and team defenses (pipeline/kdst.py): projected in standard scoring (receptions don't touch them); no
// carries, targets or attempts, and no per-component runs
const KD = new Set(["K", "DST"]);
const oT = E.usageModel(DB2, league(unit("rec"), DB2)).res, oA = E.usageModel(DB2, league(unit("int"), DB2)).res, oO = E.usageModel(DB2, league(unit("fumble"), DB2)).res;
const r3 = (x) => (x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000);
const r2 = (x) => (x == null || !isFinite(x) ? null : Math.round(x * 100) / 100);
const out = [];
for (const p of DB.players) {
  const v = V.ppr.get(p.id);
  if (!v) continue;
  const env = v.env && v.env[0];
  const kd = KD.has(p.p);
  const tgt = p.p === "QB" || kd ? 0 : oT.get(p.id).now[0], att = p.p === "QB" ? oA.get(p.id).now[0] : 0, opp = kd ? 0 : oO.get(p.id).now[0];
  const row = {
    id: p.id, name: p.n, pos: p.p, team: p.t, age: p.age ?? null, g26: p.g26 || 0, g25: p.g25 || 0, g24: p.g24 || 0,
    dc: p.dc ?? null, er: p.er ?? null, ew: p.ew ?? null, own: p.own ?? null, inj: p.inj || "",
    ij_thru: p.ij && p.ij.thru != null ? p.ij.thru : null, avail: v.avail[0] ? 1 : 0,
    page_ppr: r3(v.weekly[0]), model_ppr: r3(v.modelWeekly[0]), corr_ppr: r3(v.corr), wkexp_ppr: r3(v.wkExp),
    back: r3(v.back ? v.back[0] : 1), role_shift: r3(v.roleShift),
    env_x: env ? r3(env.x) : null, env_spread: env ? r3(env.s) : null, env_imp: env ? r3(env.imp) : null,
    o_tgt: r3(tgt), o_car: r3(p.p === "QB" ? opp - att : opp - tgt), o_att: r3(att),
    // rest of season, one entry per week from this week on (as if he plays) and whether he's expected to
    page_wk: Array.from(v.weekly, r2), model_wk: Array.from(v.modelWeekly, r2), avail_wk: v.avail.map((x) => (x ? 1 : 0)),
  };
  if (!lite) {
    row.page_half = r3(V.half.get(p.id).weekly[0]);
    row.page_std = r3(V.std.get(p.id).weekly[0]);
    ["py", "ptd", "int", "ry", "rtd", "rec", "recy", "rectd", "fl", "two"].forEach((c, i) => { row["c_" + c] = kd ? 0 : r3(comp[i].get(p.id).now[0]); });
  }
  out.push(row);
}
process.stdout.write(JSON.stringify({ meta: { builtAt: DB.builtAt, asOf: DB.asOf, season: DB.season, week: DB.curWeek,
  weeks: V.ppr.weeks, ewWeek: DB.ewWeek ?? null, sources: DB.sources, params: E.PARAMS || null,
  expertWeight: E.DEFAULT_SETTINGS.expertWeight, weeklyExpert: E.DEFAULT_SETTINGS.weeklyExpert, hindsight: !!avail }, players: out }));
