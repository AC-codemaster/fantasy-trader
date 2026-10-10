"""Fantasy Trader projection scorecard: freeze each week's projections, then grade them.

    python3 scorecard.py freeze --page fantasy-trader.html [--version V] [--now ISO] [--note TEXT]
    python3 scorecard.py grade [--weeks 5,6]

Run inside the weekly build folder. `build_db.py --fetch` leaves the inputs there: s26.csv, snaps26.csv,
games.csv, db_playerids.csv, fp_latest_weekly.csv. Node must be on the PATH (freeze only).

Files (kept in the scorecard artifact between weekly runs; restore them into this folder first):
  freeze/{season}-w{WW}.json  this week's projections exactly as the page shows them, written once and
                              never edited (freeze refuses to overwrite)
  graded/{season}-w{WW}.csv   one row per frozen player: projection, actual result, FantasyPros numbers
  data/scorecard.json         weekly + cumulative metrics, diagnostics, candidate model changes (the page reads it)
  scorecard.md                the same in words, for the weekly summary and the project docs

Our numbers: the page's own engine and data, run headlessly with default league settings (12 teams, PPR;
half-PPR and standard kept too). "page" = what the Players tab shows for this week (usage model + expert
blends); "model" = the usage model alone; components and opportunities come from the usage model.
Competitor: FantasyPros weekly expert consensus (rank and projected points), from DynastyProcess's daily
snapshots in git history. fp_early = first snapshot for the week (about when we freeze on Tuesday, so the
same information); fp_final = last snapshot before each player's kickoff (all the week's news).
Graded on players who played. "rel" = fantasy-relevant: top QB24/RB48/WR60/TE24 by either side.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

POS = ["QB", "RB", "WR", "TE"]
COMP = ["py", "ptd", "int", "ry", "rtd", "rec", "recy", "rectd", "fl", "two"]
SCORE = {"ppr": [0.04, 4, -2, 0.1, 6, 1.0, 0.1, 6, -2, 2], "half": [0.04, 4, -2, 0.1, 6, 0.5, 0.1, 6, -2, 2],
         "std": [0.04, 4, -2, 0.1, 6, 0.0, 0.1, 6, -2, 2]}
REL_N = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}
CLOSE = 12           # start/sit calls: same-position pairs within this many consensus ranks of each other
DP_REPO = "https://github.com/dynastyprocess/data"
DP_HIST = "dp-history"
FP_FILE = "files/fp_latest_weekly.csv"
SOURCES = ["page", "model", "fp_early", "fp_final"]
LABEL = {"page": "Our page", "model": "Our usage model (no expert blend)", "fp_early": "FantasyPros, Tuesday",
         "fp_final": "FantasyPros, final"}

# ----------------------------------------------------------------------------- engine runner (Node)
ENGINE_JS = r"""
const fs = require("fs");
const [pagePath] = process.argv.slice(2);
const html = fs.readFileSync(pagePath, "utf8");
const dm = html.match(/<script type="application\/json" id="db">([\s\S]*?)<\/script>/);
if (!dm) throw new Error("no db script element");
const DB = JSON.parse(dm[1].replace(/<\\\//g, "</"));
const a = html.indexOf("/* Fantasy Trader valuation engine");
const b = html.indexOf("module.exports = {", a);
if (a < 0 || b < 0) throw new Error("engine markers not found");
const mod = { exports: {} };
new Function("module", html.slice(a, html.indexOf("\n", b)))(mod);
const E = mod.exports;
const KEYS = ["passYd", "passTd", "int", "rushYd", "rushTd", "rec", "recYd", "recTd", "fumble", "twoPt"];
const league = (sc) => {
  const L = E.newLeague(DB);
  L.settings.scoring = { ...sc, byPos: {} };
  return L;
};
const base = E.DEFAULT_SETTINGS.scoring;
const unit = (k) => Object.fromEntries(KEYS.map((x) => [x, x === k ? 1 : 0]));
const V = {};
for (const [name, rec] of [["ppr", 1], ["half", 0.5], ["std", 0]]) V[name] = E.valuations(DB, league({ ...base, rec }));
const comp = KEYS.map((k) => E.usageModel(DB, league(unit(k))).res);
// opportunities: with catch rate, INT rate and fumble rate set to 1, those components count targets,
// pass attempts and (carries + targets) or (attempts + QB carries); none of them has an environment factor
const DB2 = { ...DB, players: DB.players.map((p) => { const m = p.m.slice(); m[5] = 1; m[10] = 1; m[12] = 1; return { ...p, m }; }) };
const oT = E.usageModel(DB2, league(unit("rec"))).res, oA = E.usageModel(DB2, league(unit("int"))).res, oO = E.usageModel(DB2, league(unit("fumble"))).res;
const r3 = (x) => (x == null || !isFinite(x) ? null : Math.round(x * 1000) / 1000);
const out = [];
for (const p of DB.players) {
  const v = V.ppr.get(p.id);
  if (!v) continue;
  const env = v.env && v.env[0];
  const tgt = p.p === "QB" ? 0 : oT.get(p.id).now[0], att = p.p === "QB" ? oA.get(p.id).now[0] : 0, opp = oO.get(p.id).now[0];
  out.push({
    id: p.id, name: p.n, pos: p.p, team: p.t, age: p.age ?? null, g26: p.g26 || 0, g25: p.g25 || 0, g24: p.g24 || 0,
    dc: p.dc ?? null, er: p.er ?? null, ew: p.ew ?? null, own: p.own ?? null, inj: p.inj || "",
    ij_thru: p.ij && p.ij.thru != null ? p.ij.thru : null, avail: v.avail[0] ? 1 : 0,
    page_ppr: r3(v.weekly[0]), page_half: r3(V.half.get(p.id).weekly[0]), page_std: r3(V.std.get(p.id).weekly[0]),
    model_ppr: r3(v.modelWeekly[0]), corr_ppr: r3(v.corr), wkexp_ppr: r3(v.wkExp),
    back: r3(v.back ? v.back[0] : 1), role_shift: r3(v.roleShift),
    env_x: env ? r3(env.x) : null, env_spread: env ? r3(env.s) : null, env_imp: env ? r3(env.imp) : null,
    ...Object.fromEntries(["py", "ptd", "int", "ry", "rtd", "rec", "recy", "rectd", "fl", "two"].map((c, i) => ["c_" + c, r3(comp[i].get(p.id).now[0])])),
    o_tgt: r3(tgt), o_car: r3(p.p === "QB" ? opp - att : opp - tgt), o_att: r3(att),
  });
}
process.stdout.write(JSON.stringify({ meta: { builtAt: DB.builtAt, asOf: DB.asOf, season: DB.season, week: DB.curWeek,
  ewWeek: DB.ewWeek ?? null, sources: DB.sources, expertWeight: E.DEFAULT_SETTINGS.expertWeight,
  weeklyExpert: E.DEFAULT_SETTINGS.weeklyExpert }, players: out }));
"""


def now_utc():
    return datetime.now(timezone.utc)


def week_starts(games, season):
    g = games[(games.season == season) & (games.game_type == "REG")]
    return {int(w): str(d) for w, d in g.groupby("week").gameday.min().items()}


def week_of_day(starts, day):
    ws = [w for w, d in starts.items() if d <= day]
    return max(ws) if ws else None


def kickoffs(games, season, week):
    """team -> kickoff (UTC Timestamp) for that week's games."""
    g = games[(games.season == season) & (games.week == week) & (games.game_type == "REG")]
    out = {}
    for r in g.itertuples():
        t = pd.Timestamp(f"{r.gameday} {r.gametime}", tz="America/New_York").tz_convert("UTC")
        out[r.home_team] = out[r.away_team] = t
    return out


def fp_ids():
    ids = pd.read_csv("db_playerids.csv", low_memory=False, usecols=["fantasypros_id", "gsis_id"]).dropna()
    ids["fantasypros_id"] = pd.to_numeric(ids.fantasypros_id, errors="coerce")
    return ids.dropna().drop_duplicates("fantasypros_id").set_index("fantasypros_id").gsis_id.to_dict()


def fp_frame(df, fp2g, starts):
    """FantasyPros weekly rows for QB/RB/WR/TE with gsis id, kickoff and the week they're for."""
    d = df[df.pos.isin(POS)].copy()
    d["gsis"] = pd.to_numeric(d.fantasypros_id, errors="coerce").map(fp2g)
    d["kick"] = pd.to_numeric(d.player_game_kickoff_ts, errors="coerce")
    day = pd.to_datetime(d.kick, unit="s", utc=True).dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    d["week"] = day.map(lambda x: week_of_day(starts, x) if isinstance(x, str) else None)
    return d.dropna(subset=["gsis", "ecr"])


# ----------------------------------------------------------------------------- freeze
def freeze(a):
    games = pd.read_csv("games.csv", low_memory=False)
    js = "_engine_runner.js"
    open(js, "w").write(ENGINE_JS)
    res = subprocess.run(["node", js, a.page], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit("engine run failed:\n" + res.stderr[-2000:])
    out = json.loads(res.stdout)
    meta, P = out["meta"], pd.DataFrame(out["players"])
    S, W = int(meta["season"]), int(meta["week"])
    path = f"freeze/{S}-w{W:02d}.json"
    if os.path.exists(path) and not a.force:
        print(f"{path} already exists; a freeze is never overwritten. Nothing to do.")
        return
    now = pd.Timestamp(a.now) if a.now else pd.Timestamp(now_utc())
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    kick = kickoffs(games, S, W)
    P["kick"] = P.team.map(lambda t: kick[t].isoformat() if t in kick else None)
    bye = P.kick.isna()
    started = P.kick.notna() & P.kick.map(lambda k: k is not None and pd.Timestamp(k) <= now)
    P = P[~bye & ~started].copy()
    # FantasyPros at freeze time (also recoverable later from git history; kept here as a fallback)
    P["fp_ecr"], P["fp_pts"], fp_date = np.nan, np.nan, None
    if os.path.exists("fp_latest_weekly.csv"):
        fp = fp_frame(pd.read_csv("fp_latest_weekly.csv", low_memory=False), fp_ids(), week_starts(games, S))
        fp = fp[fp.week == W].drop_duplicates("gsis").set_index("gsis")
        if len(fp):
            P["fp_ecr"] = P.id.map(fp.ecr)
            P["fp_pts"] = P.id.map(fp.r2p_pts)
            fp_date = str(fp.scrape_date.iloc[0])
    meta.update(frozenAt=now.strftime("%Y-%m-%dT%H:%M:%SZ"), pageVersion=a.version, note=a.note or "",
                fpScrape=fp_date, excludedStarted=sorted({t for t, k in kick.items() if k <= now}), n=len(P))
    os.makedirs("freeze", exist_ok=True)
    cols = list(P.columns)
    rows = P[cols].astype(object).where(P[cols].notna(), None).values.tolist()
    json.dump({"meta": meta, "cols": cols, "rows": rows}, open(path, "w"), separators=(",", ":"))
    av = P[P.avail == 1]
    print(f"froze {path}: {len(P)} players ({len(av)} expected to play), week {W}, page data built {meta['builtAt']}")
    if meta["excludedStarted"]:
        print("  left out (game already started):", ", ".join(meta["excludedStarted"]))
    print(f"  FantasyPros at freeze: {P.fp_ecr.notna().sum()} players matched (scrape {fp_date})")
    for pos in POS:
        top = av[av.pos == pos].nlargest(3, "page_ppr")
        print(f"  {pos}: " + ", ".join(f"{r.name} {r.page_ppr:.1f}" for r in top.itertuples()))


def load_freeze(path):
    j = json.load(open(path))
    return j["meta"], pd.DataFrame(j["rows"], columns=j["cols"])


# ----------------------------------------------------------------------------- FantasyPros history
def fp_history(season, starts, need_weeks, last_kick):
    """{week: list of (commit_ts, DataFrame)} from DynastyProcess daily snapshots in git history."""
    if not os.path.isdir(os.path.join(DP_HIST, ".git")):
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", DP_REPO, DP_HIST], check=True)
    else:
        subprocess.run(["git", "-C", DP_HIST, "fetch", "-q", "origin"], check=True)
        subprocess.run(["git", "-C", DP_HIST, "update-ref", "HEAD", "FETCH_HEAD"], check=True)
    lo = min(starts[w - 1] if w - 1 in starts else starts[w] for w in need_weeks)
    log = subprocess.run(["git", "-C", DP_HIST, "log", "--format=%H %ct", f"--since={lo}", "HEAD", "--", FP_FILE],
                         capture_output=True, text=True, check=True).stdout.split()
    commits = sorted((int(log[i + 1]), log[i]) for i in range(0, len(log), 2))
    hi = max(last_kick[w] for w in need_weeks).timestamp()
    fp2g = fp_ids()
    out = {w: [] for w in need_weeks}
    from io import StringIO
    for ts, sha in commits:
        if ts > hi:
            continue
        raw = subprocess.run(["git", "-C", DP_HIST, "show", f"{sha}:{FP_FILE}"], capture_output=True, text=True)
        if raw.returncode != 0:
            continue
        d = fp_frame(pd.read_csv(StringIO(raw.stdout), low_memory=False), fp2g, starts)
        if not len(d):
            continue
        wk = int(d.week.mode().iloc[0])
        if wk in out:
            out[wk].append((ts, d[d.week == wk]))
    return out


def fp_views(snaps):
    """fp_early (first snapshot of the week) and fp_final (last snapshot before each player's kickoff)."""
    if not snaps:
        return None, None, None
    snaps = sorted(snaps, key=lambda x: x[0])
    t0, e = snaps[0]
    early = e.drop_duplicates("gsis").set_index("gsis")[["ecr", "r2p_pts"]]
    fin = {}
    for ts, d in snaps:
        for r in d.itertuples():
            if pd.notna(r.kick) and ts < r.kick:
                fin[r.gsis] = (r.ecr, r.r2p_pts, ts)
    final = pd.DataFrame.from_dict(fin, orient="index", columns=["ecr", "r2p_pts", "ts"])
    return early, final, datetime.fromtimestamp(t0, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ----------------------------------------------------------------------------- actual results
def actuals(season, week):
    s = pd.read_csv("s26.csv" if season == 2026 else f"s{str(season)[2:]}.csv", low_memory=False)
    s = s[(s.season_type == "REG") & (s.week == week)].copy()
    s["fl"] = s[["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]].fillna(0).sum(axis=1)
    s["two"] = s[["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"]].fillna(0).sum(axis=1)
    src = ["passing_yards", "passing_tds", "passing_interceptions", "rushing_yards", "rushing_tds", "receptions",
           "receiving_yards", "receiving_tds", "fl", "two"]
    g = s.groupby("player_id")
    A = g[src + ["carries", "targets", "attempts"]].sum()
    A.columns = ["a_" + c for c in COMP] + ["a_car", "a_tgt", "a_att"]
    A["a_team"] = g.team.last()
    played = set(A.index)
    sn = pd.read_csv("snaps26.csv" if season == 2026 else f"snaps{str(season)[2:]}.csv", low_memory=False)
    sn = sn[(sn.week == week) & (sn.offense_snaps > 0)]
    ids = pd.read_csv("db_playerids.csv", low_memory=False, usecols=["pfr_id", "gsis_id"]).dropna()
    pfr = ids.drop_duplicates("pfr_id").set_index("pfr_id").gsis_id.to_dict()
    played |= set(sn.pfr_player_id.map(pfr).dropna())
    return A, played, set(s.team)


def comp_pts(df, prefix, kind="ppr"):
    w = SCORE[kind]
    return sum(df[prefix + c].fillna(0) * w[i] for i, c in enumerate(COMP))


# ----------------------------------------------------------------------------- grading
def grade_week(path, games, hist):
    meta, F = load_freeze(path)
    S, W = int(meta["season"]), int(meta["week"])
    A, played, stat_teams = actuals(S, W)
    g = games[(games.season == S) & (games.week == W) & (games.game_type == "REG")]
    done_teams = set()
    for r in g.itertuples():
        if pd.notna(r.home_score) and r.home_team in stat_teams and r.away_team in stat_teams:
            done_teams |= {r.home_team, r.away_team}
    all_teams = set(g.home_team) | set(g.away_team)
    status = "final" if all_teams <= done_teams else "partial"
    F = F.copy()
    F["game_done"] = F.team.isin(done_teams).astype(int)
    F = F.join(A, on="id")
    F["played"] = F.id.isin(played).astype(int) * F.game_done
    for c in ["a_" + c for c in COMP] + ["a_car", "a_tgt", "a_att"]:
        F[c] = F[c].fillna(0.0)
    for k in SCORE:
        F[f"act_{k}"] = comp_pts(F, "a_", k)
    early, final, t0 = fp_views(hist.get(W, [])) if hist is not None else (None, None, None)
    if early is None and F.fp_ecr.notna().any():   # no history: fall back to the numbers saved at the freeze
        early = F.dropna(subset=["fp_ecr"]).set_index("id")[["fp_ecr", "fp_pts"]].rename(columns={"fp_ecr": "ecr", "fp_pts": "r2p_pts"})
        t0 = meta.get("fpScrape")
    F["fpe_ecr"] = F.id.map(early.ecr) if early is not None else np.nan
    F["fpe_pts"] = F.id.map(early.r2p_pts) if early is not None else np.nan
    F["fpf_ecr"] = F.id.map(final.ecr) if final is not None and len(final) else np.nan
    F["fpf_pts"] = F.id.map(final.r2p_pts) if final is not None and len(final) else np.nan
    F["season"], F["week"] = S, W
    info = {"week": W, "season": S, "status": status, "frozenAt": meta.get("frozenAt"), "pageBuilt": meta.get("builtAt"),
            "note": meta.get("note", ""), "fpEarlyAt": t0, "gamesDone": len(done_teams) // 2, "games": len(all_teams) // 2,
            "excludedStarted": meta.get("excludedStarted", [])}
    return F, info


def relevant(D):
    """Fantasy-relevant rows: top N at the position by FantasyPros final rank or by our projection."""
    keep = pd.Series(False, index=D.index)
    for (w, pos), d in D.groupby(["week", "pos"]):
        n = REL_N[pos]
        a = d[d.avail == 1].nlargest(n, "page_ppr").index
        b = d.dropna(subset=["fpf_ecr"]).nsmallest(n, "fpf_ecr").index
        keep.loc[a.union(b)] = True
    return keep


def pred(D, src):
    """Point projection for a source (None if it has no points)."""
    return {"page": D.page_ppr, "model": D.model_ppr, "fp_early": D.fpe_pts, "fp_final": D.fpf_pts}[src]


def order(D, src):
    """Ranking score (higher = better) for a source."""
    return {"page": D.page_ppr, "model": D.model_ppr, "fp_early": -D.fpe_ecr, "fp_final": -D.fpf_ecr}[src]


def cluster_mean(d, cl):
    """Mean and cluster-robust standard error of d (clusters = games or position-weeks)."""
    d = np.asarray(d, float)
    n = len(d)
    if n < 2:
        return (float(d.mean()) if n else None), None
    m = d.mean()
    s = pd.Series(d - m).groupby(np.asarray(cl)).sum()
    k = len(s)
    se = np.sqrt((s ** 2).sum() * k / max(k - 1, 1)) / n
    return float(m), float(se)


def pairs(D, a, b=None):
    """Start/sit calls: same-position, same-week pairs within CLOSE consensus ranks (fp_final), actual
    scores different. Returns per-pair correctness for source a (and b), with cluster ids."""
    outa, outb, cl = [], [], []
    for (w, pos), d in D.groupby(["week", "pos"]):
        d = d.dropna(subset=["fpf_ecr"])
        if len(d) < 2:
            continue
        rk = d.fpf_ecr.rank(method="first").values
        act = d.act_ppr.values
        sa = order(d, a).values
        sb = order(d, b).values if b else None
        i, j = np.triu_indices(len(d), 1)
        m = (np.abs(rk[i] - rk[j]) <= CLOSE) & (act[i] != act[j])
        i, j = i[m], j[m]
        truth = np.sign(act[i] - act[j])

        def score(s):
            p = np.sign(s[i] - s[j])
            ok = np.where(p == 0, 0.5, (p == truth).astype(float))
            return np.where(np.isnan(s[i]) | np.isnan(s[j]), np.nan, ok)
        outa.append(score(sa))
        if b:
            outb.append(score(sb))
        cl.append(np.full(len(i), f"{w}-{pos}"))
    if not outa:
        return np.array([]), np.array([]), np.array([])
    return np.concatenate(outa), (np.concatenate(outb) if b else None), np.concatenate(cl)


def spearman_by_group(D, src):
    vals = []
    for (w, pos), d in D.groupby(["week", "pos"]):
        x = order(d, src)
        ok = x.notna()
        if ok.sum() >= 8:
            vals.append(((w, pos), float(x[ok].rank().corr(d.act_ppr[ok].rank())), int(ok.sum())))
    return vals


def metrics(D, src):
    out = {"n": 0}
    p = pred(D, src)
    ok = p.notna()
    if ok.sum():
        e = p[ok] - D.act_ppr[ok]
        out.update(n=int(ok.sum()), mae=round(float(e.abs().mean()), 3), bias=round(float(-e.mean()), 3),
                   rmse=round(float(np.sqrt((e ** 2).mean())), 3), r=round(float(p[ok].corr(D.act_ppr[ok])), 3))
    sp = spearman_by_group(D, src)
    if sp:
        out["rho"] = round(float(np.average([v for _, v, _ in sp], weights=[n for _, _, n in sp])), 3)
        out["nRank"] = int(sum(n for _, _, n in sp))
    ca, _, _ = pairs(D, src)
    ca = ca[~np.isnan(ca)] if len(ca) else ca
    if len(ca):
        out["pairs"] = round(float(ca.mean()) * 100, 1)
        out["nPairs"] = int(len(ca))
    return out


def compare(D, a, b):
    """Paired comparison of source a vs b on rows where both have numbers. Negative mae diff = a better."""
    res = {"a": a, "b": b}
    pa, pb = pred(D, a), pred(D, b)
    ok = pa.notna() & pb.notna()
    if ok.sum() >= 10:
        d = (pa[ok] - D.act_ppr[ok]).abs() - (pb[ok] - D.act_ppr[ok]).abs()
        m, se = cluster_mean(d, D.week[ok].astype(str) + D.team[ok])
        res["mae"] = {"diff": round(m, 3), "se": round(se, 3) if se else None, "n": int(ok.sum()),
                      "a": round(float((pa[ok] - D.act_ppr[ok]).abs().mean()), 3), "b": round(float((pb[ok] - D.act_ppr[ok]).abs().mean()), 3)}
    sa, sb = {k: v for k, v, _ in spearman_by_group(D, a)}, {k: v for k, v, _ in spearman_by_group(D, b)}
    common = sorted(set(sa) & set(sb))
    if common:
        d = np.array([sa[k] - sb[k] for k in common])
        res["rho"] = {"diff": round(float(d.mean()), 3), "se": round(float(d.std(ddof=1) / np.sqrt(len(d))), 3) if len(d) > 1 else None,
                      "n": len(d)}
    ca, cb, cl = pairs(D, a, b)
    if len(ca):
        ok2 = ~np.isnan(ca) & ~np.isnan(cb)
        if ok2.sum() >= 20:
            m, se = cluster_mean((ca - cb)[ok2] * 100, cl[ok2])
            res["pairs"] = {"diff": round(m, 2), "se": round(se, 2) if se else None, "n": int(ok2.sum()),
                            "a": round(float(ca[ok2].mean() * 100), 1), "b": round(float(cb[ok2].mean() * 100), 1)}
    return res


def verdict(c, key, better_low):
    x = c.get(key)
    if not x or x.get("se") is None:
        return "too early"
    z = x["diff"] / x["se"] if x["se"] > 0 else 0
    good = (z < -1.96) if better_low else (z > 1.96)
    bad = (z > 1.96) if better_low else (z < -1.96)
    return "ahead" if good else "behind" if bad else "even (not significant)"


# ----------------------------------------------------------------------------- diagnostics
FLAGS = [
    ("first game back", lambda D: D.back < 0.999),
    ("teammate out: role up 1+ pt", lambda D: D.role_shift >= 1),
    ("teammate back: role down 1+ pt", lambda D: D.role_shift <= -1),
    ("injury tag (Q/limited/DNP)", lambda D: D.inj.fillna("").str.match(r"(Questionable|Doubtful|Limited|DNP)")),
    ("listed out by us but played", lambda D: D.avail == 0),
    ("0-1 games this season", lambda D: D.g26 <= 1),
    ("rookie (no NFL history)", lambda D: (D.g25 == 0) & (D.g24 == 0)),
    ("backup QB (depth 2+)", lambda D: (D.pos == "QB") & (D.dc.fillna(1) >= 2)),
    ("veteran (RB 28+, WR/TE 30+, QB 35+)", lambda D: D.age.fillna(0) >= D.pos.map({"RB": 28, "WR": 30, "TE": 30, "QB": 35})),
    ("team expected 8%+ above its usual score", lambda D: D.env_x.fillna(0) >= 0.08),
    ("team expected 8%+ below its usual score", lambda D: D.env_x.fillna(0) <= -0.08),
    ("favored by 6+", lambda D: D.env_spread.fillna(0) >= 6),
    ("underdog by 6+", lambda D: D.env_spread.fillna(0) <= -6),
    ("we're 3+ pts above FantasyPros final", lambda D: (D.page_ppr - D.fpf_pts) >= 3),
    ("we're 3+ pts below FantasyPros final", lambda D: (D.page_ppr - D.fpf_pts) <= -3),
]


def group_row(name, d):
    r = d.act_ppr - d.page_ppr
    m, se = cluster_mean(r, d.week.astype(str) + d.team) if len(d) else (None, None)
    row = {"group": name, "n": int(len(d)), "resid": round(m, 2) if m is not None else None, "se": round(se, 2) if se else None,
           "mae": round(float(r.abs().mean()), 2) if len(d) else None}
    f = d.dropna(subset=["fpf_pts"])
    if len(f):
        row["fpResid"] = round(float((f.act_ppr - f.fpf_pts).mean()), 2)
        row["maeUs"] = round(float((f.page_ppr - f.act_ppr).abs().mean()), 2)
        row["maeFp"] = round(float((f.fpf_pts - f.act_ppr).abs().mean()), 2)
        row["nFp"] = int(len(f))
    row["flag"] = bool(m is not None and se and abs(m) >= 1.5 and abs(m) / se >= 2.5 and len(d) >= 25)
    return row


def diagnostics(R):
    out = {"byPos": [], "groups": [], "calibration": [], "volume": [], "blend": {}}
    for pos in POS:
        d = R[R.pos == pos]
        row = group_row(pos, d)
        row["flag"] = bool(row["resid"] is not None and row["se"] and abs(row["resid"]) >= 0.75 and abs(row["resid"]) / row["se"] >= 2.5 and len(d) >= 60)
        out["byPos"].append(row)
    for name, f in FLAGS:
        m = f(R).fillna(False).astype(bool)
        if m.sum() >= 5:
            out["groups"].append(group_row(name, R[m]))
    # calibration: actual vs projection, by projection bucket and as a line
    edges = [-1, 5, 10, 15, 20, 99]
    for lo, hi in zip(edges[:-1], edges[1:]):
        d = R[(R.page_ppr > lo) & (R.page_ppr <= hi)]
        if len(d):
            out["calibration"].append({"bucket": f"{max(lo, 0)}–{hi}" if hi < 99 else f"{lo}+", "n": int(len(d)),
                                       "proj": round(float(d.page_ppr.mean()), 2), "act": round(float(d.act_ppr.mean()), 2),
                                       "fp": round(float(d.fpf_pts.mean()), 2) if d.fpf_pts.notna().any() else None})
    slopes = {}
    for key, d in [("all", R)] + [(p, R[R.pos == p]) for p in POS]:
        if len(d) >= 20 and d.page_ppr.std() > 0:
            x, y = d.page_ppr.values, d.act_ppr.values
            b, a0 = np.polyfit(x, y, 1)
            res = y - (a0 + b * x)
            se = np.sqrt((res ** 2).sum() / (len(x) - 2) / ((x - x.mean()) ** 2).sum())
            slopes[key] = {"slope": round(float(b), 3), "se": round(float(se), 3), "n": int(len(x))}
    out["slopes"] = slopes
    # volume vs efficiency: how much of the miss is opportunities (carries + targets / attempts) vs per-play production
    for pos in POS:
        d = R[R.pos == pos]
        if not len(d):
            continue
        po = (d.o_att if pos == "QB" else d.o_car + d.o_tgt).astype(float)
        ao = (d.a_att if pos == "QB" else d.a_car + d.a_tgt).astype(float)
        ppo = np.where(po > 0.1, d.model_ppr / po.clip(lower=0.1), 0.0)
        vol = (ao - po) * ppo
        tot = d.act_ppr - d.model_ppr
        eff = tot - vol
        oe, ose = cluster_mean(ao - po, d.week.astype(str) + d.team)
        row = {"pos": pos, "n": int(len(d)), "oppBias": round(oe, 2), "oppSe": round(ose, 2) if ose else None,
               "volMae": round(float(np.abs(vol).mean()), 2), "effMae": round(float(np.abs(eff).mean()), 2),
               "volBias": round(float(vol.mean()), 2), "effBias": round(float(eff.mean()), 2)}
        if pos != "QB":
            row["tgtBias"] = round(float((d.a_tgt - d.o_tgt).mean()), 2)
            row["carBias"] = round(float((d.a_car - d.o_car).mean()), 2)
        out["volume"].append(row)
    # blending with FantasyPros: the best mix weight on their number, Tuesday (fair) and final (ceiling)
    for src, col in (("fp_early", "fpe_pts"), ("fp_final", "fpf_pts")):
        d = R.dropna(subset=[col])
        if len(d) >= 50:
            ws = np.round(np.arange(0, 1.0001, 0.05), 2)
            maes = [float(((1 - w) * d.page_ppr + w * d[col] - d.act_ppr).abs().mean()) for w in ws]
            k = int(np.argmin(maes))
            out["blend"][src] = {"best": float(ws[k]), "maeBest": round(maes[k], 3), "maePage": round(maes[0], 3),
                                 "maeFp": round(maes[-1], 3), "n": int(len(d)), "curve": [round(x, 3) for x in maes]}
    # does the expert blend on the page help? page vs model
    return out


def candidates(diag, cum, weeks_final):
    """Model changes worth testing, from cumulative evidence. Proposals only: test them in backtest_core.py
    (2024 train / 2025-26 holdout) before changing the engine."""
    c = []
    for r in diag["byPos"]:
        if r["flag"]:
            c.append({"area": f"{r['group']} level", "evidence": f"we're {'under' if r['resid'] > 0 else 'over'} by {abs(r['resid']):.2f} pts/player (±{r['se']:.2f}, n={r['n']})",
                      "idea": f"check {r['group']} team-pool volume and efficiency shrink targets"})
    for r in diag["groups"]:
        if r["flag"]:
            c.append({"area": r["group"], "evidence": f"actual − projection {r['resid']:+.2f} (±{r['se']:.2f}, n={r['n']}); FantasyPros {r.get('fpResid', float('nan')):+.2f}",
                      "idea": "situation-specific adjustment"})
    s = diag["slopes"].get("all")
    if s and abs(s["slope"] - 1) >= 0.1 and abs(s["slope"] - 1) / max(s["se"], 1e-9) >= 2.5:
        c.append({"area": "calibration", "evidence": f"actual rises {s['slope']:.2f} pts per projected pt (±{s['se']:.2f})",
                  "idea": "projections are too spread out; shrink toward the positional mean" if s["slope"] < 1 else "projections are too compressed"})
    for r in diag["volume"]:
        if r["oppSe"] and abs(r["oppBias"]) >= 0.75 and abs(r["oppBias"]) / r["oppSe"] >= 2.5 and r["n"] >= 60:
            c.append({"area": f"{r['pos']} opportunities", "evidence": f"actual − projected {'attempts' if r['pos'] == 'QB' else 'carries+targets'} {r['oppBias']:+.2f} (±{r['oppSe']:.2f})",
                      "idea": "team pool size or share fit"})
    b = diag["blend"].get("fp_early")
    if b and weeks_final >= 3 and b["best"] >= 0.15 and b["maePage"] - b["maeBest"] >= 0.05:
        c.append({"area": "weekly expert weight", "evidence": f"mixing {b['best']:.0%} of FantasyPros' Tuesday points cuts MAE {b['maePage']:.2f} → {b['maeBest']:.2f} (n={b['n']})",
                  "idea": "raise weeklyExpert, or use FantasyPros points instead of ranks"})
    mp = cum.get("model_vs_page", {}).get("mae")
    if mp and mp.get("se") and mp["diff"] / mp["se"] < -2.5:
        c.append({"area": "expert blend", "evidence": f"the usage model alone beats the page by {-mp['diff']:.2f} MAE", "idea": "lower expertWeight / weeklyExpert"})
    return c


# ----------------------------------------------------------------------------- grade command
def grade(a):
    games = pd.read_csv("games.csv", low_memory=False)
    paths = sorted(glob.glob("freeze/*.json"))
    if not paths:
        sys.exit("no frozen weeks in freeze/")
    os.makedirs("graded", exist_ok=True)
    todo = []
    for p in paths:
        meta, _ = load_freeze(p)
        S, W = int(meta["season"]), int(meta["week"])
        gp = f"graded/{S}-w{W:02d}.csv"
        if a.weeks and W not in a.weeks:
            continue
        if os.path.exists(gp) and not a.regrade:
            st = pd.read_csv(gp, nrows=1).get("status")
            if st is not None and st.iloc[0] == "final":
                continue
        _, F = load_freeze(p)
        gw = games[(games.season == S) & (games.week == W) & (games.game_type == "REG") & games.home_score.notna()]
        if not (set(gw.home_team) | set(gw.away_team)) & set(F.team):
            continue   # none of the frozen players' games has finished yet
        todo.append((p, S, W))
    hist = None
    if todo:
        S = todo[0][1]
        starts = week_starts(games, S)
        last_kick = {W: max(kickoffs(games, S, W).values()) for _, _, W in todo}
        try:
            hist = fp_history(S, starts, [W for _, _, W in todo], last_kick)
        except Exception as e:  # history is a bonus; the freeze kept FantasyPros' Tuesday numbers
            print("FantasyPros history unavailable:", e)
    infos = json.load(open("data/scorecard.json")).get("weeks", []) if os.path.exists("data/scorecard.json") else []
    infos = {(i["season"], i["week"]): i for i in infos}
    for p, S, W in todo:
        F, info = grade_week(p, games, hist)
        F["status"] = info["status"]
        F.to_csv(f"graded/{S}-w{W:02d}.csv", index=False)
        infos[(S, W)] = info
        print(f"graded week {W}: {info['status']} ({info['gamesDone']}/{info['games']} games), {int(F.played.sum())} players played")
    G = [pd.read_csv(f, low_memory=False) for f in sorted(glob.glob("graded/*.csv"))]
    if not G:
        print("nothing graded yet")
        write_outputs({"updated": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), "labels": LABEL, "weeks": [], "pending": pending(paths)})
        return
    D = pd.concat(G, ignore_index=True)
    D = D[(D.played == 1) & (D.game_done == 1)].copy()
    if not len(D):
        write_outputs({"updated": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), "labels": LABEL, "weeks": [], "pending": pending(paths)})
        return
    D["rel"] = relevant(D)
    R = D[D.rel]
    weeks = []
    for (S, W), d in R.groupby(["season", "week"]):
        i = dict(infos.get((S, W), {"season": int(S), "week": int(W)}))
        i["metrics"] = {s: metrics(d, s) for s in SOURCES}
        i["vsFinal"] = compare(d, "page", "fp_final")
        i["vsEarly"] = compare(d, "page", "fp_early")
        i["nRel"], i["nAll"] = int(len(d)), int((D.week == W).sum())
        weeks.append(i)
    nfinal = sum(1 for w in weeks if w.get("status") == "final")
    cum = {"rel": {s: metrics(R, s) for s in SOURCES}, "all": {s: metrics(D, s) for s in SOURCES},
           "byPos": {pos: {s: metrics(R[R.pos == pos], s) for s in SOURCES} for pos in POS},
           "page_vs_final": compare(R, "page", "fp_final"), "page_vs_early": compare(R, "page", "fp_early"),
           "model_vs_page": compare(R, "model", "page"), "early_vs_final": compare(R, "fp_early", "fp_final")}
    for k in ("page_vs_final", "page_vs_early"):
        cum[k]["verdict"] = {"mae": verdict(cum[k], "mae", True), "rho": verdict(cum[k], "rho", False), "pairs": verdict(cum[k], "pairs", False)}
    diag = diagnostics(R)
    cand = candidates(diag, cum, nfinal)
    last = R[R.week == R.week.max()].copy()
    last["err"] = last.act_ppr - last.page_ppr
    misses = []
    for r in last.reindex(last.err.abs().sort_values(ascending=False).index).head(15).itertuples():
        notes = [n for n, f in FLAGS[:9] if bool(f(last.loc[[r.Index]]).fillna(False).iloc[0])]
        misses.append({"name": r.name, "pos": r.pos, "team": r.team, "page": round(r.page_ppr, 1), "act": round(r.act_ppr, 1),
                       "fp": None if pd.isna(r.fpf_pts) else round(r.fpf_pts, 1),
                       "opp": f"{(r.o_att if r.pos == 'QB' else r.o_car + r.o_tgt):.1f} → {(r.a_att if r.pos == 'QB' else r.a_car + r.a_tgt):.0f}",
                       "notes": notes})
    goal = goal_status(cum, nfinal)
    out = {"updated": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"), "season": int(R.season.max()), "labels": LABEL,
           "relN": REL_N, "close": CLOSE, "goal": goal, "weeks": weeks, "cumulative": cum, "diagnostics": diag,
           "candidates": cand, "misses": {"week": int(last.week.max()), "rows": misses}, "pending": pending(paths)}
    write_outputs(out)


def goal_status(cum, nfinal):
    """'Considerably more accurate': beat FantasyPros' final consensus (all the week's news) by 3%+ in
    MAE with 95% confidence, and make more right start/sit calls, over at least 6 graded weeks."""
    c = cum["page_vs_final"]
    m, p = c.get("mae"), c.get("pairs")
    st = {"weeks": nfinal, "needWeeks": 6, "maeTargetPct": 3.0}
    if m:
        st["maeGapPct"] = round(-100 * m["diff"] / m["b"], 1) if m["b"] else None
        st["maeSig"] = bool(m.get("se") and m["diff"] / m["se"] < -1.96)
    if p:
        st["pairsGap"] = p["diff"]
        st["pairsSig"] = bool(p.get("se") and p["diff"] / p["se"] > 1.96)
    met = nfinal >= 6 and st.get("maeSig") and (st.get("maeGapPct") or 0) >= 3 and (p is None or p["diff"] > 0)
    st["met"] = bool(met)
    return st


def pending(paths):
    """Frozen weeks not fully graded yet, with a preview of what was frozen (top players per position)."""
    out = []
    for p in paths:
        meta, F = load_freeze(p)
        gp = f"graded/{meta['season']}-w{int(meta['week']):02d}.csv"
        st = pd.read_csv(gp, nrows=1).status.iloc[0] if os.path.exists(gp) else None
        if st == "final":
            continue
        top = {}
        for pos in POS:
            d = F[(F.pos == pos) & (F.avail == 1)].astype({"page_ppr": float}).nlargest(8, "page_ppr")
            top[pos] = [{"name": r.name, "team": r.team, "page": round(float(r.page_ppr), 1),
                         "fp": None if r.fp_pts is None or pd.isna(r.fp_pts) else round(float(r.fp_pts), 1)} for r in d.itertuples()]
        out.append({"season": meta["season"], "week": meta["week"], "frozenAt": meta.get("frozenAt"), "n": int(len(F)),
                    "nAvail": int((F.avail == 1).sum()), "pageBuilt": meta.get("builtAt"), "note": meta.get("note", ""),
                    "status": st or "waiting", "top": top})
    return out


def write_outputs(out):
    os.makedirs("data", exist_ok=True)
    json.dump(out, open("data/scorecard.json", "w"), separators=(",", ":"), default=lambda x: None if pd.isna(x) else x)
    open("scorecard.md", "w").write(markdown(out))
    print(open("scorecard.md").read())


def fmt(x, nd=2):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def markdown(o):
    L = ["# Fantasy Trader — projection scorecard", "", f"Updated {o['updated']}."]
    if o.get("pending"):
        L.append("Frozen, waiting for games: " + ", ".join(f"week {p['week']} ({p['n']} players, frozen {p['frozenAt']})" for p in o["pending"]) + ".")
    if not o.get("weeks"):
        return "\n".join(L + ["", "No graded weeks yet."]) + "\n"
    c = o["cumulative"]
    g = o["goal"]
    L += ["", "## Where we stand", "",
          f"Graded weeks: {g['weeks']} final. Goal: beat FantasyPros' final consensus by 3%+ in average miss (95% confidence) "
          f"and make more right start/sit calls, over 6+ weeks — {'MET' if g['met'] else 'not met yet'}."]
    for key, name in (("page_vs_final", "FantasyPros final (all the week's news)"), ("page_vs_early", "FantasyPros Tuesday (same information as us)")):
        x = c[key]
        parts = []
        if x.get("mae"):
            m = x["mae"]
            parts.append(f"average miss {m['a']:.2f} vs {m['b']:.2f} pts ({m['diff']:+.2f} ± {fmt(m.get('se'))}, n={m['n']}) → {x['verdict']['mae']}")
        if x.get("pairs"):
            p = x["pairs"]
            parts.append(f"start/sit calls {p['a']:.1f}% vs {p['b']:.1f}% right ({p['diff']:+.1f} ± {fmt(p.get('se'), 1)}) → {x['verdict']['pairs']}")
        if x.get("rho"):
            r = x["rho"]
            parts.append(f"rank correlation {r['diff']:+.3f} ± {fmt(r.get('se'), 3)} → {x['verdict']['rho']}")
        L.append(f"- vs {name}: " + "; ".join(parts))
    L += ["", "## Cumulative (fantasy-relevant players who played, PPR)", "",
          "| Source | n | Avg miss | Actual − proj | RMSE | r | Rank corr | Start/sit % |", "|---|---|---|---|---|---|---|---|"]
    for s in SOURCES:
        m = c["rel"][s]
        L.append(f"| {o['labels'][s]} | {m.get('n', 0)} | {fmt(m.get('mae'))} | {fmt(m.get('bias'))} | {fmt(m.get('rmse'))} | {fmt(m.get('r'))} | {fmt(m.get('rho'), 3)} | {fmt(m.get('pairs'), 1)} |")
    L += ["", "## By week", "", "| Week | Status | Ours | FP Tue | FP final | Start/sit ours vs FP final |", "|---|---|---|---|---|---|"]
    for w in o["weeks"]:
        M = w["metrics"]
        p = w["vsFinal"].get("pairs") or {}
        L.append(f"| {w['week']} | {w.get('status', '')} | {fmt(M['page'].get('mae'))} | {fmt(M['fp_early'].get('mae'))} | {fmt(M['fp_final'].get('mae'))} | {fmt(p.get('a'), 1)} vs {fmt(p.get('b'), 1)} |")
    d = o["diagnostics"]
    L += ["", "## Diagnostics (actual − our projection; + = we projected too low)", ""]
    for r in d["byPos"] + d["groups"]:
        L.append(f"- {r['group']}: {fmt(r['resid'])} ± {fmt(r['se'])} (n={r['n']}; our miss {fmt(r.get('maeUs'))} vs FP {fmt(r.get('maeFp'))}){'  ← flag' if r['flag'] else ''}")
    for r in d["volume"]:
        L.append(f"- {r['pos']} opportunities: actual − projected {fmt(r['oppBias'])} ± {fmt(r['oppSe'])}; miss from volume {fmt(r['volMae'])} vs per-play {fmt(r['effMae'])} pts")
    if d["slopes"].get("all"):
        s = d["slopes"]["all"]
        L.append(f"- calibration: actual rises {s['slope']:.2f} per projected point (± {s['se']:.2f}; 1.00 = calibrated)")
    for k, b in d["blend"].items():
        L.append(f"- best mix with {o['labels'][k]}: {b['best']:.0%} of theirs → miss {b['maeBest']:.2f} (ours alone {b['maePage']:.2f}, theirs {b['maeFp']:.2f})")
    L += ["", "## Model changes worth testing", ""]
    L += [f"- **{x['area']}**: {x['evidence']} — {x['idea']}" for x in o["candidates"]] or ["- none yet: not enough evidence (needs several graded weeks)"]
    L += ["", f"## Biggest misses, week {o['misses']['week']}", "", "| Player | Ours | FP final | Actual | Opps proj → actual | Notes |", "|---|---|---|---|---|---|"]
    for m in o["misses"]["rows"]:
        L.append(f"| {m['name']} ({m['pos']} {m['team']}) | {m['page']} | {fmt(m['fp'], 1)} | {m['act']} | {m['opp']} | {', '.join(m['notes'])} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--page", required=True)
    f.add_argument("--version", default="")
    f.add_argument("--now", default="")
    f.add_argument("--note", default="")
    f.add_argument("--force", action="store_true")
    g = sub.add_parser("grade")
    g.add_argument("--weeks", type=lambda s: [int(x) for x in s.split(",")], default=None)
    g.add_argument("--regrade", action="store_true")
    a = ap.parse_args()
    freeze(a) if a.cmd == "freeze" else grade(a)
