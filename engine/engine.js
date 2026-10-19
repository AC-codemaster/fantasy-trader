/* Fantasy Trader valuation engine. Pure functions; no DOM. */
// Tuned constants. tools/make_page.py writes this line from params/params.json; the weekly improvement loop tunes them.
const PARAMS = {"damp":0.3,"ret_disc":0.85,"env_scale":1,"expertWeight":0.2,"weeklyExpert":0.25};
const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"];
const OFF_POS = ["QB", "RB", "WR", "TE"];        // the usage model's positions (team carries, targets, attempts)
const KD_POS = ["K", "DST"];                      // kickers and team defenses: projected by the builder (pipeline/kdst.py)
const POS_LABEL = { DST: "D/ST" };
const FLEX_OK = { RB: 1, WR: 1, TE: 1 };
const SCORE_KEYS = ["passYd", "passTd", "int", "rushYd", "rushTd", "rec", "recYd", "recTd", "fumble", "twoPt"];
// Kicker and D/ST scoring. A kicker's weekly line is [PAT made, PAT missed, FG made 0-39, 40-49, 50-59, 60+, FG
// missed 0-39, 40-49, 50+]; a D/ST's is [sacks, INTs, fumble recoveries, safeties, defensive TDs, return TDs,
// blocked kicks, points allowed, yards allowed, then the chance of each points-allowed tier (ESPN's 0, 1-6, 7-13,
// 14-17, 18-21, 22-27, 28-34, 35-45, 46+) and each yards-allowed tier (<100, 100-199, 200-299, 300-349, 350-399,
// 400-449, 450-499, 500-549, 550+)]. Defaults: ESPN standard (pipeline/kdst.py STANDARD, kept equal by the tests).
const K_KEYS = ["patMade", "patMiss", "fg0", "fg40", "fg50", "fg60", "fgMiss", "fgMiss0", "fgMiss40", "fgMiss50"];
const D_KEYS = ["sack", "dInt", "fumRec", "safety", "dTd", "stTd", "blk", "ptsAllowed", "ydsAllowed"];
const PA_TIERS = ["0", "1-6", "7-13", "14-17", "18-21", "22-27", "28-34", "35-45", "46+"];
const YA_TIERS = ["<100", "100-199", "200-299", "300-349", "350-399", "400-449", "450-499", "500-549", "550+"];

const DEFAULT_SETTINGS = {
  teams: 12,
  scoring: { passYd: 0.04, passTd: 4, int: -2, rushYd: 0.1, rushTd: 6, rec: 1, recYd: 0.1, recTd: 6, fumble: -2, twoPt: 2, byPos: {},
    patMade: 1, patMiss: 0, fg0: 3, fg40: 4, fg50: 5, fg60: 6, fgMiss: -1, fgMiss0: 0, fgMiss40: 0, fgMiss50: 0,
    sack: 1, dInt: 2, fumRec: 2, safety: 2, dTd: 6, stTd: 6, blk: 2, ptsAllowed: 0, ydsAllowed: 0,
    paTier: [5, 4, 3, 1, 0, 0, -1, -3, -5], yaTier: [5, 3, 2, 0, -1, -3, -5, -6, -7] },
  slots: { QB: 1, RB: 2, WR: 2, TE: 1, RBWR: 0, WRTE: 0, FLEX: 1, OP: 0, K: 1, DST: 1 },
  expertWeight: PARAMS.expertWeight,  // rest-of-season FantasyPros consensus (tuned by the improvement loop)
  weeklyExpert: PARAMS.weeklyExpert, // FantasyPros weekly rankings, current week only (tuned; skipped for players with an injury tag)
  waiver: true,       // every lineup can start the best available free agent ("streaming")
  waiverDepth: 2,     // 1 = you get the best free agent each week, 2 = second best, ...
  faab: false,        // league uses a free agent acquisition budget
  faabBudget: 100,    // each team's starting budget
  // what managers look at when they size up a player (relative weights)
  perc: { season: 0.2, form: 0.15, prk: 0.1, track: 0.2, adp: 0.15, rost: 0.1, start: 0.15, espn: 0.15, experts: 0.15, news: 0.15 },
  proven: 0.15,       // trade-value premium managers pay for a player with a long, good track record (certainty)
  curWeek: 4,
  lastWeek: 17,
  playoffStart: 15,
  playoffWeight: 1.5,
  cushion: true,
  needWeight: 0.6,
  standings: 0.5,     // pts/wk of edge a winless manager gives up (an unbeaten one adds) before he'll deal
  consensus: 0.5,     // in trade talks, share of a player's price taken from cross-positional consensus rankings
  stubborn: 0.5,
  spread: 1.5,
  attachment: 1.2,
};

function newLeague(DB) {
  return {
    v: 3,
    name: "My league",
    example: false,
    settings: JSON.parse(JSON.stringify({ ...DEFAULT_SETTINGS, curWeek: DB.curWeek, lastWeek: Math.min(17, DB.lastWeek) })),
    teams: [],
    out: {},
    autoOut: {},
    overrides: {},
    espn: null,
  };
}

/* A league setting for kickers and defenses, falling back to ESPN standard when a saved league predates it. */
function kdSet(sc, k) { const v = sc[k]; return v == null || v === "" ? DEFAULT_SETTINGS.scoring[k] : v; }
function kScore(v, sc) {
  const g = (k) => +kdSet(sc, k) || 0;
  const miss = v[6] + v[7] + v[8];
  return v[0] * g("patMade") + v[1] * g("patMiss") + v[2] * g("fg0") + v[3] * g("fg40") + v[4] * g("fg50") + v[5] * g("fg60")
    + miss * g("fgMiss") + v[6] * g("fgMiss0") + v[7] * g("fgMiss40") + v[8] * g("fgMiss50");
}
function dScore(v, sc) {
  const g = (k) => +kdSet(sc, k) || 0;
  const pt = kdSet(sc, "paTier") || [], yt = kdSet(sc, "yaTier") || [];
  let s = v[0] * g("sack") + v[1] * g("dInt") + v[2] * g("fumRec") + v[3] * g("safety") + v[4] * g("dTd") + v[5] * g("stTd") + v[6] * g("blk")
    + v[7] * g("ptsAllowed") + v[8] * g("ydsAllowed");
  for (let i = 0; i < 9; i++) s += (v[9 + i] || 0) * (+pt[i] || 0) + (v[18 + i] || 0) * (+yt[i] || 0);
  return s;
}

function scoreComp(v, sc, pos) {
  if (pos === "K") return kScore(v, sc);
  if (pos === "DST") return dScore(v, sc);
  const bp = (sc.byPos && pos && sc.byPos[pos]) || null;
  let s = 0;
  for (let i = 0; i < SCORE_KEYS.length; i++) {
    const k = SCORE_KEYS[i];
    const pts = bp && bp[k] != null && bp[k] !== "" ? +bp[k] : +sc[k] || 0;
    s += v[i] * pts;
  }
  return s;
}

function outWeek(L, id) {
  const o = L.out && L.out[id];
  if (o != null && o !== "") return +o;
  const a = L.autoOut && L.autoOut[id];
  return a != null && a !== "" ? +a : null;
}

/* Last week a player misses: your entry, then the league's ESPN-based value (0 = known healthy),
   then the injury timeline built into the weekly data. */
function effOut(L, p, cur) {
  if (!p) return null;
  const o = outWeek(L, p.id);
  if (o != null) return o > 0 ? o : null;
  return p.ij && p.ij.thru != null && p.ij.thru >= cur ? p.ij.thru : null;
}

/* Map a rank (1 = best) onto a sorted-descending curve of points per game. Ties share the average. */
function curveAt(curve, r) {
  if (!curve.length) return 0;
  const i = Math.max(0, Math.min(curve.length - 1, Math.round(r) - 1));
  return curve[i];
}

/* Rank players by a score (desc) and map to the curve; equal scores share the mean of their curve values. */
function rankToCurve(entries, curve, tol) {
  const out = new Map();
  entries.sort((x, y) => y.v - x.v);
  let i = 0;
  while (i < entries.length) {
    let j = i;
    while (j + 1 < entries.length && Math.abs(entries[j + 1].v - entries[i].v) <= tol) j++;
    let sum = 0;
    for (let k = i; k <= j; k++) sum += curveAt(curve, k + 1);
    const val = sum / (j - i + 1);
    for (let k = i; k <= j; k++) out.set(entries[k].id, { val, rank: i + 1, ties: j - i + 1 });
    i = j + 1;
  }
  return out;
}

const HOT_K = 3; // games of prior belief behind production signals
const SIGNALS = ["season", "form", "prk", "track", "adp", "rost", "start", "espn", "experts", "news"];
// Manager style (0 = casual, 1 = dedicated) reweights what a manager looks at. Casual managers go by
// results (this season's and the last two); dedicated ones by expert rankings, projections, news and
// usage data (our projection).
const RESULT_SIGS = ["season", "form", "prk"];           // this season's results: small samples, regressed
const STYLE_RESULT_SIGS = RESULT_SIGS.concat(["track"]); // what casual managers lean on
const DATA_SIGS = ["experts", "espn", "news"];
const PRIOR_SIGS = ["adp", "experts", "espn", "rost", "start", "track"];
// Track record: points per game over the last two seasons (last season counts double). A player who
// produced for two full seasons anchors managers' belief: a slow start (or a hot one) moves him less,
// as if his record were TRACK_K more games of prior. Needs TRACK_MIN weighted games to count at all.
const TRACK_K = 4, TRACK_FULL = 24, TRACK_MIN = 6, TRACK_W24 = 0.5;
function styleOf(ctx, team) {
  const v = team && team.style;
  return v == null || v === "" || !isFinite(+v) ? 0.5 : Math.max(0, Math.min(1, +v));
}
/* A manager's favorite NFL team and how big a fan he is (0 casual fan .. 1 diehard). */
const FAN_KNOW = 0.7;      // a diehard sees his team's players this close to their real value (our projection)
const FAN_PREMIUM = 0.06;  // ...and values them this much extra (homer bump)
function fanOf(team) {
  const fav = team && team.fav ? String(team.fav) : "";
  if (!fav) return { fav: "", fan: 0 };
  const f = team.fan == null || team.fan === "" || !isFinite(+team.fan) ? 0.5 : Math.max(0, Math.min(1, +team.fan));
  return { fav, fan: f };
}
function styleWeights(S, style) {
  const s = Math.max(0, Math.min(1, style == null ? 0.5 : +style));
  const base = S.perc || {}, w = {};
  let tot = 0;
  for (const k of SIGNALS) {
    let x = Math.max(0, +(base[k] ?? 0));
    tot += x;
    if (STYLE_RESULT_SIGS.includes(k)) x *= 1.75 - 1.5 * s;
    if (DATA_SIGS.includes(k)) x *= 0.25 + 1.5 * s;
    w[k] = x;
  }
  // dedicated managers also read usage (snap and target shares, who's hurt): our projection
  w.proj = Math.max(0, 2 * s - 1) * 0.15 * tot;
  // casual managers take a hot start at face value; dedicated ones discount small samples more
  return { w, hotK: HOT_K * (0.25 + 1.5 * s), s };
}
/* A manager's view of a player: the weighted average of his signals, with production signals pulled
   toward the prior-belief signals as if that prior were hotK games. mutate=true writes the shown
   values back into the signals (the league's default view, for the player breakdown). */
function perceive(sig, g, w, hotK, mutate) {
  const raw = (k) => (sig[k] ? (sig[k].raw0 != null ? sig[k].raw0 : sig[k].v) : null);
  let pn = 0, pd = 0;
  for (const k of PRIOR_SIGS) { const wt = w[k] || 0, r = raw(k); if (r != null && wt > 0) { pn += wt * r; pd += wt; } }
  const prior = pd > 0 ? pn / pd : null;
  // a long track record makes the prior sturdier, for every manager (casual ones go by names too)
  const hk = hotK + ((w.track || 0) > 0 && sig.track ? TRACK_K * sig.track.full : 0);
  let num = 0, den = 0;
  for (const k of SIGNALS.concat(["proj"])) {
    const r = raw(k);
    if (r == null) continue;
    const n = k === "form" ? Math.min(2, g) : RESULT_SIGS.includes(k) ? g : 0;
    const v = prior != null && n > 0 && hk > 0 ? (n * r + hk * prior) / (n + hk) : r;
    let wt = w[k] || 0;
    if (sig[k].ties > 3) wt *= 3 / sig[k].ties;
    if (mutate) { if (v !== r) sig[k].raw0 = r; sig[k].v = v; sig[k].wt = wt > 0 ? wt : 0; }
    if (wt <= 0) continue;
    num += wt * v; den += wt;
  }
  return den > 0 ? num / den : null;
}

/* Points per game from team-share weights m and the team's pools, for given pool denominators. */
function sharePts(p, T, dr, dt, dp, sc, f = 1, E = null) {
  const m = p.m;
  // f: his share weight this week (0.85 in a first game back); E: game environment multipliers
  const vr = E ? E.vr : 1, vp = E ? E.vp : 1;
  const car = dr > 0 ? (T.r * vr * m[0] * f) / dr : 0, tgt = dt > 0 ? (T.t * vp * m[1] * f) / dt : 0, att = dp > 0 ? (T.p * vp * m[2] * f) / dp : 0;
  const ey = E ? E.py : 1, et = E ? E.pt : 1, ry = E ? E.ry : 1, rt = E ? E.rt : 1;
  let v;
  if (p.p === "QB") {
    const qc = att * m[11], opp = att + qc;
    v = [att * m[8] * ey, att * m[9] * et, att * m[10], qc * m[3] * ry, qc * m[4] * rt, 0, 0, 0, opp * m[12], opp * m[13]];
  } else {
    const opp = car + tgt;
    v = [0, 0, 0, car * m[3] * ry, car * m[4] * rt, tgt * m[5], tgt * m[6] * ey, tgt * m[7] * et, opp * m[12], opp * m[13]];
  }
  return scoreComp(v, sc, p.p);
}

/* Expected carries, targets and pass attempts behind sharePts (the same expressions, so the two always agree). */
function shareOpp(p, T, dr, dt, dp, f = 1, E = null) {
  const m = p.m, vr = E ? E.vr : 1, vp = E ? E.vp : 1;
  return [dr > 0 ? (T.r * vr * m[0] * f) / dr : 0, dt > 0 ? (T.t * vp * m[1] * f) / dt : 0, dp > 0 ? (T.p * vp * m[2] * f) / dp : 0];
}

/*
 * Game environment. A team's Vegas implied total vs its usual level (x) and the spread (s, + =
 * favored) scale its volume and per-play production; fit on 2022-25 team games (log change vs the
 * team's usual per unit of x, and per point of spread). Pass yards, for instance, move 0.57 × x, so a
 * team expected to score 10% more than usual throws for about 6% more yards; favorites run more.
 */
const ENV_K = { att: [0.2378, -0.00353], pyd: [0.5709, -0.0025], ptd: [0.6785, -0.00071], car: [-0.0775, 0.00735], ryd: [0.1785, 0.00615], rtd: [0.4132, 0.00569] };
function envMult(T, w) {
  const e = T && T.env && T.env[w];
  if (!e) return null;
  const [x, s] = e, k = ENV_K, g = PARAMS.env_scale ?? 1, f = (a) => Math.exp(g * (a[0] * x + a[1] * s));
  const vp = f(k.att), vr = f(k.car);
  return { vp, vr, py: f(k.pyd) / vp, pt: f(k.ptd) / vp, ry: f(k.ryd) / vr, rt: f(k.rtd) / vr, x, s, imp: e[2] };
}
const DAMP = PARAMS.damp ?? 0.3;        // share of a short-term absentee's work that goes to depth players we don't model
const RETURN_F = PARAMS.ret_disc ?? 0.85;   // share weight in a player's first game back (tuned by the improvement loop)
const RESERVE_RE = /^(IR|PUP|NFI|Out for season|Exempt)/;

/*
 * Weekly usage model. Each team's carries, targets and pass attempts are split among the
 * players healthy that week, in proportion to their share weights. Returns, per player,
 * points per game for each remaining week (as if he plays), under three states:
 *   now:   who is actually expected to be available
 *   ecr:   only the absences the experts already knew about when they ranked
 *   full:  everyone healthy
 * Backtested refinements: game environment per team-week; when a teammate misses a week or two
 * (not a reserve-list absence), 30% of his carries/targets go to depth players instead of being
 * split among the regulars; a player's first game back counts at 85% of his usual share.
 */
function usageModel(DB, L) {
  const S = L.settings, sc = S.scoring, cur = +S.curWeek;
  const weeks = [];
  for (let w = cur; w <= +S.lastWeek; w++) weeks.push(w);
  const nW = weeks.length;
  const teams = DB.teams || {};
  const byTeam = new Map();   // the usage model's players (kickers and defenses have no share of the team's work)
  for (const p of DB.players) { if (!p.m) continue; if (!byTeam.has(p.t)) byTeam.set(p.t, []); byTeam.get(p.t).push(p); }
  const outNow = new Map(DB.players.map((p) => [p.id, effOut(L, p, cur)]));
  const outEcr = (p) => (p.ij && p.ij.thru != null && !p.ij.nx && p.ij.thru >= cur ? p.ij.thru : null);
  const isOut = (o, w) => o != null && w <= o;
  // short absence: not on a reserve list, and back within two weeks of now
  const shortOut = (p, o) => o != null && o - cur <= 1 && !(p.ij && p.ij.thru === o && RESERVE_RE.test(p.ij.st || ""));
  const res = new Map(), opp0 = new Map(), den0 = new Map();
  for (const [tm, ps] of byTeam) {
    const T = teams[tm];
    if (!T) { for (const p of ps) res.set(p.id, { now: new Float64Array(nW), ecr: new Float64Array(nW), full: 0, avail: new Array(nW).fill(false) }); continue; }
    const byes = DB.byes[tm] || [];
    // the team's most recent game before this week (players who missed it are coming back)
    let lastGame = 0;
    for (let w = cur - 1; w >= 1; w--) if (!byes.includes(w)) { lastGame = w; break; }
    const full = [T.or, T.ot, T.op];
    for (const q of ps) for (let c = 0; c < 3; c++) full[c] += q.m[c];
    const env = weeks.map((w) => envMult(T, w));
    // share-weight factor per player-week: first game back after an absence counts less
    const backF = (q, o, wi) => {
      const w = weeks[wi];
      if (isOut(o, w) || byes.includes(w)) return 1;
      if (wi === 0) return lastGame && q.lg != null && q.lg < lastGame ? RETURN_F : (lastGame && q.lg == null && !q.g26 ? RETURN_F : 1);
      // first available week after an out stretch inside the horizon
      let pw = wi - 1;
      while (pw >= 0 && byes.includes(weeks[pw])) pw--;
      if (pw < 0) return 1;
      return isOut(o, weeks[pw]) ? RETURN_F : 1;
    };
    const fNow = new Map(), fEcr = new Map();
    for (const q of ps) {
      fNow.set(q.id, weeks.map((w, wi) => backF(q, outNow.get(q.id), wi)));
      fEcr.set(q.id, weeks.map((w, wi) => backF(q, outEcr(q), wi)));
    }
    const dNow = [], dEcr = [];
    for (let wi = 0; wi < nW; wi++) {
      const w = weeks[wi];
      const a = [T.or, T.ot, T.op], e = [T.or, T.ot, T.op], aS = [0, 0], eS = [0, 0];
      for (const q of ps) {
        const on = outNow.get(q.id), oe = outEcr(q);
        if (!isOut(on, w)) { const f = fNow.get(q.id)[wi]; for (let c = 0; c < 3; c++) a[c] += q.m[c] * f; }
        else if (shortOut(q, on)) { aS[0] += q.m[0]; aS[1] += q.m[1]; }
        if (!isOut(oe, w)) { const f = fEcr.get(q.id)[wi]; for (let c = 0; c < 3; c++) e[c] += q.m[c] * f; }
        else if (shortOut(q, oe)) { eS[0] += q.m[0]; eS[1] += q.m[1]; }
      }
      a[0] += DAMP * aS[0]; a[1] += DAMP * aS[1];
      e[0] += DAMP * eS[0]; e[1] += DAMP * eS[1];
      dNow.push(a); dEcr.push(e);
    }
    if (nW) den0.set(tm, dNow[0].slice());
    for (const p of ps) {
      const now = new Float64Array(nW), ecr = new Float64Array(nW), fullW = new Float64Array(nW), avail = [];
      const on = outNow.get(p.id), oe = outEcr(p);
      for (let wi = 0; wi < nW; wi++) {
        const w = weeks[wi];
        const a = dNow[wi], e = dEcr[wi];
        // as if he plays: if he's out, add his own (full) weight back
        const fa = isOut(on, w) ? 1 : fNow.get(p.id)[wi], fe = isOut(oe, w) ? 1 : fEcr.get(p.id)[wi];
        // (if his own absence was counted in the depth-player share, take that back out)
        const addA = isOut(on, w) ? 1 - (shortOut(p, on) ? DAMP : 0) : 0, addE = isOut(oe, w) ? 1 - (shortOut(p, oe) ? DAMP : 0) : 0;
        now[wi] = sharePts(p, T, a[0] + addA * p.m[0], a[1] + addA * p.m[1], a[2] + (isOut(on, w) ? p.m[2] : 0), sc, fa, env[wi]);
        // this week's expected carries, targets and attempts (same split as above): the start/sit simulation's inputs
        if (wi === 0) opp0.set(p.id, shareOpp(p, T, a[0] + addA * p.m[0], a[1] + addA * p.m[1], a[2] + (isOut(on, w) ? p.m[2] : 0), fa, env[wi]));
        ecr[wi] = sharePts(p, T, e[0] + addE * p.m[0], e[1] + addE * p.m[1], e[2] + (isOut(oe, w) ? p.m[2] : 0), sc, fe, env[wi]);
        // everyone healthy, same game environment and his own first-game-back factor: the yardstick for role changes
        fullW[wi] = sharePts(p, T, full[0] - (1 - fa) * p.m[0], full[1] - (1 - fa) * p.m[1], full[2] - (1 - fa) * p.m[2], sc, fa, env[wi]);
        avail.push(!byes.includes(w) && !isOut(on, w));
      }
      res.set(p.id, { now, ecr, full: sharePts(p, T, full[0], full[1], full[2], sc), fullW, avail, back: fNow.get(p.id), env });
    }
  }
  kdModel(DB, L, weeks, outNow, res);
  return { weeks, res, byTeam, outNow, opp0, den0 };
}

/*
 * Kickers and team defenses. The builder (pipeline/kdst.py) projects each one's stat line for every remaining week
 * from the Vegas lines (his team's implied total for a kicker; the opponent's for a defense) and their histories;
 * here they are scored with the league's settings, as if he plays, and marked unavailable on byes and out weeks.
 * No teammate effects, so the experts' information state and full health are the same as now.
 */
function kdModel(DB, L, weeks, outNow, res) {
  const sc = L.settings.scoring, nW = weeks.length;
  for (const p of DB.players) {
    if (p.m || !p.kw) continue;
    const now = new Float64Array(nW), avail = [], byes = DB.byes[p.t] || [], o = outNow.get(p.id), T = (DB.teams || {})[p.t];
    let s = 0, n = 0;
    for (let wi = 0; wi < nW; wi++) {
      const w = weeks[wi], v = p.kw[w];
      now[wi] = v ? scoreComp(v, sc, p.p) : 0;
      if (v) { s += now[wi]; n++; }
      avail.push(!!v && !byes.includes(w) && !(o != null && w <= o));
    }
    res.set(p.id, { now, ecr: now, full: n ? s / n : 0, fullW: now, avail, back: new Array(nW).fill(1), env: weeks.map((w) => envMult(T, w)) });
  }
}

function meanOver(arr, mask) {
  let s = 0, n = 0;
  for (let i = 0; i < arr.length; i++) if (mask[i]) { s += arr[i]; n++; }
  if (n) return s / n;
  for (let i = 0; i < arr.length; i++) s += arr[i];
  return arr.length ? s / arr.length : 0;
}

/*
 * Per-player projection (actual, by week) and market view (perceived), in points per game.
 *  actual(week) = usage model(week) + e * (expert-implied − usage model under the experts' information)
 *    The expert consensus rank is read off the model's own points-by-rank curve. The correction is
 *    measured against what the model says given only the injuries the experts knew about, so news
 *    since the rankings (a starter's injury) isn't cancelled out by stale ranks.
 *  perceived = weighted average of the signals a manager sees, each converted to points.
 */
function valuations(DB, L) {
  const S = L.settings, sc = S.scoring;
  const ext = (L.espn && L.espn.players) || {};
  const cur = +S.curWeek;
  const W = Math.max(0, Math.min(1, +S.expertWeight || 0));
  const WE = Math.max(0, Math.min(1, S.weeklyExpert == null ? DEFAULT_SETTINGS.weeklyExpert : +S.weeklyExpert));
  const weeklyOk = DB.ewWeek != null && +DB.ewWeek === cur;
  const U = usageModel(DB, L);
  const res = new Map();
  for (const pos of POSITIONS) {
    const ps = DB.players.filter((p) => p.p === pos);
    const um = (p) => U.res.get(p.id);
    const modelAvg = new Map(ps.map((p) => [p.id, meanOver(um(p).now, um(p).avail)]));
    const ecrAvg = new Map(ps.map((p) => [p.id, meanOver(um(p).ecr, um(p).avail)]));
    const season = new Map(ps.filter((p) => p.g26 > 0).map((p) => [p.id, scoreComp(p.s, sc, pos)]));
    const form = new Map(ps.filter((p) => p.g26 > 0).map((p) => [p.id, scoreComp(p.f, sc, pos)]));
    // track record: last two seasons' points per game, 2025 games counting double 2024's
    const track = new Map();
    for (const p of ps) {
      const w5 = p.s25 ? Math.max(0, +p.g25 || 0) : 0, w4 = p.s24 ? TRACK_W24 * Math.max(0, +p.g24 || 0) : 0;
      if (w5 + w4 < TRACK_MIN) continue;
      const y25 = p.s25 ? scoreComp(p.s25, sc, pos) : null, y24 = p.s24 ? scoreComp(p.s24, sc, pos) : null;
      track.set(p.id, { v: (w5 * (y25 || 0) + w4 * (y24 || 0)) / (w5 + w4), full: Math.min(1, (w5 + w4) / TRACK_FULL),
        y25, y24, g25: +p.g25 || 0, g24: +p.g24 || 0 });
    }
    const longOut = (p) => { const o = U.outNow.get(p.id); return o != null && o >= cur + 1; };

    // --- expert consensus mapped onto the model's curve (experts' information state)
    const curveA = ps.filter((p) => !longOut(p)).map((p) => ecrAvg.get(p.id)).sort((x, y) => y - x);
    const byModel = ps.slice().sort((x, y) => ecrAvg.get(y.id) - ecrAvg.get(x.id));
    const modelRank = new Map(byModel.map((p, i) => [p.id, i + 1]));
    const nListed = (DB.rosN && DB.rosN[pos]) || 0;
    // expert disagreement grows with rank, so judge each player's spread against the usual
    // spread at his rank: a least-squares line of std dev on rank, per position
    const ranked = ps.filter((p) => p.er != null && p.es != null);
    let sa = 0, sb = 0, sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (const p of ranked) { sx += p.er; sy += p.es; sxx += p.er * p.er; sxy += p.er * p.es; }
    const nR = ranked.length;
    if (nR >= 5) { sb = (nR * sxy - sx * sy) / Math.max(1e-9, nR * sxx - sx * sx); sa = (sy - sb * sx) / nR; }
    else { sa = 2; sb = 0; }
    const usualSd = (r) => Math.max(0.5, sa + sb * r);
    // this week's model points by rank (players available this week), for the weekly expert ranks
    const curveWk = ps.filter((p) => um(p).avail[0]).map((p) => um(p).now[0]).sort((x, y) => y - x);

    // --- perceived: signals mapped to points on the market's own scale (season averages)
    // Early in the season the points-by-rank leaderboard is mostly luck (the WR1 after 3 games is
    // far above any real WR1), so blend it with the model's curve until more games are played.
    const rawQ = ps.filter((p) => p.g26 >= 2).map((p) => season.get(p.id)).sort((x, y) => y - x);
    const curveM = ps.filter((p) => !longOut(p)).map((p) => modelAvg.get(p.id)).sort((x, y) => y - x);
    const G = Math.max(0, +DB.doneWeek || 0), KQ = 3;
    let curveQ = rawQ.length < 12 ? curveA : rawQ.map((v, i) => (G * v + KQ * curveAt(curveM, i + 1)) / (G + KQ));
    const tot = ps.filter((p) => p.g26 > 0).map((p) => ({ id: p.id, v: season.get(p.id) * p.g26 }));
    const prkComputed = rankToCurve(tot, curveQ, 1e-9);
    const prkEspn = rankToCurve(ps.filter((p) => ext[p.id] && ext[p.id].prk > 0).map((p) => ({ id: p.id, v: -ext[p.id].prk })), curveQ, 1e-9);
    const espnAdp = ps.filter((p) => ext[p.id] && ext[p.id].adp > 0);
    const adpMap = espnAdp.length >= 12
      ? rankToCurve(espnAdp.map((p) => ({ id: p.id, v: -ext[p.id].adp })), curveQ, 1e-9)
      : rankToCurve(ps.filter((p) => p.dp != null).map((p) => ({ id: p.id, v: -p.dp })), curveQ, 1e-9);
    const rostOf = (p) => (ext[p.id] && ext[p.id].rost != null ? ext[p.id].rost : p.own);
    const rostMap = rankToCurve(ps.filter((p) => rostOf(p) != null).map((p) => ({ id: p.id, v: rostOf(p) })), curveQ, 0.25);
    const startMap = rankToCurve(ps.filter((p) => ext[p.id] && ext[p.id].start != null).map((p) => ({ id: p.id, v: ext[p.id].start })), curveQ, 0.25);
    // managers read rankings too: the FantasyPros rest-of-season consensus position rank
    const expMap = rankToCurve(ps.filter((p) => p.er != null).map((p) => ({ id: p.id, v: -p.er })), curveQ, 1e-9);
    // track record by rank: "a top-5 WR the last two years" reads as a top-5 WR on the market's scale
    const trackMap = rankToCurve([...track].map(([id, t]) => ({ id, v: t.v })), curveQ, 1e-9);

    for (const p of ps) {
      const id = p.id, u = um(p);
      const r = p.er != null ? p.er : Math.max(nListed + 1, modelRank.get(id));
      const expert = curveAt(curveA, r);
      const spts = p.er != null && p.es != null ? p.es / usualSd(r) : null;
      let w = W, why = "";
      if (longOut(p)) { w = 0; why = "injured: expert ranks already count missed games"; }
      else if (p.er == null) { w = W * 0.5; why = "experts don't rank him"; }
      else if (spts != null && spts > 1.25) { w = W * Math.max(0.25, 1 / spts); why = `experts disagree ${spts.toFixed(1)}× more than usual at this rank`; }
      const corr = w * (expert - ecrAvg.get(id));
      const weekly = new Float64Array(u.now.length);
      for (let i = 0; i < weekly.length; i++) weekly[i] = Math.max(0, u.now[i] + corr);
      // this week only: FantasyPros weekly rankings (matchups, late news), read off this week's model curve.
      // Skipped for players with an injury tag: their rank prices in the chance he sits, while our
      // projection is for a game he plays.
      let wkExp = null;
      const tagged = /^(Questionable|Doubtful|Out|Limited|DNP)/.test(p.inj || "");
      if (WE > 0 && weeklyOk && p.ew != null && u.avail[0] && curveWk.length && !tagged) {
        wkExp = curveWk[Math.min(p.ew, curveWk.length) - 1];
        weekly[0] = Math.max(0, u.now[0] + corr + WE * (wkExp - u.now[0]));
      }
      const actual = meanOver(weekly, u.avail);
      const m = modelAvg.get(id);
      // role change from teammates' availability (any remaining week differs from full health)
      let roleShift = 0;
      for (let i = 0; i < u.now.length; i++) if (u.avail[i]) { const d = u.now[i] - (u.fullW ? u.fullW[i] : u.full); if (Math.abs(d) > Math.abs(roleShift)) roleShift = d; }
      const roleChanged = Math.abs(roleShift) >= Math.max(1, 0.15 * Math.max(u.full, 1));

      const x = ext[id] || {};
      const sig = {
        season: season.has(id) ? { v: season.get(id) } : null,
        form: form.has(id) ? { v: form.get(id) } : null,
        track: trackMap.has(id) ? { ...track.get(id), ppg: track.get(id).v, v: trackMap.get(id).val, rank: trackMap.get(id).rank } : null,
        prk: prkEspn.has(id) ? { v: prkEspn.get(id).val, rank: x.prk, src: "ESPN" } : prkComputed.has(id) ? { v: prkComputed.get(id).val, rank: prkComputed.get(id).rank } : null,
        adp: adpMap.has(id) ? { v: adpMap.get(id).val, rank: adpMap.get(id).rank, raw: espnAdp.length >= 12 ? x.adp : p.dr, src: espnAdp.length >= 12 ? "ESPN" : "preseason" } : null,
        rost: rostMap.has(id) ? { v: rostMap.get(id).val, raw: rostOf(p) } : null,
        start: startMap.has(id) ? { v: startMap.get(id).val, raw: x.start } : null,
        espn: x.proj != null && x.proj > 0 ? { v: x.proj } : null,
        experts: expMap.has(id) ? { v: expMap.get(id).val, rank: p.er } : null,
        news: roleChanged ? { v: actual, shift: roleShift } : null,
        proj: { v: actual },
      };
      // a crowd signal that can't tell players apart (dozens tied at 99.8% rostered) counts less
      if (sig.rost && rostMap.get(id).ties > 3) sig.rost.ties = rostMap.get(id).ties;
      if (sig.start && startMap.get(id).ties > 3) sig.start.ties = startMap.get(id).ties;
      // A few games are a small sample and managers know it: production signals (season average,
      // form, PRK) are pulled toward what the market believed before them (draft cost, expert rank,
      // ESPN's projection, roster and start rates), as if that prior were worth HOT_K games.
      const pv = perceive(sig, Math.max(0, +p.g26 || 0), styleWeights(S, 0.5).w, HOT_K, true);
      const perceived = pv != null ? pv : actual;
      res.set(id, { model: m, modelEcr: ecrAvg.get(id), full: u.full, expert, expertRank: r, ranked: p.er != null, spts, w, why, corr,
        actual, weekly, modelWeekly: u.now, avail: u.avail, plays: u.avail.some(Boolean), sig, perceived, roleShift, roleChanged,
        wkExp, wkRank: p.ew ?? null, env: u.env, back: u.back });
    }
  }
  res.weeks = U.weeks;
  res.usage = U;
  return res;
}

/* Teammate absences that change a player's role: how many points per game each one is worth to him. */
function roleNotes(ctx, id) {
  const p = ctx.byId.get(id), U = ctx.val.usage;
  if (!p || !U || !p.m) return [];
  const T = (ctx.DB.teams || {})[p.t];
  if (!T) return [];
  const mates = U.byTeam.get(p.t) || [];
  const sc = ctx.S.scoring, weeks = U.weeks, out = [];
  for (const j of mates) {
    if (j.id === id) continue;
    const oj = U.outNow.get(j.id);
    if (oj == null || oj < weeks[0]) continue;
    // first remaining week he's out
    const wi = weeks.findIndex((w) => w <= oj && !(ctx.DB.byes[p.t] || []).includes(w));
    if (wi < 0) continue;
    const w = weeks[wi];
    const d = [T.or, T.ot, T.op];
    for (const q of mates) {
      const oq = U.outNow.get(q.id);
      if (q.id === id || !(oq != null && w <= oq)) for (let c = 0; c < 3; c++) d[c] += q.m[c];
    }
    const without = sharePts(p, T, d[0], d[1], d[2], sc);
    const withJ = sharePts(p, T, d[0] + j.m[0], d[1] + j.m[1], d[2] + j.m[2], sc);
    const delta = without - withJ;
    if (Math.abs(delta) >= 0.5) out.push({ id: j.id, name: j.n, pos: j.p, thru: oj, delta, nx: !!(j.ij && j.ij.nx) });
  }
  return out.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
}

/* Build everything that depends on league settings but not on a specific roster. */
function buildCtx(DB, L) {
  const S = L.settings;
  const byId = new Map(DB.players.map((p) => [p.id, p]));
  const val = valuations(DB, L);
  const ppg = { a: new Map(), q: new Map() };
  const wkA = new Map();
  for (const p of DB.players) {
    const o = (L.overrides || {})[p.id] || {};
    const v = val.get(p.id);
    let weekly = v.weekly;
    if (o.a != null && o.a !== "") {
      const target = +o.a;
      weekly = v.actual > 0 ? weekly.map((x) => (x * target) / v.actual) : weekly.map(() => target);
    }
    wkA.set(p.id, weekly);
    ppg.a.set(p.id, o.a != null && o.a !== "" ? +o.a : v.actual);
    ppg.q.set(p.id, o.q != null && o.q !== "" ? +o.q : v.perceived);
  }
  const weeks = [];
  for (let w = +S.curWeek; w <= +S.lastWeek; w++) weeks.push({ w, wt: w >= +S.playoffStart ? +S.playoffWeight : 1 });
  const wSum = weeks.reduce((a, b) => a + b.wt, 0);

  // Free agents = players on no roster in this league. If the league's rosters look incomplete,
  // players rostered in at least half of leagues are assumed to be taken too.
  const rostered = new Set();
  for (const t of L.teams) for (const id of t.roster) rostered.add(id);
  const complete = L.teams.length >= +S.teams && rostered.size >= +S.teams * 12;
  const pool = DB.players.filter((p) => !rostered.has(p.id) && (complete || (p.own ?? 0) < 50));
  const fa = { a: {} };
  for (const pos of POSITIONS) {
    let best = null;
    for (const p of DB.players) {
      if (p.p !== pos || rostered.has(p.id)) continue;
      const ow = effOut(L, p, +S.curWeek);
      if (ow != null && ow >= +S.curWeek + 1) continue;
      if (!best || ppg.a.get(p.id) > ppg.a.get(best)) best = p.id;
    }
    fa.a[pos] = best;
  }
  // ---- waiver wire: what any team can stream at each position, week by week (our projection)
  const nW = weeks.length, cur = +S.curWeek;
  const depth = Math.max(1, +S.waiverDepth || 2);
  const waiverList = { a: {} }, waiverWho = {};
  for (const pos of POSITIONS) {
    const ps = pool.filter((p) => p.p === pos), lists = [];
    for (let wi = 0; wi < nW; wi++) {
      const w = weeks[wi].w, vals = [];
      for (const p of ps) {
        if ((DB.byes[p.t] || []).includes(w)) continue;
        const o = effOut(L, p, cur);
        if (o != null && w <= o) continue;
        vals.push({ id: p.id, v: wkA.get(p.id)[wi] });
      }
      vals.sort((x, y) => y.v - x.v);
      lists.push(vals.slice(0, 8).map((x) => x.v));
      if (wi === 0) waiverWho[pos] = vals.slice(0, 4).map((x) => x.id);
    }
    waiverList.a[pos] = lists;
  }
  const ctx = { DB, L, S, byId, val, ppg, wkA, weeks, wSum, fa, pool, rostered, waiverList, waiverWho, wvCache: new Map(), cache: new Map(), avail: new Map(), info: new Map(), persp: new Map() };
  ctx.root = ctx;
  ctx.faabAvg = L.teams.length ? L.teams.reduce((a, t) => a + faabOf(ctx, t), 0) / L.teams.length : +S.faabBudget || 100;
  ctx.depth = depth;
  ctx.waiver = { a: {} };
  ctx.waiverAvg = { a: {} };
  for (const pos of POSITIONS) {
    const arr = streamLevels(ctx, "a", pos, depth);
    ctx.waiver.a[pos] = arr;
    ctx.waiverAvg.a[pos] = arr.length ? arr.reduce((x, y) => x + y, 0) / arr.length : 0;
  }
  ctx.style = { ...styleWeights(S, 0.5), base: true };
  applyMarket(ctx);
  return ctx;
}

/* How the flex slots split among positions when counting starters (kickers and defenses fill only their own slot). */
const SLOT_SHARE = { QB: { OP: 0.8 }, RB: { FLEX: 0.4, OP: 0.07, RBWR: 0.5 }, WR: { FLEX: 0.5, OP: 0.1, RBWR: 0.5, WRTE: 0.7 }, TE: { FLEX: 0.1, OP: 0.03, WRTE: 0.3 }, K: {}, DST: {} };
/* Positions priced by a rank ladder in trades: easy to stream, so only the top few are worth much (see marketPrices). */
const LADDER_POS = ["QB", "TE", "K", "DST"];

/*
 * The market layer of a context: free-agent beliefs, replacement levels, the market's streamers,
 * trade values (marketPrices) and the points the other manager's lineup math runs on (ppg.n).
 * The league's context uses the League-tab weights; perspective() builds one per manager style.
 */
function applyMarket(c) {
  const { DB, L, S, val, ppg, pool, rostered, weeks } = c;
  // Every manager in the league passed on its free agents, so the market doesn't believe a free
  // agent's hot start: it judges him by his projection, read on the market's own scale (the market
  // points of whoever holds his projection rank at the position), and never above his own signals.
  // Without this, deep leagues price the streamer above rostered starters (a free-agent TE with a
  // big September "beats" a TE3 the market actually started), and every trade value collapses.
  const faAdj = new Map();
  for (const pos of POSITIONS) {
    const all = DB.players.filter((p) => p.p === pos && val.get(p.id).plays);
    const A = all.map((p) => ppg.a.get(p.id)).sort((x, y) => y - x), Q = all.map((p) => ppg.q.get(p.id)).sort((x, y) => y - x);
    if (A.length < 3) continue;
    const onQ = (x) => {
      let i = 0;
      while (i < A.length && A[i] > x) i++;
      if (i === 0) return Q[0];
      if (i >= A.length) return Q[Q.length - 1];
      const f = (A[i - 1] - x) / Math.max(1e-9, A[i - 1] - A[i]);
      return Q[i - 1] + f * (Q[i] - Q[i - 1]);
    };
    for (const p of pool) {
      if (p.p !== pos) continue;
      const o = (L.overrides || {})[p.id] || {};
      if (o.q != null && o.q !== "") continue;
      const q0 = ppg.q.get(p.id), qm = Math.min(q0, onQ(ppg.a.get(p.id)));
      if (qm < q0 - 0.05) { faAdj.set(p.id, { q0, qm }); ppg.q.set(p.id, qm); }
    }
  }
  c.faAdj = faAdj;
  // replacement level per position, for trade values
  const share = SLOT_SHARE;
  const repl = {};
  for (const pos of POSITIONS) {
    let starters = +S.slots[pos] || 0;
    for (const f of ["FLEX", "OP", "RBWR", "WRTE"]) starters += (+S.slots[f] || 0) * (share[pos][f] || 0);
    const n = Math.max(1, Math.round(+S.teams * starters));
    const vals = DB.players.filter((p) => p.p === pos).map((p) => ppg.q.get(p.id)).sort((a, b) => b - a);
    repl[pos] = vals[Math.min(n, vals.length - 1)] || 0;
  }
  c.repl = repl;
  c.fa = { ...c.fa, q: {} };
  for (const pos of POSITIONS) {
    let best = null;
    for (const p of DB.players) {
      if (p.p !== pos || rostered.has(p.id)) continue;
      const ow = effOut(L, p, +S.curWeek);
      if (ow != null && ow >= +S.curWeek + 1) continue;
      if (!best || ppg.q.get(p.id) > ppg.q.get(best)) best = p.id;
    }
    c.fa.q[pos] = best;
  }
  const nW = weeks.length, cur = +S.curWeek;
  const qLists = (get) => {
    const out = {};
    for (const pos of POSITIONS) {
      const ps = pool.filter((p) => p.p === pos), lists = [];
      for (let wi = 0; wi < nW; wi++) {
        const w = weeks[wi].w, vals = [];
        for (const p of ps) {
          if ((DB.byes[p.t] || []).includes(w)) continue;
          const o = effOut(L, p, cur);
          if (o != null && w <= o) continue;
          vals.push(get(p.id));
        }
        vals.sort((x, y) => y - x);
        lists.push(vals.slice(0, 8));
      }
      out[pos] = lists;
    }
    return out;
  };
  c.waiverList = { ...c.waiverList, q: qLists((id) => ppg.q.get(id)) };
  c.waiver = { ...c.waiver, q: {} };
  c.waiverAvg = { ...c.waiverAvg, q: {} };
  for (const pos of POSITIONS) {
    const arr = streamLevels(c, "q", pos, c.depth);
    c.waiverAvg.q[pos] = arr.length ? arr.reduce((x, y) => x + y, 0) / arr.length : 0;
  }
  // a manager's trade values are measured against what he could stream, at least
  if (S.waiver !== false) for (const pos of POSITIONS) repl[pos] = Math.max(repl[pos], c.waiverAvg.q[pos]);
  // trade-market pricing: what managers think each player is worth in a trade, and the points
  // their lineup math uses (ppg.n), with QB and TE edges priced the way consensus rankings price them
  c.mkt = marketPrices(c);
  // The other manager's lineup math. Quarterbacks run on trade-value points (replacement + trade
  // value): an elite QB's market points overstate what managers believe he adds over a streamer.
  // Other positions run on market points, so a starter's edge over his backup or the waiver
  // wire still counts (pricing them by trade value too erased mid-tier TEs and RBs).
  ppg.n = new Map(DB.players.map((p) => [p.id, p.p === "QB" ? repl[p.p] + c.mkt.mu.get(p.id) : ppg.q.get(p.id)]));
  c.waiverList.q = qLists((id) => ppg.n.get(id));
  for (const pos of POSITIONS) c.waiver.q[pos] = streamLevels(c, "q", pos, c.depth);
  c.wvCache = new Map();
  c.wv = wvFor(c, c.depth);
}

/*
 * A manager's own view of the market. Casual managers (style near 0) go by results so far;
 * dedicated ones (near 1) by expert rankings, projections, news and usage. 0.5 = the League-tab
 * weights, which is the league's shared context itself.
 */
function perspective(ctx, team) {
  const root = ctx.root || ctx;
  const s = styleOf(root, team);
  const { fav, fan } = fanOf(team);
  const fanOn = fav && fan > 0.005;
  if (Math.abs(s - 0.5) < 0.005 && !fanOn) return root;
  const key = s.toFixed(2) + (fanOn ? `|${fav}|${fan.toFixed(2)}` : "");
  let c = root.persp.get(key);
  if (c) return c;
  const st = styleWeights(root.S, s);
  const q = new Map();
  for (const p of root.DB.players) {
    const o = (root.L.overrides || {})[p.id] || {};
    const v = root.val.get(p.id);
    let x = o.q != null && o.q !== "" ? +o.q : Math.abs(s - 0.5) < 0.005 ? v.perceived : perceive(v.sig, Math.max(0, +p.g26 || 0), st.w, st.hotK, false);
    if (x == null) x = v.actual;
    // a fan follows his team closely: he sees its players near their real value, plus a homer bump
    if (fanOn && p.t === fav && !(o.q != null && o.q !== "")) x = ((1 - FAN_KNOW * fan) * x + FAN_KNOW * fan * root.ppg.a.get(p.id)) * (1 + FAN_PREMIUM * fan);
    q.set(p.id, x);
  }
  c = Object.create(root);
  c.style = st;
  c.fan = fanOn ? { fav, fan } : null;
  c.ppg = { a: root.ppg.a, q };
  c.fa = { a: root.fa.a };
  c.waiverList = { a: root.waiverList.a };
  c.waiver = { a: root.waiver.a };
  c.waiverAvg = { a: root.waiverAvg.a };
  c.cache = new Map();
  c.info = new Map();
  applyMarket(c);
  root.persp.set(key, c);
  return c;
}

/* How badly a manager wants to shake things up, from his record: +1 winless, −1 unbeaten, 0 at .500.
   Early records count less (a 0-1 start isn't a 0-4 start). */
function teamMood(team) {
  if (!team) return 0;
  const w = Math.max(0, +team.wins || 0), l = Math.max(0, +team.losses || 0), t = Math.max(0, +team.ties || 0);
  const g = w + l + t;
  if (!g) return 0;
  const pct = (w + 0.5 * t) / g;
  return (0.5 - pct) * 2 * Math.min(1, g / 4);
}

/*
 * Trade-market prices. Managers don't trade on raw points: consensus rankings put the QB1 around
 * 25th overall in a one-QB league (worth one good RB2 or WR2) and most TEs barely above a streamer,
 * because those positions are easy to stream. So:
 *  1. Calibrate in a reference league (12 teams, one QB, PPR, the format of the FantasyPros overall
 *     rankings): read each RB/WR's market margin (perceived points over replacement) off his overall
 *     consensus rank, giving a points-by-overall-rank curve V; the QB and TE price per point of margin,
 *     k, is what that curve pays the top QBs/TEs divided by their perceived margins.
 *  2. In this league, a player's trade price per week is
 *       mu = (1 − c) · k[pos] · (perceived − replacement) + c · u[pos] · V(overall consensus rank)
 *     c = settings.consensus, u = this league's margins relative to the reference league (scoring,
 *     TE premium, roster size). Superflex/2QB leagues price QBs at full points instead.
 */
function marketPrices(ctx) {
  const { DB, L, S, ppg, repl } = ctx;
  const D = DEFAULT_SETTINGS;
  const refL = { ...L, settings: { ...S, teams: 12, scoring: { ...D.scoring, byPos: {} }, slots: { ...D.slots } } };
  const sameFormat = +S.teams === 12 && Object.keys(D.slots).every((k) => (+S.slots[k] || 0) === D.slots[k])
    && SCORE_KEYS.every((k) => +S.scoring[k] === +D.scoring[k]) && !Object.keys(S.scoring.byPos || {}).length;
  const root = ctx.root || ctx;
  if (!root._vRef) root._vRef = sameFormat ? root.val : valuations(DB, refL);
  const vRef = root._vRef;
  const st = ctx.style;
  const qR = new Map(DB.players.map((p) => {
    const v = vRef.get(p.id);
    const x = !st || st.base ? v.perceived : perceive(v.sig, Math.max(0, +p.g26 || 0), st.w, st.hotK, false);
    return [p.id, x != null ? x : v.actual];
  }));
  const plays = (p) => ctx.val.get(p.id).plays;
  // reference replacement: the starter line in a 12-team one-QB league
  const share = SLOT_SHARE;
  const N = {}, replR = {};
  for (const pos of POSITIONS) {
    let st = +D.slots[pos] || 0;
    for (const f of ["FLEX", "OP", "RBWR", "WRTE"]) st += (+D.slots[f] || 0) * (share[pos][f] || 0);
    N[pos] = Math.max(1, Math.round(12 * st));
    const vals = DB.players.filter((p) => p.p === pos).map((p) => qR.get(p.id)).sort((a, b) => b - a);
    replR[pos] = vals[Math.min(N[pos], vals.length - 1)] || 0;
  }
  // overall consensus rank; players outside the overall list get one from their position rank
  // (data built before the overall rankings were added falls back to preseason overall ranks)
  const ok = DB.players.some((p) => p.eo != null) ? "eo" : "dr";
  const eo = new Map();
  for (const pos of POSITIONS) {
    const ps = DB.players.filter((p) => p.p === pos);
    const tab = ps.filter((p) => p[ok] != null).map((p) => +p[ok]).sort((a, b) => a - b);
    const nEr = ps.filter((p) => p.er != null).length;
    const rest = ps.filter((p) => p.er == null).sort((a, b) => ppg.q.get(b.id) - ppg.q.get(a.id));
    const restRank = new Map(rest.map((p, i) => [p.id, nEr + 1 + i]));
    const slope = tab.length >= 6 ? (tab[tab.length - 1] - tab[tab.length - 6]) / 5 : 12;
    const at = (r) => {
      if (!tab.length) return 150 + 12 * r;
      if (r <= 1) return tab[0];
      if (r <= tab.length) { const i = Math.floor(r), f = r - i; return tab[i - 1] + f * (tab[Math.min(i, tab.length - 1)] - tab[i - 1]); }
      return tab[tab.length - 1] + (r - tab.length) * slope;
    };
    for (const p of ps) eo.set(p.id, p[ok] != null ? +p[ok] : at(p.er != null ? +p.er : restRank.get(p.id)));
  }
  // V: RB/WR perceived margin by overall rank (quantile match), reference league
  const rw = DB.players.filter((p) => (p.p === "RB" || p.p === "WR") && plays(p));
  const X = rw.map((p) => eo.get(p.id)).sort((a, b) => a - b);
  const Y = rw.map((p) => Math.max(0, qR.get(p.id) - replR[p.p])).sort((a, b) => b - a);
  const V = (x) => {
    if (!X.length) return 0;
    if (x <= X[0]) return Y[0];
    let lo = 0, hi = X.length - 1;
    if (x >= X[hi]) return Y[hi];
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (X[m] <= x) lo = m; else hi = m; }
    const f = (x - X[lo]) / Math.max(1e-9, X[hi] - X[lo]);
    return Y[lo] + f * (Y[hi] - Y[lo]);
  };
  // u: this league's margins relative to the reference league, per position (scoring, TE premium, size)
  const u = {}, ladder = {};
  for (const pos of POSITIONS) {
    const ps = DB.players.filter((p) => p.p === pos && plays(p));
    const top = (m) => ps.slice().sort((a, b) => m.get(b.id) - m.get(a.id)).slice(0, N[pos]);
    const marR = top(qR).reduce((s, p) => s + Math.max(0, qR.get(p.id) - replR[pos]), 0);
    const marL = top(ppg.q).reduce((s, p) => s + Math.max(0, ppg.q.get(p.id) - repl[pos]), 0);
    u[pos] = marR > 1e-6 && marL > 1e-6 ? Math.max(0.25, Math.min(4, marL / marR)) : 1;
    // QB/TE/K/DST price ladder: what the consensus pays for the 1st, 2nd, ... best player at the position
    // (the overall rankings list only the top few kickers and defenses, far down: most are worth nothing)
    if (LADDER_POS.includes(pos)) ladder[pos] = ps.map((p) => V(eo.get(p.id))).sort((a, b) => b - a);
  }
  // QB/TE/K/DST: the market signals decide where he ranks at his position; the ladder decides what that
  // rank is worth. Near-ties share a price (managers can't tell QB4 from QB8 when they score alike).
  const rankPrice = {};
  for (const pos of LADDER_POS) {
    const qs = DB.players.filter((p) => p.p === pos && plays(p)).map((p) => ppg.q.get(p.id)).sort((a, b) => b - a);
    const L2 = ladder[pos], H = 1.0;
    rankPrice[pos] = (q) => {
      let num = 0, den = 0;
      for (let j = 0; j < qs.length && j < L2.length; j++) {
        const d = (q - qs[j]) / H;
        if (d > 4) break;
        if (d < -4) continue;
        const w = Math.exp(-d * d);
        num += w * L2[j]; den += w;
      }
      if (den > 1e-9) return num / den;
      return q >= qs[0] ? L2[0] || 0 : 0;
    };
  }
  // superflex / two-QB leagues: QBs are scarce, so their points count in full
  const qbDemand = (+S.slots.QB || 0) + 0.8 * (+S.slots.OP || 0);
  const b = Math.max(0, Math.min(1, (qbDemand - 1) / 0.8));
  const c = Math.max(0, Math.min(1, S.consensus == null ? 0.5 : +S.consensus));
  // proven-player premium: managers pay extra for certainty. Scales with how long his record is and
  // how much of his current value it backs up; casual managers (name value) pay more, dedicated less.
  const sty = ctx.style && ctx.style.s != null ? ctx.style.s : 0.5;
  const TP = Math.max(0, S.proven == null ? DEFAULT_SETTINGS.proven : +S.proven) * (1.5 - sty);
  const mu = new Map(), parts = new Map();
  for (const p of DB.players) {
    const o = (L.overrides || {})[p.id] || {};
    const cw = o.q != null && o.q !== "" ? 0 : c; // your own market number stands in for the consensus
    const q = ppg.q.get(p.id), m = q - repl[p.p];
    const con = u[p.p] * V(eo.get(p.id));
    // above replacement: RB/WR edges count as perceived points; QB/TE edges at the price the
    // consensus pays for that rank. Below replacement (streamers, fringe players) the shortfall
    // counts in full, so a free agent never looks closer to a starter than the market thinks.
    const sig = m <= 0 ? m : rankPrice[p.p] ? u[p.p] * rankPrice[p.p](q) : m;
    let v = m > 0 ? (1 - cw) * sig + cw * con : m + cw * con;
    if (p.p === "QB") v = (1 - b) * v + b * m;
    let prem = 0, proven = 0;
    const tr = ctx.val.get(p.id).sig.track;
    // not for one-QB-league quarterbacks, kickers or defenses: certainty is cheap at a position you can stream
    const pf = p.p === "QB" ? b : KD_POS.includes(p.p) ? 0 : 1;
    if (TP > 0 && pf > 0 && v > 0 && tr && !(o.q != null && o.q !== "")) {
      proven = Math.max(0, Math.min(1, (tr.v - repl[p.p]) / Math.max(0.5, m)));
      prem = TP * pf * tr.full * proven * v;
      v += prem;
    }
    mu.set(p.id, v);
    parts.set(p.id, { sig, con, eo: eo.get(p.id), listed: p[ok] != null, prem, proven: proven * (tr ? tr.full : 0) });
  }
  return { mu, parts, u, b, c, V, eo, ladder };
}

/* Streaming level for each remaining week at a (possibly fractional) waiver depth:
   depth 1 = the best available free agent, 2 = the second best, 1.5 = halfway between. */
function streamLevels(ctx, view, pos, d) {
  const lists = ctx.waiverList[view][pos], out = new Float64Array(lists.length);
  for (let wi = 0; wi < lists.length; wi++) {
    const l = lists[wi];
    if (!l.length) continue;
    const i = Math.floor(d), f = d - i;
    const a = l[Math.min(i, l.length) - 1], b = l[Math.min(i + 1, l.length) - 1];
    out[wi] = Math.round((a + f * (b - a)) * 100) / 100;
  }
  return out;
}

/* Virtual streamer entries added to a lineup for a given waiver depth (one per position; two QBs with superflex). */
function wvFor(ctx, d) {
  if (ctx.S.waiver === false) return [];
  const key = d.toFixed(3);
  let wv = ctx.wvCache.get(key);
  if (wv) return wv;
  wv = [];
  const nW = ctx.weeks.length;
  for (const pos of POSITIONS) {
    const count = pos === "QB" && +ctx.S.slots.OP > 0 ? 2 : 1;
    const pts = {}, codes = {};
    for (const view of ["a", "q"]) {
      pts[view] = streamLevels(ctx, view, pos, d);
      const vals = [], c = new Int32Array(nW);
      for (let wi = 0; wi < nW; wi++) {
        let k = vals.indexOf(pts[view][wi]);
        if (k < 0) { k = vals.length; vals.push(pts[view][wi]); }
        c[wi] = k;
      }
      codes[view] = c;
    }
    for (let i = 0; i < count; i++) wv.push({ pc: POS_CODE[pos], pos, streamer: true, pts, code: codes });
  }
  ctx.wvCache.set(key, wv);
  return wv;
}

/* A team's remaining free agent budget (defaults to the full budget). */
function faabOf(ctx, team) {
  const b = +ctx.S.faabBudget || 100;
  const v = team ? team.faab : null;
  return v == null || v === "" ? b : Math.max(0, +v);
}

/* Waiver depth a team can expect from its budget: an average budget gets the league's usual
   depth; twice the average gets the best free agent; an empty budget gets one pick deeper. */
function depthFor(ctx, dollars) {
  const D = ctx.depth;
  if (!ctx.S.faab || ctx.S.waiver === false || !(ctx.faabAvg > 0)) return D;
  const r = dollars / ctx.faabAvg;
  return Math.min(D + 1, Math.max(1, D + 1 - r));
}
function teamDepth(ctx, team) { return depthFor(ctx, faabOf(ctx, team)); }

/* Points (rest of season) one FAAB dollar buys in future waiver breakouts: the pool of points
   that past seasons' breakouts scored above a startable level from this week on, divided by all
   the budget left in the league. */
function faabPerDollar(ctx) {
  const P = ctx.DB.faabPool;
  if (!P || !ctx.S.faab) return 0;
  const w = String(Math.max(1, Math.min(18, +ctx.S.curWeek)));
  const std = +(P.std[w] ?? 0), ppr = +(P.ppr[w] ?? 0);
  const rec = Math.max(0, Math.min(1, +ctx.S.scoring.rec || 0));
  const pool = std + rec * (ppr - std);
  const total = ctx.faabAvg * Math.max(1, +ctx.S.teams);
  return total > 0 ? pool / total : 0;
}

/* What a change in a team's budget is worth to it, in rest-of-season points:
   better weekly pickups (streaming depth) plus a share of future breakouts. */
function faabValue(ctx, team, delta) {
  if (!ctx.S.faab || !delta) return { stream: 0, breakout: 0, total: 0 };
  const f0 = faabOf(ctx, team), f1 = Math.max(0, f0 + delta);
  const stream = teamValue(ctx, team.roster, "a", true, depthFor(ctx, f1)) - teamValue(ctx, team.roster, "a", true, depthFor(ctx, f0));
  const breakout = (f1 - f0) * faabPerDollar(ctx);
  return { stream, breakout, total: stream + breakout };
}


function availString(ctx, id) {
  let a = ctx.avail.get(id);
  if (a !== undefined) return a;
  a = "";
  for (const { w } of ctx.weeks) a += available(ctx, id, w) ? "1" : "0";
  ctx.avail.set(id, a);
  return a;
}

function available(ctx, id, w) {
  const p = ctx.byId.get(id);
  if (!p) return false;
  const byes = ctx.DB.byes[p.t] || [];
  if (byes.includes(w)) return false;
  const o = effOut(ctx.L, p, +ctx.S.curWeek);
  if (o != null && w <= o) return false;
  return true;
}

const AVAIL_Q = 0.93; // chance a healthy starter actually plays in a given week
const _st = new Int32Array(64);
const _used = new Uint8Array(64);

/*
 * Best legal lineup from players sorted by points (desc), as parallel arrays; optionally ignoring
 * one player. Fills dedicated slots first, then the narrow flex slots (RB/WR, WR/TE), then
 * FLEX (RB/WR/TE), then superflex. Position codes: 0 QB, 1 RB, 2 WR, 3 TE, 4 K, 5 D/ST (kickers and
 * defenses only ever fill their own slot). Fills _st.
 */
function lineupFast(pos, pts, n, skip, slots) {
  let q = +slots.QB || 0, r = +slots.RB || 0, wr = +slots.WR || 0, te = +slots.TE || 0, kk = +slots.K || 0, dd = +slots.DST || 0;
  let rbwr = +slots.RBWR || 0, wrte = +slots.WRTE || 0, flex = +slots.FLEX || 0, op = +slots.OP || 0;
  let total = 0, k = 0;
  const used = _used;
  used.fill(0, 0, n);
  const take = (i) => { used[i] = 1; total += pts[i] > 0 ? pts[i] : 0; _st[k++] = i; };
  for (let i = 0; i < n; i++) {
    if (i === skip) continue;
    const p = pos[i];
    if (p === 0 && q > 0) q--; else if (p === 1 && r > 0) r--; else if (p === 2 && wr > 0) wr--; else if (p === 3 && te > 0) te--;
    else if (p === 4 && kk > 0) kk--; else if (p === 5 && dd > 0) dd--; else continue;
    take(i);
  }
  if (rbwr > 0 || wrte > 0) {
    for (let i = 0; i < n && (rbwr > 0 || wrte > 0); i++) {
      if (i === skip || used[i]) continue;
      const p = pos[i];
      if (p === 1 && rbwr > 0) { rbwr--; take(i); }
      else if (p === 3 && wrte > 0) { wrte--; take(i); }
      else if (p === 2) { if (wrte > 0) { wrte--; take(i); } else if (rbwr > 0) { rbwr--; take(i); } }
    }
  }
  for (let i = 0; i < n && flex > 0; i++) {
    if (i === skip || used[i] || pos[i] === 0 || pos[i] > 3) continue;
    flex--; take(i);
  }
  for (let i = 0; i < n && op > 0; i++) {
    if (i === skip || used[i] || pos[i] > 3) continue;
    op--; take(i);
  }
  return [total, k];
}

/* Expected lineup points for one week's available players, with the injury cushion. */
function weekEV(pos, pts, n, slots, cushion) {
  const [base, k] = lineupFast(pos, pts, n, -1, slots);
  if (!cushion) return base;
  const starters = [];
  for (let i = 0; i < k; i++) starters.push(_st[i]);
  let loss = 0;
  for (const s of starters) loss += base - lineupFast(pos, pts, n, s, slots)[0];
  return base - (1 - AVAIL_Q) * loss;
}

const POS_CODE = { QB: 0, RB: 1, WR: 2, TE: 3, K: 4, DST: 5 };

/* Per-player numbers the engine needs, computed once per context: points in each remaining week
   (0 when he can't play) and a code per week that changes only when his points or availability do. */
function info(ctx, id) {
  let x = ctx.info.get(id);
  if (x !== undefined) return x;
  const p = ctx.byId.get(id);
  if (!p) { ctx.info.set(id, null); return null; }
  const av = availString(ctx, id), nW = ctx.weeks.length;
  // the perceived view uses trade-market points (ppg.n): what a manager's lineup math runs on
  const wa = ctx.wkA.get(id), q = ctx.ppg.n ? ctx.ppg.n.get(id) : ctx.ppg.q.get(id);
  const pa = new Float64Array(nW), ca = new Int32Array(nW), pq = new Float64Array(nW), cq = new Int32Array(nW);
  const vals = [];
  let mask = 0;
  for (let i = 0; i < nW; i++) {
    if (av[i] === "1") {
      mask |= 1 << i;
      const v = wa ? wa[i] : 0;
      let k = vals.findIndex((y) => Math.abs(y - v) < 1e-9);
      if (k < 0) { k = vals.length; vals.push(v); }
      pa[i] = v; ca[i] = k; pq[i] = q; cq[i] = 0;
    } else { ca[i] = -1; cq[i] = -1; }
  }
  x = { pc: POS_CODE[p.p], a: ctx.ppg.a.get(id), q, mask, pts: { a: pa, q: pq }, code: { a: ca, q: cq } };
  ctx.info.set(id, x);
  return x;
}

const _pos = new Int8Array(64), _pts = new Float64Array(64), _ord = new Int32Array(64);

/* Rest-of-season value of a roster: sum over weeks of expected starting-lineup points.
   Weeks with the same availability and the same per-player points are evaluated once. */
function teamValue(ctx, roster, view, useCache = true, depth = null) {
  const d = depth == null ? ctx.depth : depth;
  let key;
  if (useCache) {
    key = view + "|" + d.toFixed(3) + "|" + roster.slice().sort().join(",");
    const hit = ctx.cache.get(key);
    if (hit !== undefined) return hit;
  }
  const list = [];
  for (const id of roster) { const x = info(ctx, id); if (x) list.push(x); }
  if (list.length > 56) list.length = 56;
  for (const x of wvFor(ctx, d)) list.push(x);
  const n = list.length, nW = ctx.weeks.length;
  const gKey = new Map(), gWt = [], gWi = [];
  for (let wi = 0; wi < nW; wi++) {
    let h1 = 0x811c9dc5 | 0, h2 = 0;
    for (let i = 0; i < n; i++) {
      const c = list[i].code[view][wi] + 2;
      h1 = Math.imul(h1 ^ c, 16777619);
      h2 = (Math.imul(h2, 31) + c) | 0;
    }
    const k = (h1 >>> 0) * 2097152 + ((h2 >>> 0) & 0x1fffff);
    const g = gKey.get(k);
    if (g === undefined) { gKey.set(k, gWt.length); gWt.push(ctx.weeks[wi].wt); gWi.push(wi); }
    else gWt[g] += ctx.weeks[wi].wt;
  }
  let total = 0;
  for (let g = 0; g < gWt.length; g++) {
    const wi = gWi[g];
    let k = 0;
    for (let i = 0; i < n; i++) {
      if (list[i].code[view][wi] < 0) continue;
      // insertion sort by points, descending
      const v = list[i].pts[view][wi];
      let j = k++;
      while (j > 0 && _pts[j - 1] < v) { _pts[j] = _pts[j - 1]; _pos[j] = _pos[j - 1]; j--; }
      _pts[j] = v; _pos[j] = list[i].pc;
    }
    total += gWt[g] * weekEV(_pos, _pts, k, ctx.S.slots, ctx.S.cushion);
  }
  if (useCache) {
    if (ctx.cache.size > 20000) ctx.cache.clear();
    ctx.cache.set(key, total);
  }
  return total;
}

/* Starters for a given week (for display). */
function lineupForWeek(ctx, roster, view, w, depth = null) {
  const wi = ctx.weeks.findIndex((x) => x.w === w);
  const pts = (id) => (view === "a" ? (wi >= 0 ? ctx.wkA.get(id)[wi] : ctx.ppg.a.get(id)) : (ctx.ppg.n || ctx.ppg.q).get(id));
  const entries = roster.filter((id) => ctx.byId.has(id) && available(ctx, id, w)).map((id) => ({ id, pc: POS_CODE[ctx.byId.get(id).p], v: pts(id) }));
  if (wi >= 0) for (const x of wvFor(ctx, depth == null ? ctx.depth : depth)) entries.push({ id: null, pos: x.pos, pc: x.pc, v: x.pts[view][wi] });
  entries.sort((a, b) => b.v - a.v);
  if (entries.length > 60) entries.length = 60;
  const pos = new Int8Array(entries.length), pv = new Float64Array(entries.length);
  entries.forEach((e, i) => { pos[i] = e.pc; pv[i] = e.v; });
  const [total, k] = lineupFast(pos, pv, entries.length, -1, ctx.S.slots);
  const ids = [], streamers = [];
  for (let i = 0; i < k; i++) { const e = entries[_st[i]]; if (e.id) ids.push(e.id); else streamers.push(e.pos); }
  return { total, ids, streamers };
}

/* Points per game over the waiver-wire streamer at his position, averaged over the weeks he plays. */
function overWaiver(ctx, id) {
  const p = ctx.byId.get(id), v = ctx.val.get(id);
  if (!p || !v) return null;
  const wk = ctx.wkA.get(id), wv = ctx.waiver.a[p.p];
  let s = 0, n = 0;
  for (let i = 0; i < wk.length; i++) if (v.avail[i]) { s += wk[i] - wv[i]; n++; }
  return n ? s / n : null;
}

/* Fill an open roster spot with the best free agent for this team. */
function withFreeAgent(ctx, roster, view, positions, d = null) {
  let best = roster, bestV = teamValue(ctx, roster, view, false, d);
  for (const pos of positions || POSITIONS) {
    const id = ctx.fa[view][pos];
    if (!id) continue;
    const r = roster.concat([id]);
    const v = teamValue(ctx, r, view, false, d);
    if (v > bestV) { bestV = v; best = r; }
  }
  return { roster: best, v: bestV };
}

function rosterValueAfter(ctx, roster, view, size, gaveAway, d = null) {
  let r = roster;
  let v;
  let added = null;
  if (r.length < size) {
    const positions = [...new Set((gaveAway || []).map((id) => ctx.byId.get(id).p))];
    const f = withFreeAgent(ctx, r, view, positions, d);
    if (f.roster.length > r.length) added = f.roster[f.roster.length - 1];
    r = f.roster; v = f.v;
  } else v = teamValue(ctx, r, view, false, d);
  return { v, added };
}

/* "Name value" a manager sees: his trade-market price per week (see marketPrices) over the
   weeks he can play, rest of season. */
function vorpQ(ctx, id) {
  const p = ctx.byId.get(id);
  if (!p) return 0;
  const o = effOut(ctx.L, p, +ctx.S.curWeek);
  let wt = 0;
  for (const { w, wt: x } of ctx.weeks) if (!(o != null && w <= o)) wt += x;
  const per = ctx.mkt ? ctx.mkt.mu.get(id) : ctx.ppg.q.get(id) - ctx.repl[p.p];
  return Math.max(0, per) * wt;
}
/* Trade-market price per week, for display. */
function marketPrice(ctx, id) { return ctx.mkt ? ctx.mkt.mu.get(id) : 0; }

function sigmoid(x) { return 1 / (1 + Math.exp(-x)); }
const LOSS_AVERSION = 2;

/*
 * Evaluate a trade. `give` leaves team A for team B; `get` leaves B for A.
 * Actual: change in each side's rest-of-season lineup points using regressed projections.
 * Perceived (B only): what B believes, mixing lineup need and trade value (marketPrices).
 */
function evalTrade(ctx, teamA, teamB, give, get, money) {
  ctx = ctx.root || ctx;
  const S = ctx.S;
  // the other manager judges the deal through his own eyes (casual or dedicated) and his record
  const cB = perspective(ctx, teamB);
  const mood = teamMood(teamB), M = S.standings == null ? 0.5 : +S.standings;
  const mg = Math.max(0, +(money && money.give) || 0), mr = Math.max(0, +(money && money.get) || 0);
  const fa0 = faabOf(ctx, teamA), fb0 = faabOf(ctx, teamB);
  const dA0 = depthFor(ctx, fa0), dB0 = depthFor(ctx, fb0);
  const dA1 = depthFor(ctx, fa0 - mg + mr), dB1 = depthFor(ctx, fb0 + mg - mr);
  const a0 = teamA.roster, b0 = teamB.roster;
  const a1 = a0.filter((id) => !give.includes(id)).concat(get);
  const b1 = b0.filter((id) => !get.includes(id)).concat(give);
  const vA0 = teamValue(ctx, a0, "a", true, dA0), vB0 = teamValue(ctx, b0, "a", true, dB0), qB0 = teamValue(cB, b0, "q", true, dB0);
  const A = rosterValueAfter(ctx, a1, "a", a0.length, give, dA1);
  const B = rosterValueAfter(ctx, b1, "a", b0.length, get, dB1);
  const Bq = rosterValueAfter(cB, b1, "q", b0.length, get, dB1);
  const pd = faabPerDollar(ctx);
  const dA = A.v - vA0 + (mr - mg) * pd;
  const dB = B.v - vB0 + (mg - mr) * pd;
  const needQ = Bq.v - qB0 + (mg - mr) * pd;
  const rawQ = give.reduce((s, id) => s + vorpQ(cB, id), 0) - (+S.attachment || 1) * get.reduce((s, id) => s + vorpQ(cB, id), 0)
    + mg * pd - (+S.attachment || 1) * mr * pd;
  // a losing manager thinks more about this week's lineup and needs less of an edge to deal;
  // a winning one is happy with his team and needs more
  const w = Math.max(0, Math.min(1, +S.needWeight + 0.1 * mood * (M > 0 ? 1 : 0)));
  const edge = +S.stubborn - M * mood;
  const perceived = w * needQ + (1 - w) * rawQ;
  // acceptance works in points per week, the unit managers actually think in
  const perWeek = perceived / Math.max(1, ctx.wSum);
  // loss aversion: a trade they see as a loss counts double against it (people weigh losses about
  // twice as heavily as equal gains), so deals they think they lose are rarely accepted
  const felt = perWeek < 0 ? LOSS_AVERSION * perWeek : perWeek;
  const accept = sigmoid((felt - edge) / Math.max(0.1, +S.spread));
  return { dA, dB, needQ, rawQ, perceived, accept, faA: A.added, faB: B.added, wSum: ctx.wSum, money: { give: mg, get: mr },
    edge, mood, style: styleOf(ctx, teamB), needW: w };
}

/* Value of a player to every team: what they'd gain by adding him, or lose by losing him. */
function contextValues(ctx, id) {
  return ctx.L.teams.map((t) => {
    const has = t.roster.includes(id);
    const d = teamDepth(ctx, t);
    const base = teamValue(ctx, t.roster, "a", true, d);
    const other = has ? t.roster.filter((x) => x !== id) : t.roster.concat([id]);
    const v = teamValue(ctx, other, "a", true, d);
    return { team: t, has, delta: has ? base - v : v - base };
  });
}

/* Search trades between my team and the others. Generator so the UI can yield between chunks. */
function* findTrades(ctx, mine, opts) {
  const { shapes = ["1-1", "2-1", "1-2"], minAccept = 0.25, partnerId = "", partnerIds = null, minPts = 6 } = opts || {};
  ctx = ctx.root || ctx;
  const only = partnerIds && partnerIds.length ? new Set(partnerIds) : partnerId ? new Set([partnerId]) : null;
  const results = [], near = [];
  const useFaab = !!ctx.S.faab && !!ctx.DB.faabPool;
  // kickers and defenses stay out of the search (a kicker-for-kicker swap is rarely worth a message); the Trade
  // tab values them like anyone else
  const keep = (id) => !KD_POS.includes((ctx.byId.get(id) || {}).p) && (ctx.ppg.a.get(id) >= minPts || ctx.ppg.q.get(id) >= minPts);
  const myC = mine.roster.filter(keep);
  const partners = ctx.L.teams.filter((t) => t.id !== mine.id && (!only || only.has(t.id)));
  const pairs = (arr) => { const o = []; for (let i = 0; i < arr.length; i++) for (let j = i + 1; j < arr.length; j++) o.push([arr[i], arr[j]]); return o; };
  let n = 0, pi = 0;
  for (const t of partners) {
    pi++;
    const thC = t.roster.filter(keep);
    const combos = [];
    if (shapes.includes("1-1")) for (const g of myC) for (const r of thC) combos.push([[g], [r]]);
    if (shapes.includes("2-1")) for (const g of pairs(myC)) for (const r of thC) combos.push([g, [r]]);
    if (shapes.includes("1-2")) for (const g of myC) for (const r of pairs(thC)) combos.push([[g], r]);
    if (shapes.includes("2-2")) for (const g of pairs(myC)) for (const r of pairs(thC)) combos.push([g, r]);
    for (const [give, get] of combos) {
      const e = evalTrade(ctx, mine, t, give, get);
      if (e.dA > 1 && e.accept >= minAccept) results.push({ partner: t.id, give, get, ...e, score: e.accept * e.dA });
      else if (useFaab && e.dA > 1.5 && e.accept >= 0.02) near.push({ t, give, get, dA: e.dA, accept: e.accept });
      if (++n % 250 === 0) yield { n, partner: t.name, pi, of: partners.length };
    }
  }
  // FAAB: sweeten near misses with your budget, and ask for theirs where they'd still say yes
  if (useFaab) {
    const target = Math.max(minAccept, 0.5);
    const step = Math.max(1, Math.round((+ctx.S.faabBudget || 100) / 20));
    const myF = faabOf(ctx, mine);
    near.sort((x, y) => y.dA * (y.accept + 0.1) - x.dA * (x.accept + 0.1));
    let k = 0;
    for (const c of near.slice(0, 60)) {
      for (let x = step; x <= Math.floor(myF * 0.6); x += step) {
        const e = evalTrade(ctx, mine, c.t, c.give, c.get, { give: x });
        if (e.dA <= 1) break;
        if (e.accept >= target) { results.push({ partner: c.t.id, give: c.give, get: c.get, ...e, score: e.accept * e.dA, sweet: true }); break; }
      }
      if (++k % 10 === 0) yield { n, partner: "FAAB sweeteners", pi: partners.length, of: partners.length };
    }
    results.sort((x, y) => y.score - x.score);
    // deals they'd accept easily: how much of their FAAB you could also ask for (up to half of it)
    for (const r of results.slice(0, 40)) {
      if (r.money.give || r.accept < 0.75) continue;
      const t = ctx.L.teams.find((x) => x.id === r.partner), theirF = faabOf(ctx, t);
      let best = null, amt = 0;
      for (let y = step; y <= Math.floor(theirF * 0.5); y += step) {
        const e = evalTrade(ctx, mine, t, r.give, r.get, { get: y });
        if (e.accept < Math.max(minAccept, 0.6)) break;
        best = e; amt = y;
      }
      if (best) r.askFor = { amount: amt, accept: best.accept, dA: best.dA };
    }
  }
  results.sort((x, y) => y.score - x.score);
  // keep the result list varied: any one player appears in at most 3 suggested deals
  const seen = new Map();
  const out = [];
  const dealSeen = new Set();
  for (const r of results) {
    const ids = r.get.concat(r.give);
    const dk = r.give.slice().sort().join("+") + ">" + r.get.slice().sort().join("+");
    if (dealSeen.has(dk)) continue;
    dealSeen.add(dk);
    if (ids.some((id) => (seen.get(id) || 0) >= 3)) continue;
    for (const id of ids) seen.set(id, (seen.get(id) || 0) + 1);
    out.push(r);
    if (out.length >= 40) break;
  }
  return out;
}

/* Default "out through week" from the injury timeline built into the data
   (CBS expected return, NFL IR 4-game rule, news on season-ending injuries). */
function defaultOut(DB, p, curWeek) {
  if (!p || !p.ij || p.ij.thru == null) return null;
  return p.ij.thru >= curWeek ? p.ij.thru : null;
}

/* First week whose games are on or after a date (a return date maps to the week he can play). */
function weekOfDate(DB, date) {
  const wd = DB.weekDates || {};
  const t = new Date(date).getTime();
  if (!isFinite(t)) return null;
  const weeks = Object.keys(wd).map(Number).sort((a, b) => a - b);
  for (const w of weeks) if (new Date(wd[w] + "T12:00:00").getTime() + 4 * 864e5 >= t) return w;
  return 19;
}

/* Sample league: a simple snake draft by perceived value with position caps. */
function sampleLeague(DB, seed) {
  const L = newLeague(DB);
  L.name = "Sample league (simulated draft)";
  L.example = true;
  L.settings.faab = true;
  let s = seed || 7;
  const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const ctx = buildCtx(DB, L);
  const n = L.settings.teams;
  // one kicker and one defense per team, late, when the data has them (15 rounds of everyone else)
  const kd = KD_POS.filter((pos) => DB.players.some((p) => p.p === pos));
  const caps = { QB: 2, RB: 6, WR: 6, TE: 2, K: 1, DST: 1 };
  const need = { QB: 1, RB: 2, WR: 2, TE: 1 };
  for (const pos of kd) need[pos] = 1;
  L.teams = Array.from({ length: n }, (_, i) => ({ id: "t" + (i + 1), name: i === 0 ? "My team" : "Team " + (i + 1), mine: i === 0, roster: [] }));
  const pool = DB.players.map((p) => ({ id: p.id, pos: p.p, v: (p.dr ? 40 - p.dr / 6 : 0) * 0.3 + (ctx.ppg.q.get(p.id) - ctx.repl[p.p]) }));
  const taken = new Set();
  const rounds = 15 + kd.length;
  for (let r = 0; r < rounds; r++) {
    const order = r % 2 === 0 ? L.teams : L.teams.slice().reverse();
    for (const t of order) {
      const cnt = { QB: 0, RB: 0, WR: 0, TE: 0, K: 0, DST: 0 };
      for (const id of t.roster) cnt[ctx.byId.get(id).p]++;
      const roundsLeft = rounds - r;
      const missing = Object.keys(need).filter((k) => cnt[k] < need[k]);
      let cands = pool.filter((p) => !taken.has(p.id) && cnt[p.pos] < caps[p.pos]);
      if (missing.length >= roundsLeft) cands = cands.filter((p) => missing.includes(p.pos));
      // QBs and TEs go later in real drafts, kickers and defenses last; nudge them down, add a little noise
      const adj = (p) => (KD_POS.includes(p.pos) ? -50 : 0) + p.v * (p.pos === "QB" ? 0.55 : p.pos === "TE" ? 0.8 : 1) + (rnd() - 0.5) * 2.5;
      cands.sort((x, y) => adj(y) - adj(x));
      const pick = cands[0];
      taken.add(pick.id);
      t.roster.push(pick.id);
    }
  }
  const played = Math.max(0, +L.settings.curWeek - 1);
  for (const t of L.teams) {
    t.faab = Math.max(0, 100 - Math.round(rnd() * 70));
    t.wins = 0; t.losses = 0; t.ties = 0;
    for (let g = 0; g < played; g++) (rnd() < 0.5 ? t.wins++ : t.losses++);
    if (!t.mine) t.style = Math.round((0.2 + rnd() * 0.6) * 10) / 10;
    if (!t.mine && rnd() < 0.5) { const tms = Object.keys(DB.teams || {}); t.fav = tms[Math.floor(rnd() * tms.length)]; t.fan = Math.round((0.3 + rnd() * 0.6) * 10) / 10; }
  }
  return L;
}

/* ---------------- Weekly points distributions: start/sit, floor and ceiling ---------------- */
/*
 * Every player's points this week as a distribution instead of one number. Each game is simulated a few
 * thousand times from the same expected stat line as his projection: a pace shock both teams share and a
 * script shock that splits them; each team's pass volume, rush volume and efficiency; each player's role
 * (shares are re-split inside the team, so one back's big day is his teammate's small one), a small chance
 * he leaves early, his efficiency; then carries and targets (Poisson), catches (binomial), yards (sums of
 * plays) and touchdowns (Poisson). A quarterback's passing line is his pass catchers' receiving line, so a
 * QB and his receivers rise and fall together. Players listed Questionable play with the chance past
 * Questionable players with the same practice report played. dist/sim.py is the reference implementation
 * and params/dist.json the fitted numbers (2024-26 backtest weeks).
 */
// The fitted distribution model (params/dist.json). tools/make_page.py writes this line.
const DIST = {"version":0,"team":{"sd_pass":0.12,"sd_rush":0.2,"sd_eff":0.06,"td_el":1.5},"game":{"pace_vol":0.06,"pace_eff":0.14,"script_pass":0.08,"script_rush":0.2},"player":{"share_rb":0.38,"share_wr":0.25,"share_te":0.22,"share_qb":0.025,"exit":0.03,"exit_qb":0.02,"eff":{"QB":0,"RB":0.077,"WR":0.12,"TE":0.08}},"play":{"cv_rush":1.4,"cv_qbrush":1.04,"cv_catch_rb":1.5,"cv_catch_wr":0.9,"cv_catch_te":0.8,"other_ypt":7,"other_cv":1.6,"other_min":0.05,"other_car":0.03,"other_tgt":0.06},"mean":{"QB":{},"RB":{},"WR":{},"TE":{}},"pplay":{"base":{"Full":0.94,"Limited":0.75,"DNP":0.55,"none":0.75},"missed_last_or":0.57,"qb_or":0.3,"doubtful":0.012,"listed_no_status":0.974,"unlisted":0.995,"active":0.995},"kdst":{"k_sd":4.5,"dst_sd":6}};

/* Seeded random numbers (xoshiro128**), with the draws the simulation needs. */
function makeRng(seed) {
  let s = (seed >>> 0) || 1;
  const sm = () => { s = (s + 0x9e3779b9) | 0; let z = s; z = Math.imul(z ^ (z >>> 16), 0x85ebca6b); z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35); return (z ^ (z >>> 16)) >>> 0; };
  let a = sm(), b = sm(), c = sm(), d = sm();
  const rotl = (x, k) => (x << k) | (x >>> (32 - k));
  const u = () => {
    const r = Math.imul(rotl(Math.imul(b, 5), 7), 9), t = b << 9;
    c ^= a; d ^= b; b ^= c; a ^= d; c ^= t; d = rotl(d, 11);
    return ((r >>> 0) + 0.5) / 4294967296;
  };
  let spare = null;
  const normal = () => {
    if (spare !== null) { const x = spare; spare = null; return x; }
    let x, y, q;
    do { x = 2 * u() - 1; y = 2 * u() - 1; q = x * x + y * y; } while (q >= 1 || q === 0);
    const f = Math.sqrt(-2 * Math.log(q) / q);
    spare = y * f;
    return x * f;
  };
  const gamma = (k) => {               // shape k, scale 1 (Marsaglia-Tsang)
    if (!(k > 0)) return 0;
    if (k < 1) return gamma(k + 1) * Math.pow(u(), 1 / k);
    const dd = k - 1 / 3, cc = 1 / Math.sqrt(9 * dd);
    for (;;) {
      let x, v;
      do { x = normal(); v = 1 + cc * x; } while (v <= 0);
      v = v * v * v;
      const w = u();
      if (w < 1 - 0.0331 * x * x * x * x) return dd * v;
      if (Math.log(w) < 0.5 * x * x + dd * (1 - v + Math.log(v))) return dd * v;
    }
  };
  const poisson = (lam) => {
    if (!(lam > 0)) return 0;
    if (lam < 10) {                     // inversion
      let k = 0, p = Math.exp(-lam), F = p;
      const w = u();
      while (w > F && k < 200) { k++; p *= lam / k; F += p; }
      return k;
    }
    const sl = Math.sqrt(lam), ll = Math.log(lam), bb = 0.931 + 2.53 * sl, aa = -0.059 + 0.02483 * bb;
    const inva = 1.1239 + 1.1328 / (bb - 3.4), vr = 0.9277 - 3.6224 / (bb - 2);
    for (;;) {                          // transformed rejection (Hormann's PTRS)
      const U = u() - 0.5, V = u(), us = 0.5 - Math.abs(U);
      const k = Math.floor((2 * aa / us + bb) * U + lam + 0.43);
      if (us >= 0.07 && V <= vr) return k;
      if (k < 0 || (us < 0.013 && V > us)) continue;
      if (Math.log(V) + Math.log(inva) - Math.log(aa / (us * us) + bb) <= -lam + k * ll - logFact(k)) return k;
    }
  };
  const binom = (n, p) => { let k = 0; for (let i = 0; i < n; i++) if (u() < p) k++; return k; };
  return { u, normal, gamma, poisson, binom };
}
const _lf = [0];
function logFact(k) {
  if (k < 0) return 0;
  if (k < 256) { while (_lf.length <= k) _lf.push(_lf[_lf.length - 1] + Math.log(_lf.length)); return _lf[k]; }
  return (k + 0.5) * Math.log(k) - k + 0.5 * Math.log(2 * Math.PI) + 1 / (12 * k);
}

/* How a player's injury status reads for this week: game status, last practice, and whether he missed his
   team's last game. ESPN's status counts when your import is newer than the weekly data. */
function weekStatus(ctx, p) {
  const L = ctx.L, x = L.espn && L.espn.players && L.espn.players[p.id];
  const espnNewer = L.espn && L.espn.importedAt && new Date(L.espn.importedAt) > new Date(ctx.DB.builtAt || 0);
  const es = x && x.status ? ({ QUESTIONABLE: "Questionable", DOUBTFUL: "Doubtful", OUT: "Out", INJURY_RESERVE: "Out", SUSPENSION: "Out" })[x.status] || "" : "";
  let gs = p.gd === "active" ? "Active" : p.gd === "inactive" ? "Inactive" : (p.gs || "");
  if (!gs && /^(Questionable|Doubtful)/.test(p.inj || "")) gs = p.inj.startsWith("Doubtful") ? "Doubtful" : "Questionable";
  if (espnNewer && es && gs !== "Active" && gs !== "Inactive") gs = es;
  const byes = ctx.DB.byes[p.t] || [], cur = +ctx.S.curWeek;
  let last = 0;
  for (let w = cur - 1; w >= 1; w--) if (!byes.includes(w)) { last = w; break; }
  const missed = !!last && (p.lg == null ? !p.g26 : +p.lg < last);
  return { gs, pr: p.pr || "", missed };
}

/* Chance he plays this week (0 when he's out or on bye). */
function pPlay(ctx, p) {
  const v = ctx.val.get(p.id), P = DIST.pplay;
  if (!v || !v.avail[0]) return { p: 0, why: (ctx.DB.byes[p.t] || []).includes(+ctx.S.curWeek) ? "bye" : "out" };
  const st = weekStatus(ctx, p);
  if (st.gs === "Active") return { p: P.active, why: "active: his team's inactives are out" };
  if (st.gs === "Inactive" || st.gs === "Out") return { p: 0, why: "inactive" };
  if (st.gs === "Doubtful") return { p: P.doubtful, why: "doubtful" };
  if (st.gs === "Questionable") {
    const b = P.base[st.pr || "none"] ?? P.base.none;
    let odds = b / (1 - b);
    if (st.missed) odds *= P.missed_last_or;
    if (p.p === "QB") odds *= P.qb_or;
    const q = odds / (1 + odds);
    return { p: q, why: `questionable${st.pr ? `, ${st.pr === "DNP" ? "did not practice" : st.pr.toLowerCase() + " practice"} last` : ""}${st.missed ? ", missed last game" : ""}` };
  }
  if (st.pr) return { p: P.listed_no_status, why: "on the practice report, no game status" };
  return { p: P.unlisted, why: "" };
}

/* His expected stat line this week as the projection has it, ready for the simulation (null if he doesn't play). */
function distInputs(ctx, p, raw = false) {
  const U = ctx.val.usage, v = ctx.val.get(p.id);
  if (!U || !U.opp0 || !v || !v.avail[0] || !p.m) return null;
  const o = U.opp0.get(p.id);
  if (!o) return null;
  const E = v.env && v.env[0], m = p.m;
  const ey = E ? E.py : 1, et = E ? E.pt : 1, ry = E ? E.ry : 1, rt = E ? E.rt : 1;
  // the page's projection on top of the usage model (expert blends, your own number) scales his volume
  const model = v.modelWeekly[0], fin = ctx.wkA.get(p.id)[0];
  const r = model > 0.01 ? fin / model : 1;
  // raw: the projection's own stat line, without the calibration (tests compare it with dist/sim.py)
  const M = (!raw && DIST.mean[p.p]) || {}, g = (k) => (M[k] == null ? 1 : +M[k]);
  const sc = ctx.S.scoring, bp = (sc.byPos && sc.byPos[p.p]) || null;
  const w = SCORE_KEYS.map((k) => (bp && bp[k] != null && bp[k] !== "" ? +bp[k] : +sc[k] || 0));
  const qb = p.p === "QB";
  const att = qb ? o[2] * r : 0, car = qb ? att * m[11] : o[0] * r, tgt = qb ? 0 : o[1] * r;
  return {
    id: p.id, pos: p.p, qb, w, pplay: raw ? 1 : pPlay(ctx, p).p,
    car: car * g("vr"), tgt: tgt * g("vt"), att: att * g("vt"),
    ypc: m[3] * ry * g("ypc"), rtd: m[4] * rt * g("rtd"), cr: qb ? 0 : Math.min(1, m[5]),
    ypr: !qb && m[5] > 0 ? (m[6] * ey / m[5]) * g("ypr") : 0, ctd: !qb && m[5] > 0 ? (m[7] * et / m[5]) * g("ctd") : 0,
    py: qb ? att * m[8] * ey * g("py") : 0, ptd: qb ? att * m[9] * et * g("ptd") : 0, ipa: qb ? m[10] * g("int") : 0,
    fl: m[12], two: m[13], proj: fin,
  };
}

/*
 * Simulate this week's games for every team with a player in `ids` (whole teams: shares and passing need
 * teammates). Returns { n, pts: Map(id -> Float32Array of n points), inp: Map(id -> inputs), teams }.
 * Same seed, same numbers: start/sit comparisons use the same simulated games for every option.
 */
function simWeek(ctx, ids, opts = {}) {
  const n = Math.max(200, opts.n || 4000), R = makeRng(opts.seed ?? 20261017);
  const D = DIST, tm = D.team, gm = D.game, pl = D.player, pp = D.play;
  const DB = ctx.DB, U = ctx.val.usage;
  const teamsWanted = new Set();
  // a D/ST's week follows the offense it faces, so that offense is simulated too
  for (const id of ids) { const p = ctx.byId.get(id); if (p) { teamsWanted.add(p.t); if (p.p === "DST" && (DB.opp || {})[p.t]) teamsWanted.add(DB.opp[p.t]); } }
  if (opts.allTeams) for (const t of Object.keys(DB.teams || {})) teamsWanted.add(t);
  const opp = DB.opp || {};
  // team blocks
  const blocks = [];
  for (const t of teamsWanted) {
    const mates = (U && U.byTeam.get(t)) || [];
    const ps = [];
    for (const q of mates) { const x = distInputs(ctx, q, !!opts.raw); if (x && (x.car + x.tgt + x.att) > 0.02) ps.push(x); }
    if (!ps.length) continue;
    const k = ps.length;
    const B = { team: t, ps, k, opp: opp[t] || null };
    let ec = 0, et = 0, ea = 0, Ey = 0, Et = 0, Qy = 0, Qt = 0;
    for (const x of ps) {
      if (x.qb) { ea += x.att; Qy += x.py; Qt += x.ptd; }
      else { ec += x.car; et += x.tgt; Ey += x.tgt * x.cr * x.ypr; Et += x.tgt * x.cr * x.ctd; }
    }
    Object.assign(B, { ec, et, ea, Ey, Et, Qy, Qt, Oy: Math.max(pp.other_min * Qy, Qy - Ey), Ot: Math.max(pp.other_min * Qt, Qt - Et) });
    B.share = Float64Array.from(ps, (x) => (x.qb ? pl.share_qb : x.pos === "RB" ? pl.share_rb : x.pos === "WR" ? pl.share_wr : pl.share_te));
    B.exitp = Float64Array.from(ps, (x) => (x.qb ? pl.exit_qb : pl.exit));
    B.sde = Float64Array.from(ps, (x) => pl.eff[x.pos] || 0);
    B.cvc = Float64Array.from(ps, (x) => (x.pos === "RB" ? pp.cv_catch_rb : x.pos === "WR" ? pp.cv_catch_wr : pp.cv_catch_te));
    B.out = ps.map(() => new Float32Array(n));
    B.g = new Float64Array(k); B.f = new Float64Array(k); B.lc = new Float64Array(k); B.lt = new Float64Array(k); B.la = new Float64Array(k);
    // the offense's touchdowns and yards in each simulated game: its kicker's PATs and the other side's D/ST follow them
    B.tdS = new Float32Array(n); B.ydS = new Float32Array(n);
    B.tdE = ps.reduce((a, x) => a + x.car * x.rtd + (x.qb ? 0 : x.tgt * x.cr * x.ctd), 0) + (ea > 0 ? B.Ot : 0);
    blocks.push(B);
  }
  // games: pair teams that play each other (pace and script are shared); side +1 for the alphabetically first
  const gameOf = new Map();
  for (const B of blocks) {
    const o = B.opp, key = o ? [B.team, o].sort().join("-") : B.team;
    if (!gameOf.has(key)) gameOf.set(key, gameOf.size);
    B.game = gameOf.get(key);
    B.side = !o || B.team <= o ? 1 : -1;
  }
  const G = gameOf.size, pace = new Float64Array(G), script = new Float64Array(G);
  const varP = tm.sd_pass ** 2 + gm.pace_vol ** 2 + gm.script_pass ** 2, varR = tm.sd_rush ** 2 + gm.script_rush ** 2;
  const varQ = tm.sd_eff ** 2 + gm.pace_eff ** 2, varU = tm.sd_eff ** 2, tdl = tm.td_el;
  const gsum = (np, mean, cv) => (np > 0 && mean > 0 ? R.gamma(np / (cv * cv)) * mean * cv * cv : 0);
  // pool re-split: role shocks keep the pool's size, early exits hand work to teammates still playing
  const split = (B, E, which, other, out, sel) => {
    let tot = 0, ga = 0;
    for (let i = 0; i < B.k; i++) if (sel(B.ps[i])) { tot += E(B.ps[i]); ga += E(B.ps[i]) * B.g[i]; }
    if (tot <= 0) { for (let i = 0; i < B.k; i++) if (sel(B.ps[i])) out[i] = 0; return; }
    const gbar = (ga + other * tot) / ((1 + other) * tot);
    let kept = 0, lost = 0;
    for (let i = 0; i < B.k; i++) if (sel(B.ps[i])) { const a = E(B.ps[i]) * B.g[i] / gbar; out[i] = a * B.f[i]; kept += out[i]; lost += a - out[i]; }
    const K = kept + other * tot;
    for (let i = 0; i < B.k; i++) if (sel(B.ps[i])) out[i] = out[i] + (K > 0 ? lost * out[i] / K : 0);
  };
  const isSk = (x) => !x.qb, isQb = (x) => x.qb;
  const eCar = (x) => x.car, eTgt = (x) => x.tgt, eAtt = (x) => x.att;
  const nA = new Float64Array(64), recY = new Float64Array(64), recT = new Float64Array(64), nC = new Float64Array(64), nT = new Float64Array(64);
  for (let s = 0; s < n; s++) {
    for (let gI = 0; gI < G; gI++) { pace[gI] = R.normal(); script[gI] = R.normal(); }
    for (const B of blocks) {
      const pc = pace[B.game], sp = script[B.game] * B.side;
      // pace = the game's passing environment (shootouts, weather), shared; script splits the two teams
      const lp = tm.sd_pass * R.normal() + gm.pace_vol * pc - gm.script_pass * sp;
      const lr = tm.sd_rush * R.normal() + gm.script_rush * sp;
      const ze = tm.sd_eff * R.normal(), lq = ze + gm.pace_eff * pc;
      const vp = Math.exp(lp - 0.5 * varP), vr = Math.exp(lr - 0.5 * varR);
      const ve = Math.exp(lq - 0.5 * varQ), vt = Math.exp(tdl * lq - 0.5 * tdl * tdl * varQ);       // passing
      const vu = Math.exp(ze - 0.5 * varU), vtu = Math.exp(tdl * ze - 0.5 * tdl * tdl * varU);       // rushing
      for (let i = 0; i < B.k; i++) {
        const sd = B.share[i], kk = 1 / (sd * sd);
        B.g[i] = sd > 0 ? R.gamma(kk) / kk : 1;
        let f = R.u() < B.exitp[i] ? R.u() : 1;
        if (R.u() >= B.ps[i].pplay) f = 0;                 // inactive or scratched: his work goes to teammates
        B.f[i] = f;
      }
      split(B, eCar, "car", pp.other_car, B.lc, isSk);
      split(B, eTgt, "tgt", pp.other_tgt, B.lt, isSk);
      split(B, eAtt, "att", 0.01, B.la, isQb);
      let Sy = 0, St = 0, attTot = 0;
      for (let i = 0; i < B.k; i++) {
        const x = B.ps[i];
        const z = R.normal(), sde = B.sde[i];
        const eff = Math.exp(sde * z - 0.5 * sde * sde), etd = Math.exp(tdl * sde * z - 0.5 * tdl * tdl * sde * sde);
        if (x.qb) {
          const la = B.la[i] * vp;
          nA[i] = R.poisson(la);
          attTot += nA[i];
          const frac = x.att > 0 ? B.la[i] / x.att : 0;
          nC[i] = R.poisson(x.car * vp * frac);
          nT[i] = 0;
        } else {
          nC[i] = R.poisson(B.lc[i] * vr);
          nT[i] = R.poisson(B.lt[i] * vp);
          nA[i] = 0;
        }
        const ry = gsum(nC[i], x.ypc * vu * eff, x.qb ? pp.cv_qbrush : pp.cv_rush);
        const rtd = R.poisson(nC[i] * x.rtd * vtu * etd);
        let rec = 0, ryd = 0, rtdc = 0;
        if (!x.qb && nT[i] > 0) {
          rec = R.binom(nT[i], x.cr);
          ryd = gsum(rec, x.ypr * ve * eff, B.cvc[i]);
          rtdc = R.poisson(rec * x.ctd * vt * etd);
        }
        recY[i] = ryd; recT[i] = rtdc; Sy += ryd; St += rtdc;
        B.tdS[s] += rtd + rtdc; B.ydS[s] += ry + ryd;
        const ops = nC[i] + nT[i] + nA[i];
        const fl = R.poisson(ops * x.fl), two = R.poisson(ops * x.two);
        // QB passing is added below, once the receivers are done
        B.out[i][s] = x.w[3] * ry + x.w[4] * rtd + x.w[5] * rec + x.w[6] * ryd + x.w[7] * rtdc + x.w[8] * fl + x.w[9] * two;
      }
      if (B.ea > 0) {
        const oy = gsum((B.Oy / pp.other_ypt) * vp, pp.other_ypt * ve, pp.other_cv), ot = R.poisson(B.Ot * vp * vt);
        B.tdS[s] += ot; B.ydS[s] += oy;
        const tpy = B.Ey + B.Oy > 0 ? ((Sy + oy) / (B.Ey + B.Oy)) * B.Qy : 0;
        const tpt = B.Et + B.Ot > 0 ? ((St + ot) / (B.Et + B.Ot)) * B.Qt : 0;
        for (let i = 0; i < B.k; i++) {
          const x = B.ps[i];
          if (!x.qb) continue;
          const sh = attTot > 0 ? nA[i] / attTot : (B.Qy > 0 ? x.py / B.Qy : 0);
          const ints = R.poisson(nA[i] * x.ipa);
          B.out[i][s] += x.w[0] * tpy * sh + x.w[1] * tpt * sh + x.w[2] * ints;
        }
      }
    }
  }
  const pts = new Map(), inp = new Map();
  for (const B of blocks) B.ps.forEach((x, i) => { pts.set(x.id, B.out[i]); inp.set(x.id, x); });
  simKd(ctx, ids, opts, n, R, blocks, pts, inp);
  return { n, pts, inp, teams: blocks.map((B) => B.team) };
}

/*
 * Kickers and defenses in the same simulated games, from their expected stat lines this week, with the spreads and
 * links measured in box scores (DIST.kdst, dist/fit_dist.py fit_kdst). A kicker's PATs follow his offense's
 * simulated touchdowns (they correlate 0.87); his field-goal tries are steadier than a Poisson count, a little
 * fewer when there are more PATs (-0.21), and are made at his rate for each distance. A D/ST's points allowed come from the spread of real scores around the line, tied
 * to the opposing offense's simulated touchdowns when that offense is in the simulation; yards allowed move with
 * points allowed; sacks, interceptions and fumble recoveries rise on a good defensive day (each with its own
 * game shock), and some takeaways go for touchdowns. Scored with the league's settings; each player's simulated
 * mean is moved onto the page's projection (expert blends included).
 */
function simKd(ctx, ids, opts, n, R, blocks, pts, inp) {
  const DB = ctx.DB, cur = +ctx.S.curWeek, sc = ctx.S.scoring, KS = (DB.kdst && DB.kdst.sim) || null;
  if (!KS) return;
  const want = new Set();
  for (const id of ids) { const p = ctx.byId.get(id); if (p && p.kw) want.add(p); }
  if (opts.allTeams) for (const p of DB.players) if (p.kw) want.add(p);
  const blockOf = new Map(blocks.map((B) => [B.team, B]));
  const zc = new Map();
  const zTd = (B) => {     // an offense's simulated touchdowns, standardized, per game
    if (!B || !(B.tdE > 0.05)) return null;
    if (zc.has(B.team)) return zc.get(B.team);
    let m = 0, v = 0;
    for (let s = 0; s < n; s++) m += B.tdS[s];
    m /= n;
    for (let s = 0; s < n; s++) v += (B.tdS[s] - m) ** 2;
    const sd = Math.sqrt(v / n) || 1, z = Float64Array.from(B.tdS, (x) => (x - m) / sd);
    zc.set(B.team, z);
    return z;
  };
  const res = KS.paResid, cdf = [];
  let acc = 0, mu = 0;
  for (const [r, p] of res) { acc += p; cdf.push(acc); mu += r * p; }
  const qPA = (u) => { let i = 0; while (i < cdf.length - 1 && cdf[i] < u * acc) i++; return res[i][0]; };
  const qPois = (lam, u) => { let k = 0, p = Math.exp(-lam), F = p; while (u > F && k < 60) { k++; p *= lam / k; F += p; } return k; };
  const qBin = (nn, pp, u) => { let k = 0, p = Math.pow(1 - pp, nn), F = p; while (u > F && k < nn) { p *= ((nn - k) / (k + 1)) * (pp / (1 - pp)); k++; F += p; } return k; };
  const K = DIST.kdst || {}, EV = K.ev || {}, rp = K.pa_rho ?? 0.9, ryp = K.ya_pa ?? 0.68, rk = K.pat_rho ?? 0.87, vm = K.fga_vm ?? 1, rpf = K.pat_fga ?? 0;
  const g = (k) => +kdSet(sc, k) || 0, pt = kdSet(sc, "paTier") || [], yt = kdSet(sc, "yaTier") || [];
  const Phi = (x) => 0.5 * (1 + erf(x / Math.SQRT2));
  const mix = (z, e, r) => r * z + Math.sqrt(Math.max(0, 1 - r * r)) * e;
  for (const p of want) {
    const v = p.kw[cur], val = ctx.val.get(p.id);
    if (!v || !val || !val.avail[0]) continue;
    const proj = ctx.wkA.get(p.id)[0], shift = proj - scoreComp(v, sc, p.p);
    const pplay = p.p === "K" ? pPlay(ctx, p).p : 1;
    const out = new Float32Array(n);
    if (p.p === "K") {
      const zt = zTd(blockOf.get(p.t)), pat = v[0] + v[1], pPat = pat > 0 ? v[0] / pat : 0;
      const a = [v[2] + v[6], v[3] + v[7], v[4] + v[5] + v[8]], fga = a[0] + a[1] + a[2];
      const mk = [a[0] > 0 ? v[2] / a[0] : 0, a[1] > 0 ? v[3] / a[1] : 0, a[2] > 0 ? (v[4] + v[5]) / a[2] : 0];
      const six = v[4] + v[5] > 0 ? v[5] / (v[4] + v[5]) : 0;
      const nT = vm < 0.98 && fga > 0 ? Math.max(1, Math.round(fga / (1 - vm))) : 0, pT = nT ? Math.min(1, fga / nT) : 0;
      for (let s = 0; s < n; s++) {
        if (R.u() >= pplay) continue;
        // drives end in a touchdown or a field goal: more PATs, slightly fewer field-goal tries
        const wp = zt ? mix(zt[s], R.normal(), rk) : R.normal(), uf = Phi(mix(wp, R.normal(), rpf));
        const pa = qPois(pat, Phi(wp)), pm = R.binom(pa, pPat);
        const tries = nT ? qBin(nT, pT, uf) : qPois(fga, uf);
        const m = [0, 0, 0], x = [0, 0, 0];
        for (let t = 0; t < tries; t++) {
          const u = R.u() * fga, b = u < a[0] ? 0 : u < a[0] + a[1] ? 1 : 2;
          if (R.u() < mk[b]) m[b]++; else x[b]++;
        }
        const m6 = R.binom(m[2], six);
        out[s] = kScore([pm, pa - pm, m[0], m[1], m[2] - m6, m6, x[0], x[1], x[2]], sc) + shift;
      }
    } else {
      const zt = zTd(blockOf.get((DB.opp || {})[p.t]));
      const c = v[7] - mu, sdY = KS.yaSd || 75, take = v[1] + v[2], pTd = take > 0 ? Math.min(1, v[4] / take) : 0;
      const ev = ["sk", "it", "fr"].map((k, i) => [v[i], ...(EV[k] || [0, 0])]);
      for (let s = 0; s < n; s++) {
        const w = zt ? mix(zt[s], R.normal(), rp) : R.normal();
        const pa = Math.max(0, Math.round(c + qPA(Phi(w))));
        const ya = v[8] + sdY * mix(w, R.normal(), ryp);
        const cnt = ev.map(([lam, sig, cc]) => R.poisson(lam * Math.exp(sig * mix(-w, R.normal(), cc) - 0.5 * sig * sig)));
        const td = take > 0 && v[4] > 0 && (cnt[1] + cnt[2]) > 0 ? R.binom(cnt[1] + cnt[2], pTd) : R.poisson(take > 0 ? 0 : v[4]);
        let ti = 0; while (ti < 8 && pa >= [1, 7, 14, 18, 22, 28, 35, 46][ti]) ti++;
        let yi = 0; while (yi < 8 && ya >= [100, 200, 300, 350, 400, 450, 500, 550][yi]) yi++;
        out[s] = cnt[0] * g("sack") + cnt[1] * g("dInt") + cnt[2] * g("fumRec") + R.poisson(v[3]) * g("safety") + td * g("dTd")
          + R.poisson(v[5]) * g("stTd") + R.poisson(v[6]) * g("blk") + pa * g("ptsAllowed") + ya * g("ydsAllowed")
          + (+pt[ti] || 0) + (+yt[yi] || 0) + shift;
      }
    }
    pts.set(p.id, out);
    inp.set(p.id, { id: p.id, pos: p.p, qb: false, kd: true, pplay, proj, car: 0, tgt: 0, att: 0 });
  }
}
/* Error function (Abramowitz-Stegun 7.1.26, |error| < 1.5e-7). */
function erf(x) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}

/* Percentiles and chances from one player's simulated points. */
function distSummary(arr, proj) {
  const a = Float64Array.from(arr).sort(), n = a.length;
  const q = (p) => { const h = (n - 1) * p, i = Math.floor(h); return i + 1 < n ? a[i] + (h - i) * (a[i + 1] - a[i]) : a[n - 1]; };
  let s = 0;
  for (let i = 0; i < n; i++) s += a[i];
  const ge = (t) => { let lo = 0, hi = n; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < t) lo = m + 1; else hi = m; } return (n - lo) / n; };
  return { mean: s / n, p10: q(0.1), p25: q(0.25), p50: q(0.5), p75: q(0.75), p90: q(0.9), ge, sorted: a,
    boom: proj > 0 ? ge(1.5 * proj) : 0, bust: proj > 0 ? 1 - ge(0.5 * proj) : 0 };
}

/* Lineup slots as a list, narrowest first, each with the positions it takes. */
const SLOT_POS = { QB: ["QB"], RB: ["RB"], WR: ["WR"], TE: ["TE"], K: ["K"], DST: ["DST"], RBWR: ["RB", "WR"], WRTE: ["WR", "TE"], FLEX: ["RB", "WR", "TE"], OP: ["QB", "RB", "WR", "TE"] };
const SLOT_ORDER = ["QB", "RB", "WR", "TE", "K", "DST", "RBWR", "WRTE", "FLEX", "OP"];
/* Slots of a kind in the league (leagues imported before kickers and defenses were modeled kept them as slotsK/slotsDST). */
function slotCount(S, k) {
  const v = S.slots && S.slots[k];
  if (v != null && v !== "") return +v || 0;
  if (k === "K" && S.slotsK != null) return +S.slotsK || 0;
  if (k === "DST" && S.slotsDST != null) return +S.slotsDST || 0;
  return 0;
}
/* have: positions the data has players for (start/sit leaves out K or D/ST slots the data can't fill). */
function lineupSlotList(S, have) {
  const out = [];
  for (const k of SLOT_ORDER) {
    if (have && SLOT_POS[k].every((p) => !have.has(p))) continue;
    for (let i = 0; i < slotCount(S, k); i++) out.push({ k, pos: SLOT_POS[k] });
  }
  return out;
}
/* Put players in slots (bipartite matching). Returns slot index per player, or null if they don't fit. */
function fitSlots(slots, posList) {
  if (posList.length > slots.length) return null;
  const owner = new Array(slots.length).fill(-1);
  const tryP = (i, seen) => {
    for (let s = 0; s < slots.length; s++) {
      if (seen[s] || !slots[s].pos.includes(posList[i])) continue;
      seen[s] = true;
      if (owner[s] < 0 || tryP(owner[s], seen)) { owner[s] = i; return true; }
    }
    return false;
  };
  // narrow players first keeps flex slots open
  const order = posList.map((_, i) => i);
  for (const i of order) if (!tryP(i, new Array(slots.length).fill(false))) return null;
  const at = new Array(posList.length);
  owner.forEach((i, s) => { if (i >= 0) at[i] = s; });
  return at;
}
/* The highest-projection legal lineup from a list of { id, pos, v } (v = points to rank by). */
function bestByValue(slots, cands) {
  const c = cands.filter((x) => x.v > 0).sort((a, b) => b.v - a.v);
  const chosen = [];
  for (const x of c) {
    if (chosen.length >= slots.length) break;
    if (fitSlots(slots, chosen.concat([x]).map((y) => y.pos))) chosen.push(x);
  }
  return chosen;
}

/*
 * Start/sit for one matchup. mine/theirs: teams. Ranks lineups by the chance to win the week, not just by
 * projected points: P(win) = share of simulated weeks where your starters outscore theirs, kickers and defenses
 * included (with data built before they were modeled, their usual swings are added to both sides as noise).
 */
function startSit(ctx, mine, theirs, opts = {}) {
  const S = ctx.S, have = new Set(ctx.DB.players.map((p) => p.p)), slots = lineupSlotList(S, have);
  const ids = mine.roster.concat(theirs ? theirs.roster : []).filter((id) => ctx.byId.has(id));
  const sim = opts.sim || simWeek(ctx, ids, { n: opts.n || 4000, seed: opts.seed });
  const n = sim.n;
  const info = (id) => {
    const p = ctx.byId.get(id), arr = sim.pts.get(id), x = sim.inp.get(id);
    return { id, pos: p.p, proj: x ? x.proj : 0, pplay: x ? x.pplay : 0, arr, ok: !!arr };
  };
  const pool = (team) => team.roster.filter((id) => ctx.byId.has(id)).map(info).filter((x) => x.ok);
  const me = pool(mine);
  // the lineup they'd set: highest projection, discounted by the chance each plays
  const oppL = theirs ? bestByValue(slots, pool(theirs).map((x) => ({ ...x, v: x.proj * x.pplay }))) : [];
  const oppTot = new Float64Array(n);
  for (const x of oppL) for (let s = 0; s < n; s++) oppTot[s] += x.arr[s];
  // kickers and defenses the data doesn't have (built before they were modeled): their usual swing, both sides
  const K = DIST.kdst || { k_sd: 4.5, dst_sd: 6 };
  const nk = have.has("K") ? 0 : slotCount(S, "K"), nd = have.has("DST") ? 0 : slotCount(S, "DST");
  const kd = opts.kdst === false ? 0 : Math.sqrt(2 * (K.k_sd ** 2 * nk + K.dst_sd ** 2 * nd));
  const R = makeRng(7919), noise = new Float64Array(n);
  for (let s = 0; s < n; s++) noise[s] = kd * R.normal() + (opts.lead || 0);
  const pwin = (set) => {
    const tot = new Float64Array(n);
    for (const x of set) for (let s = 0; s < n; s++) tot[s] += x.arr[s];
    let w = 0;
    for (let s = 0; s < n; s++) { const d = tot[s] - oppTot[s] + noise[s]; w += d > 0 ? 1 : d === 0 ? 0.5 : 0; }
    return w / n;
  };
  // players whose game already started can't be moved: locked in (opts.lockedIn) or out (the rest of opts.locked)
  const locked = new Set(opts.locked || []), lockedIn = new Set(opts.lockedIn || []);
  const val = (x) => (locked.has(x.id) ? (lockedIn.has(x.id) ? 1e6 : -1) : x.proj * (x.pplay >= 0.5 ? 1 : x.pplay));
  const byProj = bestByValue(slots, me.map((x) => ({ ...x, v: val(x) })));
  // local search: swap one starter for one bench player while the chance to win goes up
  const inSet = (set, b) => set.some((x) => x.id === b.id);
  let cur = byProj.slice(), pCur = pwin(cur);
  for (let it = 0; it < 8; it++) {
    let best = null;
    for (let i = 0; i < cur.length; i++) for (const b of me) {
      if (inSet(cur, b) || locked.has(b.id) || locked.has(cur[i].id)) continue;
      const trial = cur.slice(); trial[i] = b;
      if (!fitSlots(slots, trial.map((x) => x.pos))) continue;
      const p = pwin(trial);
      if (p > pCur + 0.002 && (!best || p > best.p)) best = { trial, p };
    }
    // a lineup with an open slot: try every bench player in it
    if (cur.length < slots.length) for (const b of me) {
      if (inSet(cur, b) || locked.has(b.id)) continue;
      const trial = cur.concat([b]);
      if (!fitSlots(slots, trial.map((y) => y.pos))) continue;
      const p = pwin(trial);
      if (p > pCur + 0.002 && (!best || p > best.p)) best = { trial, p };
    }
    if (!best) break;
    cur = best.trial; pCur = best.p;
  }
  // for every starter in the best lineup: the chance to win with each bench player who could take his place
  const alts = cur.map((x, i) => {
    const opts2 = [];
    if (locked.has(x.id)) return { id: x.id, p: pCur, alts: opts2, locked: true };
    for (const b of me) {
      if (inSet(cur, b) || locked.has(b.id)) continue;
      const trial = cur.slice(); trial[i] = b;
      if (!fitSlots(slots, trial.map((y) => y.pos))) continue;
      opts2.push({ id: b.id, p: pwin(trial) });
    }
    return { id: x.id, p: pCur, alts: opts2.sort((a, b) => b.p - a.p) };
  });
  const sumMean = (set) => set.reduce((a, x) => a + x.arr.reduce((u, v) => u + v, 0) / n, 0);
  const assign = (set) => { const at = fitSlots(slots, set.map((x) => x.pos)) || []; return set.map((x, i) => ({ id: x.id, slot: slots[at[i]] ? slots[at[i]].k : "" })); };
  return { sim, slots, kd, opp: oppL.map((x) => x.id), oppMean: sumMean(oppL),
    proj: { ids: byProj.map((x) => x.id), p: pwin(byProj), mean: sumMean(byProj), lineup: assign(byProj) },
    best: { ids: cur.map((x) => x.id), p: pCur, mean: sumMean(cur), lineup: assign(cur) }, alts };
}

/*
 * One decision under a target: for each candidate, the chance that he plus your other players still to play
 * outscore their players still to play by more than you trail (lead < 0 when you're ahead). With nobody else
 * left on either side it is simply the chance he scores more than the deficit.
 */
function needCalc(ctx, cands, opts = {}) {
  const mineLeft = opts.mine || [], theirsLeft = opts.theirs || [];
  const sim = opts.sim || simWeek(ctx, cands.concat(mineLeft, theirsLeft), { n: opts.n || 6000, seed: opts.seed });
  const n = sim.n, base = new Float64Array(n);
  for (const id of mineLeft) { const a = sim.pts.get(id); if (a) for (let s = 0; s < n; s++) base[s] += a[s]; }
  for (const id of theirsLeft) { const a = sim.pts.get(id); if (a) for (let s = 0; s < n; s++) base[s] -= a[s]; }
  const K = DIST.kdst || { k_sd: 4.5, dst_sd: 6 };
  const kd = opts.kdst ? Math.sqrt(2 * (K.k_sd ** 2 + K.dst_sd ** 2)) : 0;
  const R = makeRng(104729), noise = new Float64Array(n);
  if (kd > 0) for (let s = 0; s < n; s++) noise[s] = kd * R.normal();
  const need = +opts.need || 0;
  return cands.map((id) => {
    const a = sim.pts.get(id);
    if (!a) return { id, p: 0, sum: null };
    let w = 0;
    for (let s = 0; s < n; s++) { const d = a[s] + base[s] + noise[s] - need; w += d > 0 ? 1 : d === 0 ? 0.5 : 0; }
    const x = sim.inp.get(id);
    return { id, p: w / n, sum: distSummary(a, x ? x.proj : 0), pplay: x ? x.pplay : 0 };
  });
}

/* ---------------- ESPN import ---------------- */
const ESPN_SLOTS = { 0: "QB", 2: "RB", 3: "RBWR", 4: "WR", 5: "WRTE", 6: "TE", 7: "OP", 23: "FLEX", 17: "K", 16: "DST" };
const ESPN_POS = { 1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST" };
const ESPN_SLOT_POS = { 0: "QB", 2: "RB", 4: "WR", 6: "TE" };
const ESPN_STATS = { 3: "passYd", 4: "passTd", 20: "int", 24: "rushYd", 25: "rushTd", 53: "rec", 42: "recYd", 43: "recTd", 72: "fumble", 19: "twoPt", 26: "twoPt", 44: "twoPt" };
// kickers and team defenses (ESPN stat ids; 74 is "FG made 50+" in old leagues and 50-59 once 201 is set)
const ESPN_KD_STATS = { 86: "patMade", 88: "patMiss", 80: "fg0", 77: "fg40", 74: "fg50", 201: "fg60", 85: "fgMiss", 82: "fgMiss0", 79: "fgMiss40", 76: "fgMiss50",
  99: "sack", 95: "dInt", 96: "fumRec", 98: "safety", 94: "dTd", 101: "stTd", 97: "blk", 120: "ptsAllowed", 127: "ydsAllowed" };
const ESPN_PA_TIERS = [89, 90, 91, 92, 121, 122, 123, 124, 125];
const ESPN_YA_TIERS = [128, 129, 130, 131, 132, 133, 134, 135, 136];
const ESPN_KD_KNOWN = new Set([...Object.keys(ESPN_KD_STATS).map(Number), ...ESPN_PA_TIERS, ...ESPN_YA_TIERS, 83, 93, 102, 103, 104, 105, 203]);

/* Pull a league ID (and season / team, when present) out of an ID or any ESPN link. */
function parseLeagueInput(text) {
  const s = String(text || "").trim();
  const pick = (re) => { const m = s.match(re); return m ? m[1] : null; };
  const leagueId = pick(/leagueId=(\d+)/i) || pick(/leagues\/(\d+)/i) || pick(/(?:^|\D)(\d{5,12})(?:\D|$)/);
  const season = pick(/seasonId=(\d{4})/i) || pick(/seasons\/(\d{4})/i);
  const teamId = pick(/teamId=(\d+)/i);
  return { leagueId, season: season ? +season : null, teamId: teamId ? +teamId : null };
}

function espnApiUrl(leagueId, season) {
  return `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/${season}/segments/0/leagues/${leagueId}?view=mSettings&view=mTeam&view=mRoster&view=mMatchup`;
}

/* Find the JSON object inside pasted text or page text. */
function extractJson(text) {
  if (text && typeof text === "object") return text;
  const s = String(text || "");
  const a = s.indexOf("{"), b = s.lastIndexOf("}");
  const a2 = s.indexOf("[");
  try {
    if (a2 >= 0 && (a < 0 || a2 < a)) return JSON.parse(s.slice(a2, s.lastIndexOf("]") + 1));
    if (a < 0 || b < a) throw new Error();
    return JSON.parse(s.slice(a, b + 1));
  } catch (e) {
    const err = new Error("That text isn't complete league data. Make sure you copied the whole page.");
    err.code = "not_json";
    throw err;
  }
}

function espnProjection(stats, season, week) {
  if (!Array.isArray(stats)) return null;
  const proj = stats.filter((x) => x && x.statSourceId === 1 && (x.seasonId == null || x.seasonId === season));
  const seas = proj.find((x) => x.statSplitTypeId === 0);
  const wk = proj.find((x) => x.statSplitTypeId === 1 && x.scoringPeriodId === week);
  let sPer = null;
  if (seas) sPer = seas.appliedAverage > 0 ? seas.appliedAverage : seas.appliedTotal > 0 ? seas.appliedTotal / 17 : null;
  const wPer = wk && wk.appliedTotal > 0 ? wk.appliedTotal : null;
  if (sPer != null && wPer != null) return 0.5 * sPer + 0.5 * wPer;
  return sPer != null ? sPer : wPer;
}

/* Kicker and D/ST scoring from ESPN's scoring items. Rules the league doesn't list score 0. */
function parseKdScoring(items) {
  const out = {}, by = new Map();
  for (const it of items || []) if (it && it.statId != null) by.set(+it.statId, +it.points || 0);
  for (const [id, k] of Object.entries(ESPN_KD_STATS)) out[k] = by.has(+id) ? by.get(+id) : 0;
  // FG made 50+ (74) covers 60+ in leagues without a 60+ rule; "total FG made" (83) adds to every distance
  if (!by.has(201)) out.fg60 = out.fg50;
  if (by.has(83)) for (const k of ["fg0", "fg40", "fg50", "fg60"]) out[k] += by.get(83);
  if (by.has(203) && !by.has(76)) out.fgMiss50 = by.get(203);
  // defensive TDs: one rule for all, or interception (103) / fumble (104) return TDs; return TDs: kickoff (101),
  // punt (102) or blocked kick (93) returns; "total return TD" (105) counts for both
  if (!by.has(94)) out.dTd = by.has(103) ? by.get(103) : by.has(104) ? by.get(104) : 0;
  if (!by.has(101)) out.stTd = by.has(102) ? by.get(102) : by.has(93) ? by.get(93) : 0;
  if (by.has(105)) { out.dTd += by.get(105); out.stTd += by.get(105); }
  out.paTier = ESPN_PA_TIERS.map((id) => (by.has(id) ? by.get(id) : 0));
  out.yaTier = ESPN_YA_TIERS.map((id) => (by.has(id) ? by.get(id) : 0));
  return out;
}

/*
 * Turn ESPN's league JSON (views mSettings, mTeam, mRoster) into league fields.
 * prev: the existing league with this ESPN id, if any (keeps your edits and your team).
 */
function parseEspn(raw, DB, opts) {
  opts = opts || {};
  let j = Array.isArray(raw) ? raw[0] : raw;
  if (!j || typeof j !== "object") throw Object.assign(new Error("That isn't ESPN league data."), { code: "bad" });
  if (!j.teams && (j.messages || j.details)) {
    const msg = [].concat(j.messages || []).join(" ") || (j.details && j.details[0] && j.details[0].message) || "";
    const priv = /not authorized|AUTH|private|not visible/i.test(msg + JSON.stringify(j.details || ""));
    throw Object.assign(new Error(priv ? "ESPN says this league is private. Sign in to ESPN in the same browser, then open the link again." : "ESPN answered: " + (msg || "no league data")), { code: priv ? "private" : "espn" });
  }
  if (!Array.isArray(j.teams) || !j.settings) throw Object.assign(new Error("This data is missing teams or settings. Use the link from this page, which asks ESPN for both."), { code: "bad" });
  const season = j.seasonId || opts.season || 2026;
  const week = j.scoringPeriodId || (j.status && j.status.latestScoringPeriod) || DB.curWeek;
  const set = j.settings;
  const report = { ignoredScoring: 0, kdst: 0, unmatched: [], warnings: [] };

  // scoring
  const scoring = { ...DEFAULT_SETTINGS.scoring, byPos: {} };
  const found = {};
  const items = (set.scoringSettings && set.scoringSettings.scoringItems) || [];
  for (const it of items) {
    const key = ESPN_STATS[it.statId];
    if (!key) { if (it.points && !ESPN_KD_KNOWN.has(+it.statId)) report.ignoredScoring++; continue; }
    if (key === "twoPt" && found.twoPt) continue;
    scoring[key] = +it.points || 0;
    found[key] = true;
    if (it.pointsOverrides) for (const [slot, pts] of Object.entries(it.pointsOverrides)) {
      const pos = ESPN_SLOT_POS[slot];
      if (pos) { scoring.byPos[pos] = scoring.byPos[pos] || {}; scoring.byPos[pos][key] = +pts; }
    }
  }
  for (const k of SCORE_KEYS) if (!found[k]) scoring[k] = 0;
  for (const k of ["passYd", "rushYd", "recYd"]) if (!found[k]) { scoring[k] = DEFAULT_SETTINGS.scoring[k]; report.warnings.push(`No ${k === "passYd" ? "passing" : k === "rushYd" ? "rushing" : "receiving"}-yards rule found; using ${DEFAULT_SETTINGS.scoring[k]} per yard. Check the League tab.`); }
  Object.assign(scoring, parseKdScoring(items));

  // lineup
  const slots = { QB: 0, RB: 0, WR: 0, TE: 0, RBWR: 0, WRTE: 0, FLEX: 0, OP: 0, K: 0, DST: 0 };
  const counts = (set.rosterSettings && set.rosterSettings.lineupSlotCounts) || {};
  for (const [sid, n] of Object.entries(counts)) if (ESPN_SLOTS[sid]) slots[ESPN_SLOTS[sid]] += +n || 0;
  const hasPos = new Set(DB.players.map((p) => p.p));

  // schedule
  const sch = set.scheduleSettings || {};
  const regWeeks = +sch.matchupPeriodCount || 14;
  const rounds = Math.ceil(Math.log2(Math.max(2, +sch.playoffTeamCount || 4)));
  const lastWeek = Math.min(18, regWeeks + rounds * (+sch.playoffMatchupPeriodLength || 1));

  const acq = set.acquisitionSettings || {};
  // players and teams
  const byEspn = new Map(DB.players.filter((p) => p.espn).map((p) => [String(p.espn), p]));
  const members = new Map((j.members || []).map((m) => [m.id, m]));
  const players = {};
  const autoOut = {};
  const teams = j.teams.map((t) => {
    const owner = (t.owners || []).map((o) => members.get(o)).filter(Boolean)[0];
    const ownerName = owner ? (owner.displayName || [owner.firstName, owner.lastName].filter(Boolean).join(" ")) : "";
    const name = (t.name || `${t.location || ""} ${t.nickname || ""}`.trim() || t.abbrev || "Team " + t.id).replace(/\s+/g, " ").trim();
    const roster = [];
    for (const e of (t.roster && t.roster.entries) || []) {
      const ppe = e.playerPoolEntry || {};
      const pl = ppe.player || {};
      const pid = String(e.playerId || pl.id || ppe.id || "");
      const pos = ESPN_POS[pl.defaultPositionId];
      const p = byEspn.get(pid);
      if (!p) {
        // data built before kickers and defenses were modeled has none of them
        if ((pos === "K" && !hasPos.has("K")) || (pos === "D/ST" && !hasPos.has("DST"))) report.kdst++;
        else report.unmatched.push(pl.fullName || "ESPN player " + pid);
        continue;
      }
      roster.push(p.id);
      const own = pl.ownership || {};
      const rating = ppe.ratings && (ppe.ratings["0"] || ppe.ratings[0]);
      const status = pl.injuryStatus || e.injuryStatus || "";
      const det = pl.injuryDetails || e.injuryDetails || null;
      let espnThru = null;
      if (det && det.outForSeason) espnThru = 18;
      else if (det && det.expectedReturnDate) {
        const d = Array.isArray(det.expectedReturnDate) ? `${det.expectedReturnDate[0]}-${String(det.expectedReturnDate[1]).padStart(2, "0")}-${String(det.expectedReturnDate[2]).padStart(2, "0")}` : det.expectedReturnDate;
        const rw = weekOfDate(DB, d);
        if (rw != null) espnThru = rw - 1;
      }
      players[p.id] = {
        rost: own.percentOwned != null ? +(+own.percentOwned).toFixed(1) : null,
        start: own.percentStarted != null ? +(+own.percentStarted).toFixed(1) : null,
        adp: own.averageDraftPosition > 0 && own.averageDraftPosition < 400 ? +(+own.averageDraftPosition).toFixed(1) : null,
        prk: rating && rating.positionalRanking > 0 ? rating.positionalRanking : null,
        proj: espnProjection(pl.stats, season, week),
        status,
        slot: e.lineupSlotId,
        ret: espnThru,
      };
      // precedence: ESPN's own return estimate, then the built-in timeline, then a rule of thumb
      const healthy = status === "ACTIVE" || status === "NORMAL" || status === "QUESTIONABLE" || status === "PROBABLE";
      const tl = defaultOut(DB, p, week);
      if (espnThru != null && espnThru >= week) autoOut[p.id] = espnThru;
      else if (healthy && e.lineupSlotId !== 21) autoOut[p.id] = 0; // ESPN shows him available
      else if (tl != null) autoOut[p.id] = tl;
      else if (e.lineupSlotId === 21 || status === "INJURY_RESERVE") autoOut[p.id] = week + 3;
      else if (status === "OUT" || status === "DOUBTFUL" || status === "SUSPENSION") autoOut[p.id] = week;
    }
    const tc = t.transactionCounter || {};
    const faabLeft = acq.isUsingAcquisitionBudget ? Math.max(0, (+acq.acquisitionBudget || 0) - (+tc.acquisitionBudgetSpent || 0)) : null;
    const rec = (t.record && t.record.overall) || {};
    const record = rec.wins != null || rec.losses != null
      ? { wins: +rec.wins || 0, losses: +rec.losses || 0, ties: +rec.ties || 0, streak: rec.streakLength ? `${rec.streakType === "WIN" ? "W" : rec.streakType === "LOSS" ? "L" : "T"}${rec.streakLength}` : "", pf: rec.pointsFor != null ? +rec.pointsFor : null }
      : null;
    return { id: "espn-" + t.id, espnTeamId: t.id, name, owner: ownerName, mine: false, roster, faab: faabLeft, ...(record || {}) };
  });
  return {
    leagueId: String(j.id || opts.leagueId || ""),
    season,
    name: set.name || "ESPN league " + (j.id || ""),
    settings: { teams: +set.size || teams.length, scoring, slots, curWeek: week, lastWeek, playoffStart: regWeeks + 1,
      faab: !!acq.isUsingAcquisitionBudget, faabBudget: +acq.acquisitionBudget || 100 },
    teams,
    autoOut,
    players,
    report,
    // weekly matchups (with view=mMatchup): start/sit picks this week's opponent
    schedule: Array.isArray(j.schedule) ? j.schedule.filter((m) => m && m.home && m.away && m.matchupPeriodId != null)
      .map((m) => ({ w: +m.matchupPeriodId, h: "espn-" + m.home.teamId, a: "espn-" + m.away.teamId })) : null,
  };
}

/* Merge an ESPN import into a league (new or existing), keeping the user's edits. */
function applyEspn(prev, imp, DB, mineEspnTeamId) {
  const L = prev ? JSON.parse(JSON.stringify(prev)) : newLeague(DB);
  L.name = imp.name;
  L.example = false;
  L.settings = { ...L.settings, ...imp.settings, scoring: imp.settings.scoring, slots: imp.settings.slots };
  delete L.settings.slotsK; delete L.settings.slotsDST;   // now slots.K / slots.DST
  const mineId = mineEspnTeamId != null ? +mineEspnTeamId : (prev && (prev.teams.find((t) => t.mine) || {}).espnTeamId);
  // keep what the user set for each manager (style; a record typed in when ESPN sent none)
  const prevBy = new Map(((prev && prev.teams) || []).map((t) => [t.espnTeamId, t]));
  L.teams = imp.teams.map((t) => {
    const o = prevBy.get(t.espnTeamId) || {};
    const keep = { style: o.style, fav: o.fav, fan: o.fan };
    if (t.wins == null && o.wins != null) Object.assign(keep, { wins: o.wins, losses: o.losses, ties: o.ties });
    return { ...keep, ...t, mine: mineId != null && t.espnTeamId === +mineId };
  });
  if (!L.teams.some((t) => t.mine) && L.teams[0]) L.teams[0].mine = true;
  L.autoOut = imp.autoOut;
  L.espn = { leagueId: imp.leagueId, season: imp.season, importedAt: new Date().toISOString(), players: imp.players };
  if (imp.schedule && imp.schedule.length) L.espn.schedule = imp.schedule;
  else if (prev && prev.espn && prev.espn.schedule) L.espn.schedule = prev.espn.schedule;
  L.out = L.out || {};
  L.overrides = L.overrides || {};
  return L;
}

if (typeof module !== "undefined" && module.exports) module.exports = { POSITIONS, OFF_POS, KD_POS, POS_LABEL, K_KEYS, D_KEYS, PA_TIERS, YA_TIERS, kScore, dScore, kdModel, parseKdScoring, slotCount, lineupFast, POS_CODE, PARAMS, DIST, makeRng, pPlay, weekStatus, distInputs, simWeek, distSummary, lineupSlotList, fitSlots, bestByValue, startSit, needCalc, shareOpp, faabPerDollar, faabValue, faabOf, depthFor, teamDepth, streamLevels, overWaiver, roleNotes, usageModel, sharePts, effOut, weekOfDate, defaultOut, DEFAULT_SETTINGS, newLeague, buildCtx, valuations, teamValue, evalTrade, findTrades, contextValues, lineupForWeek, sampleLeague, scoreComp, vorpQ, marketPrice, marketPrices, perspective, fanOf, teamMood, styleOf, styleWeights, perceive, outWeek, parseLeagueInput, espnApiUrl, extractJson, parseEspn, applyEspn, SIGNALS };
