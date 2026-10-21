// Waiver board checks on a fixed week (tests/run_tests.py reads the JSON this prints).
//   node tests/waiver_checks.js ENGINE.js DB.json BANK.json
// bank:     decodes; every offensive position has rows; paths are relative levels (0..2.52) or byes
// tie:      a pickup's value on his projection (every week weighted evenly, a streamer this week too) equals the change
//           in teamValue when he's actually on the roster (rebuilt league, so he's off the wire)
// odds:     the season simulation's title chances add up to 1 across the league and playoff chances to the field size;
//           an unbeaten team's playoff weeks count more, relative to now, than a winless team's
// weights:  every mode keeps the trade tool's total
// room:     room = open spots + players adding nothing; more bench spots add open spots and never shorten a hold
// upside:   scenarios exist for offensive free agents; chances are probabilities; a backup's contingent role is above
//           his projection
// speed:    the whole board (simulation included)
const fs = require("fs");
const [enginePath, dbPath, bankPath] = process.argv.slice(2);
const mod = { exports: {} };
new Function("module", fs.readFileSync(enginePath, "utf8"))(mod);
const E = mod.exports;
const DB = JSON.parse(fs.readFileSync(dbPath, "utf8"));
const bank = JSON.parse(fs.readFileSync(bankPath, "utf8"));
const out = {};

// --- bank
const D = E.stashDecode(bank);
out.bank = { pos: Object.keys(D), rows: Object.fromEntries(Object.entries(D).map(([k, b]) => [k, b.n])) };
let badLevel = 0, nLev = 0;
for (const b of Object.values(D)) for (const p of b.path) for (const v of p) { nLev++; if (!Number.isNaN(v) && (v < 0 || v > 2.6)) badLevel++; }
out.bank.badLevel = badLevel; out.bank.levels = nLev;

// --- a 12-team simulated league (FAAB on), and its first team as "mine"
const L = E.sampleLeague(DB, 11);
const ctx = E.buildCtx(DB, L);
const mine = L.teams[0];
let t0 = Date.now();
const odds = E.seasonOdds(ctx, mine);
const B = E.waiverBoard(ctx, mine, { bank, odds });
out.ms = Date.now() - t0;
out.rows = B.rows.length;

// --- tie to teamValue: on projection, even weights, streamer this week too
const even = E.waiverBoard(ctx, mine, { bank: null, mode: "even", streamNow: true, limit: 400 });
const ties = [];
for (const r of even.rows.filter((x) => x.hold >= ctx.weeks.length).slice(0, 12)) {
  const L2 = JSON.parse(JSON.stringify(L));
  const me2 = L2.teams[0];
  me2.roster = me2.roster.filter((id) => id !== r.drop).concat([r.id]);
  const c2 = E.buildCtx(DB, L2);
  const d = E.teamDepth(ctx, mine);
  const dv = E.teamValue(c2, me2.roster, "a", false, d) - E.teamValue(ctx, mine.roster, "a", false, d);
  ties.push({ id: r.id, board: r.proj, teamValue: dv, diff: Math.abs(r.proj - dv) });
}
out.tie = { n: ties.length, maxDiff: Math.max(...ties.map((x) => x.diff)), worst: ties.sort((a, b) => b.diff - a.diff)[0] };

// --- the season simulation across the league
let sumTitle = 0, sumPO = 0;
const all = L.teams.map((t) => { const o = E.seasonOdds(ctx, t); sumTitle += o.pTitle; sumPO += o.pPlayoffs; return o; });
out.odds = { sumTitle, sumPlayoffs: sumPO, field: all[0].nPO };
// unbeaten vs winless: how much more the playoff weeks count than this week
const L3 = JSON.parse(JSON.stringify(L));
const done = Math.max(1, +L3.settings.curWeek - 1);
L3.teams.forEach((t, i) => { t.wins = i === 0 ? done : i === 1 ? 0 : Math.round(done / 2); t.losses = done - t.wins; });
const c3 = E.buildCtx(DB, L3);
const ratio = (t) => {
  const w = E.waiverWeights(c3, t, "auto").w, ps = +c3.S.playoffStart;
  const po = w.filter((x, i) => c3.weeks[i].w >= ps), reg = w.filter((x, i) => c3.weeks[i].w < ps);
  const avg = (a) => a.reduce((x, y) => x + y, 0) / Math.max(1, a.length);
  return avg(po) / Math.max(1e-9, avg(reg));
};
out.leverage = { unbeaten: ratio(L3.teams[0]), winless: ratio(L3.teams[1]) };

// --- weights keep the total
out.weights = Object.fromEntries(["auto", "even", "now", "playoffs"].map((m) => [m, E.waiverWeights(ctx, mine, m, odds).w.reduce((a, b) => a + b, 0)]));
out.wSum = ctx.wSum;

// --- room
const L4 = JSON.parse(JSON.stringify(L));
L4.settings.bench = (L4.settings.bench ?? 7) + 3;
const c4 = E.buildCtx(DB, L4);
const B4 = E.waiverBoard(c4, L4.teams[0], { bank, odds });
out.room = { room: B.room, open: B.open, dead: B.dead.length, roomMore: B4.room, openMore: B4.open, deadMore: B4.dead.length, holdsNotShorter: B4.rows.every((r) => { const a = B.rows.find((x) => x.id === r.id); return !a || r.hold >= a.hold; }) };

// --- upside
const off = B.rows.filter((r) => ["QB", "RB", "WR", "TE"].includes(r.pos));
out.upside = { offRows: off.length, withScen: off.filter((r) => r.n > 0).length,
  oddsOk: off.every((r) => r.odds == null || (r.odds >= 0 && r.odds <= 1)),
  meanUpsideTop10: off.slice().sort((a, b) => b.upside - a.upside).slice(0, 10).reduce((s, r) => s + r.upside, 0) / 10,
  contAbove: off.filter((r) => r.cont).every((r) => r.relc >= r.rel0 - 1e-9) };
// a backup RB with a real contingent role: relc clearly above rel0
out.upside.backups = off.filter((r) => r.cont && r.relc > r.rel0 + 0.1).length;
console.log(JSON.stringify(out));
