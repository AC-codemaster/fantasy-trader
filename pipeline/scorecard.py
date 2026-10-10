"""Fantasy Trader projection scorecard: freeze each week's projections, then grade them.

    python3 pipeline/scorecard.py freeze --page fantasy-trader.html [--cbs cbs_injuries.tsv] [--version V] [--note TEXT]
    python3 pipeline/scorecard.py grade [--weeks 5,6] [--regrade]

Run from the weekly work folder: `build_db.py --fetch` leaves the nflverse and DynastyProcess inputs there
(s{yy}.csv, snaps{yy}.csv, games.csv, db_playerids.csv, fp_latest_weekly.csv). Everything the scorecard
keeps lives in the repo's data/ folder (or --data):

  freeze/{S}-w{WW}.json        this week's projections exactly as the page showed them; written once, never edited
  inputs/{S}/w{WW}/            what the page ran on: db.json, injury_news.json, cbs_injuries.tsv, params.json,
                               engine.js. Lets any later engine or parameter set be replayed on the same week.
  ros/{S}-w{WW}.json           each player's projection for every remaining week (rest of season), from the freeze
  graded/{S}-w{WW}.csv         one row per frozen player: projections, hindsight projections, result, FantasyPros
  scorecard/scorecard.json     metrics, diagnostics, candidate changes (the scorecard page reads it)
  scorecard/scorecard.md       the same in words

Sources graded:
  page      what the Players tab showed on Tuesday (usage model + expert blends), Tuesday's information
  model     the usage model alone
  hind      the page's model rerun on the same inputs with the week's actual availability (who played):
            separates model error from news that broke after Tuesday; the basis for model diagnostics
  fp_early  FantasyPros weekly consensus, first snapshot of the week (same information as our freeze)
  fp_final  FantasyPros, last snapshot before each player's kickoff (all the week's news)
Goals: the model is judged against fp_early (same information); the product against fp_final.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from io import StringIO

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from ftlib import engine_source, load_params_file, values  # noqa: E402

RUNNER = os.path.join(ROOT, "tools", "engine_runner.js")
DATA = os.path.join(ROOT, "data")
POS = ["QB", "RB", "WR", "TE"]
COMP = ["py", "ptd", "int", "ry", "rtd", "rec", "recy", "rectd", "fl", "two"]
SCORE = {"ppr": [0.04, 4, -2, 0.1, 6, 1.0, 0.1, 6, -2, 2], "half": [0.04, 4, -2, 0.1, 6, 0.5, 0.1, 6, -2, 2],
         "std": [0.04, 4, -2, 0.1, 6, 0.0, 0.1, 6, -2, 2]}
REL_N = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}
CLOSE = 12           # start/sit calls: same-position pairs within this many consensus ranks of each other
DP_REPO = "https://github.com/dynastyprocess/data"
DP_HIST = "dp-history"
FP_FILE = "files/fp_latest_weekly.csv"
SOURCES = ["page", "model", "hind", "fp_early", "fp_final"]
LABEL = {"page": "Our page", "model": "Our usage model (no expert blend)", "hind": "Our page with hindsight availability",
         "fp_early": "FantasyPros, Tuesday", "fp_final": "FantasyPros, final"}
GOAL_WEEKS, GOAL_PCT = 6, 3.0


def now_utc():
    return datetime.now(timezone.utc)


def stamp():
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def yy(season):
    return str(season)[2:]


def dpath(*parts):
    return os.path.join(DATA, *parts)


def tag(S, W):
    return f"{S}-w{int(W):02d}"


# ----------------------------------------------------------------------------- engine
def engine_from_page(html):
    """(engine source, db.json text, injury_news text) cut out of a published page."""
    a = html.index("/* Fantasy Trader valuation engine")
    b = html.index("module.exports = {", a)
    eng = html[a:html.index("\n", b) + 1].replace("<\\/script", "</script")
    unesc = lambda t: t.replace("<\\/", "</")  # noqa: E731
    db = re.search(r'<script type="application/json" id="db">(.*?)</script>', html, re.S)
    inj = re.search(r'<script type="application/json" id="injnews">(.*?)</script>', html, re.S)
    return eng, unesc(db.group(1)), unesc(inj.group(1)) if inj else None


def run_engine(engine_src, db_path, avail=None, lite=False):
    """Run the engine headlessly (tools/engine_runner.js). Returns (meta, players DataFrame)."""
    with tempfile.TemporaryDirectory() as td:
        ep = os.path.join(td, "engine.js")
        open(ep, "w").write(engine_src)
        cmd = ["node", RUNNER, "--engine", ep, "--db", db_path]
        if avail is not None:
            ap_ = os.path.join(td, "avail.json")
            json.dump(avail, open(ap_, "w"))
            cmd += ["--avail", ap_]
        if lite:
            cmd.append("--lite")
        res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("engine run failed:\n" + res.stderr[-2000:])
    out = json.loads(res.stdout)
    return out["meta"], pd.DataFrame(out["players"])


def week_engine(S, W, params_vals=None, engine_src=None):
    """Engine source for replaying an archived week: the archived engine unless overridden, with the
    archived parameters unless params_vals is given."""
    d = dpath("inputs", str(S), f"w{int(W):02d}")
    src = engine_src if engine_src is not None else (open(os.path.join(d, "engine.js")).read()
                                                     if os.path.exists(os.path.join(d, "engine.js")) else None)
    if params_vals is None:
        pp = os.path.join(d, "params.json")
        params_vals = values(load_params_file(pp)) if os.path.exists(pp) else None
    return engine_source(params_vals, src)


def archived_weeks():
    out = []
    for p in sorted(glob.glob(dpath("inputs", "*", "w*", "db.json"))):
        S, w = p.split(os.sep)[-3], p.split(os.sep)[-2]
        out.append((int(S), int(w[1:])))
    return out


# ----------------------------------------------------------------------------- schedule helpers
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


def done_teams(games, season, week, stat_teams):
    g = games[(games.season == season) & (games.week == week) & (games.game_type == "REG")]
    done = set()
    for r in g.itertuples():
        if pd.notna(r.home_score) and r.home_team in stat_teams and r.away_team in stat_teams:
            done |= {r.home_team, r.away_team}
    return done, set(g.home_team) | set(g.away_team)


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
    html = open(a.page).read()
    eng, db_text, inj_text = engine_from_page(html)
    with tempfile.TemporaryDirectory() as td:
        dbp = os.path.join(td, "db.json")
        open(dbp, "w").write(db_text)
        meta, P = run_engine(eng, dbp)
    S, W = int(meta["season"]), int(meta["week"])
    path = dpath("freeze", tag(S, W) + ".json")
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
    # rest-of-season vectors for every player (byes and started games included: later weeks still count)
    ros = {"season": S, "week": W, "weeks": meta["weeks"], "frozenAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "players": P[["id", "name", "pos", "team", "er", "page_wk", "model_wk", "avail_wk"]].to_dict("records")}
    P = P[~bye & ~started].drop(columns=["page_wk", "model_wk", "avail_wk"]).copy()
    P["fp_ecr"], P["fp_pts"], fp_date = np.nan, np.nan, None
    if os.path.exists("fp_latest_weekly.csv"):
        fp = fp_frame(pd.read_csv("fp_latest_weekly.csv", low_memory=False), fp_ids(), week_starts(games, S))
        fp = fp[fp.week == W].drop_duplicates("gsis").set_index("gsis")
        if len(fp):
            P["fp_ecr"] = P.id.map(fp.ecr)
            P["fp_pts"] = P.id.map(fp.r2p_pts)
            fp_date = str(fp.scrape_date.iloc[0])
    commit = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    meta.update(frozenAt=now.strftime("%Y-%m-%dT%H:%M:%SZ"), pageVersion=a.version, commit=commit, note=a.note or "",
                fpScrape=fp_date, excludedStarted=sorted({t for t, k in kick.items() if k <= now}), n=len(P))
    # archive the inputs: everything needed to replay this week with any later engine or parameters
    ind = dpath("inputs", str(S), f"w{W:02d}")
    os.makedirs(ind, exist_ok=True)
    keep = {"db.json": db_text, "engine.js": eng}
    if inj_text:
        keep["injury_news.json"] = inj_text
    for name, text in keep.items():
        fp_ = os.path.join(ind, name)
        if not os.path.exists(fp_):
            open(fp_, "w").write(text)
    if a.cbs and os.path.exists(a.cbs) and not os.path.exists(os.path.join(ind, "cbs_injuries.tsv")):
        shutil.copy(a.cbs, os.path.join(ind, "cbs_injuries.tsv"))
    pp = os.path.join(ind, "params.json")
    if not os.path.exists(pp):
        pj = load_params_file()
        pj["engine_params_in_page"] = meta.get("params")
        json.dump(pj, open(pp, "w"), indent=1)
    os.makedirs(dpath("freeze"), exist_ok=True)
    os.makedirs(dpath("ros"), exist_ok=True)
    cols = list(P.columns)
    rows = P[cols].astype(object).where(P[cols].notna(), None).values.tolist()
    json.dump({"meta": meta, "cols": cols, "rows": rows}, open(path, "w"), separators=(",", ":"))
    json.dump(ros, open(dpath("ros", tag(S, W) + ".json"), "w"), separators=(",", ":"))
    av = P[P.avail == 1]
    print(f"froze {path}: {len(P)} players ({len(av)} expected to play), week {W}, page data built {meta['builtAt']}")
    print(f"  inputs archived in {ind}")
    if meta["excludedStarted"]:
        print("  left out (game already started):", ", ".join(meta["excludedStarted"]))
    print(f"  FantasyPros at freeze: {P.fp_ecr.notna().sum()} players matched (scrape {fp_date})")
    for pos in POS:
        top = av[av.pos == pos].nlargest(3, "page_ppr")
        print(f"  {pos}: " + ", ".join(f"{r.name} {r.page_ppr:.1f}" for r in top.itertuples()))


def load_freeze(path):
    j = json.load(open(path))
    return j["meta"], pd.DataFrame(j["rows"], columns=j["cols"])


def ros_vectors(S, W):
    """Rest-of-season vectors for a frozen week: from the freeze, else rebuilt by replaying the archived
    inputs with the archived engine and parameters (same numbers the page showed), then saved."""
    p = dpath("ros", tag(S, W) + ".json")
    if os.path.exists(p):
        return json.load(open(p))
    dbp = dpath("inputs", str(S), f"w{int(W):02d}", "db.json")
    if not os.path.exists(dbp):
        return None
    meta, P = run_engine(week_engine(S, W), dbp, lite=True)
    ros = {"season": S, "week": W, "weeks": meta["weeks"], "rebuilt": stamp(),
           "players": P[["id", "name", "pos", "team", "er", "page_wk", "model_wk", "avail_wk"]].to_dict("records")}
    os.makedirs(dpath("ros"), exist_ok=True)
    json.dump(ros, open(p, "w"), separators=(",", ":"))
    return ros


# ----------------------------------------------------------------------------- FantasyPros history
def fp_history(season, starts, need_weeks, last_kick):
    """{week: list of (commit_ts, DataFrame)} from DynastyProcess snapshots in git history."""
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
_STATS, _SNAPS = {}, {}


def season_stats(season):
    if season not in _STATS:
        s = pd.read_csv(f"s{yy(season)}.csv", low_memory=False)
        s = s[s.season_type == "REG"].copy()
        s["fl"] = s[["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]].fillna(0).sum(axis=1)
        s["two"] = s[["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"]].fillna(0).sum(axis=1)
        _STATS[season] = s
    return _STATS[season]


def season_snaps(season):
    if season not in _SNAPS:
        f = f"snaps{yy(season)}.csv"
        if os.path.exists(f):
            sn = pd.read_csv(f, low_memory=False)
            sn = sn[sn.offense_snaps > 0]
            ids = pd.read_csv("db_playerids.csv", low_memory=False, usecols=["pfr_id", "gsis_id"]).dropna()
            pfr = ids.drop_duplicates("pfr_id").set_index("pfr_id").gsis_id.to_dict()
            _SNAPS[season] = sn.assign(gsis=sn.pfr_player_id.map(pfr)).dropna(subset=["gsis"])
        else:
            _SNAPS[season] = pd.DataFrame(columns=["week", "gsis"])
    return _SNAPS[season]


def actuals(season, week):
    s = season_stats(season)
    s = s[s.week == week]
    src = ["passing_yards", "passing_tds", "passing_interceptions", "rushing_yards", "rushing_tds", "receptions",
           "receiving_yards", "receiving_tds", "fl", "two"]
    g = s.groupby("player_id")
    A = g[src + ["carries", "targets", "attempts"]].sum()
    A.columns = ["a_" + c for c in COMP] + ["a_car", "a_tgt", "a_att"]
    A["a_team"] = g.team.last()
    played = set(A.index)
    sn = season_snaps(season)
    played |= set(sn[sn.week == week].gsis)
    return A, played, set(s.team)


def comp_pts(df, prefix, kind="ppr"):
    w = SCORE[kind]
    return sum(df[prefix + c].fillna(0) * w[i] for i, c in enumerate(COMP))


# ----------------------------------------------------------------------------- grading one week
def grade_week(path, games, hist):
    meta, F = load_freeze(path)
    S, W = int(meta["season"]), int(meta["week"])
    A, played, stat_teams = actuals(S, W)
    done, all_teams = done_teams(games, S, W, stat_teams)
    status = "final" if all_teams <= done else "partial"
    F = F.copy()
    F["game_done"] = F.team.isin(done).astype(int)
    F = F.join(A, on="id")
    F["played"] = F.id.isin(played).astype(int) * F.game_done
    for c in ["a_" + c for c in COMP] + ["a_car", "a_tgt", "a_att"]:
        F[c] = F[c].fillna(0.0)
    for k in SCORE:
        F[f"act_{k}"] = comp_pts(F, "a_", k)
    # hindsight: the same model on the same inputs, told who actually played
    F["hind_ppr"], F["hind_model_ppr"] = np.nan, np.nan
    for c in ("hind_o_car", "hind_o_tgt", "hind_o_att"):
        F[c] = np.nan
    dbp = dpath("inputs", str(S), f"w{W:02d}", "db.json")
    if os.path.exists(dbp) and done:
        db_ids = {p["id"] for p in json.load(open(dbp))["players"]}
        avail = {"week": W, "played": sorted(played & db_ids), "teams": sorted(done)}
        _, H = run_engine(week_engine(S, W), dbp, avail=avail, lite=True)
        H = H.set_index("id")
        F["hind_ppr"] = F.id.map(H.page_ppr)
        F["hind_model_ppr"] = F.id.map(H.model_ppr)
        F["hind_o_car"], F["hind_o_tgt"], F["hind_o_att"] = F.id.map(H.o_car), F.id.map(H.o_tgt), F.id.map(H.o_att)
    early, final, t0 = fp_views(hist.get(W, [])) if hist is not None else (None, None, None)
    if early is None and F.fp_ecr.notna().any():   # no history: fall back to the numbers saved at the freeze
        early = F.dropna(subset=["fp_ecr"]).set_index("id")[["fp_ecr", "fp_pts"]].rename(columns={"fp_ecr": "ecr", "fp_pts": "r2p_pts"})
        t0 = meta.get("fpScrape")
    F["fpe_ecr"] = F.id.map(early.ecr) if early is not None else np.nan
    F["fpe_pts"] = F.id.map(early.r2p_pts) if early is not None else np.nan
    F["fpf_ecr"] = F.id.map(final.ecr) if final is not None and len(final) else np.nan
    F["fpf_pts"] = F.id.map(final.r2p_pts) if final is not None and len(final) else np.nan
    F["season"], F["week"] = S, W
    F["w0"], F["we0"] = meta.get("expertWeight"), meta.get("weeklyExpert")
    info = {"week": W, "season": S, "status": status, "frozenAt": meta.get("frozenAt"), "pageBuilt": meta.get("builtAt"),
            "commit": meta.get("commit"), "note": meta.get("note", ""), "fpEarlyAt": t0, "gamesDone": len(done) // 2,
            "games": len(all_teams) // 2, "excludedStarted": meta.get("excludedStarted", []),
            "hindsight": bool(F.hind_ppr.notna().any())}
    return F, info


# ----------------------------------------------------------------------------- metrics (season-aware)
def add_sw(D):
    D = D.copy()
    D["sw"] = D.season.astype(int).astype(str) + "-" + D.week.astype(int).map(lambda w: f"{w:02d}")
    D["cl"] = D.sw + "-" + D.team.astype(str)
    return D


def relevant(D):
    """Fantasy-relevant rows: top N at the position by FantasyPros final rank or by our projection."""
    keep = pd.Series(False, index=D.index)
    for (sw, pos), d in D.groupby(["sw", "pos"]):
        n = REL_N[pos]
        a = d[d.avail == 1].nlargest(n, "page_ppr").index
        b = d.dropna(subset=["fpf_ecr"]).nsmallest(n, "fpf_ecr").index
        keep.loc[a.union(b)] = True
    return keep


PRED_COL = {"page": "page_ppr", "model": "model_ppr", "hind": "hind_ppr", "fp_early": "fpe_pts", "fp_final": "fpf_pts"}
ORDER_COL = {"page": ("page_ppr", 1), "model": ("model_ppr", 1), "hind": ("hind_ppr", 1), "fp_early": ("fpe_ecr", -1), "fp_final": ("fpf_ecr", -1)}


def pred(D, src):
    """Point projection for a source."""
    return D[PRED_COL[src]].astype(float)


def order(D, src):
    """Ranking score (higher = better) for a source."""
    c, sgn = ORDER_COL[src]
    return sgn * D[c].astype(float)


def cluster_mean(d, cl):
    """Mean and cluster-robust standard error of d (clusters = team-weeks or position-weeks)."""
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
    for (sw, pos), d in D.groupby(["sw", "pos"]):
        d = d.dropna(subset=["fpf_ecr"])
        if len(d) < 2:
            continue
        rk = d.fpf_ecr.rank(method="first").values
        act = d.act_ppr.values
        sa = order(d, a).values.astype(float)
        sb = order(d, b).values.astype(float) if b else None
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
        cl.append(np.full(len(i), f"{sw}-{pos}"))
    if not outa:
        return np.array([]), np.array([]), np.array([])
    return np.concatenate(outa), (np.concatenate(outb) if b else None), np.concatenate(cl)


def spearman_by_group(D, src):
    vals = []
    for (sw, pos), d in D.groupby(["sw", "pos"]):
        x = order(d, src)
        ok = x.notna()
        if ok.sum() >= 8:
            vals.append(((sw, pos), float(x[ok].rank().corr(d.act_ppr[ok].rank())), int(ok.sum())))
    return vals


def metrics(D, src):
    out = {"n": 0}
    p = pred(D, src)
    ok = p.notna()
    if ok.sum():
        e = p[ok] - D.act_ppr[ok]
        out.update(n=int(ok.sum()), mae=round(float(e.abs().mean()), 3), bias=round(float(-e.mean()), 3),
                   rmse=round(float(np.sqrt((e ** 2).mean())), 3), r=round(float(p[ok].corr(D.act_ppr[ok])), 3) if ok.sum() > 2 else None)
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
        m, se = cluster_mean(d, D.cl[ok])
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
# which tunable parameters (params/params.json) could explain a lean, for the improvement loop
PARAM_HINTS = {
    "QB level": ["K_ypa", "K_ptd", "team_prior", "low_target"],
    "RB level": ["team_prior", "prior_games", "K_ypc", "K_rtd"],
    "WR level": ["prior_games", "K_ypt", "K_rectd", "decay"],
    "TE level": ["prior_games", "K_ypt", "K_rectd"],
    "first game back": ["ret_disc"],
    "teammate out: role up 1+ pt": ["damp"],
    "teammate back: role down 1+ pt": ["damp", "ret_disc"],
    "0-1 games this season": ["prior_games", "prior_moved"],
    "rookie (no NFL history)": ["low_target", "prior_games"],
    "backup QB (depth 2+)": ["low_target", "K_ypa", "K_ptd"],
    "veteran (RB 28+, WR/TE 30+, QB 35+)": ["vet_prior"],
    "team expected 8%+ above its usual score": ["env_scale"],
    "team expected 8%+ below its usual score": ["env_scale"],
    "favored by 6+": ["env_scale"],
    "underdog by 6+": ["env_scale"],
    "calibration": ["K_ypa", "K_ptd", "K_ypc", "K_rtd", "K_ypt", "K_rectd", "w1", "w2"],
    "QB opportunities": ["team_prior", "decay"],
    "RB opportunities": ["team_prior", "decay", "damp", "prior_games"],
    "WR opportunities": ["team_prior", "decay", "prior_games"],
    "TE opportunities": ["team_prior", "decay", "prior_games"],
    "expert weights": ["expertWeight", "weeklyExpert"],
}


def group_row(name, d, col):
    r = d.act_ppr - d[col]
    m, se = cluster_mean(r, d.cl) if len(d) else (None, None)
    row = {"group": name, "n": int(len(d)), "resid": round(m, 2) if m is not None else None, "se": round(se, 2) if se else None,
           "mae": round(float(r.abs().mean()), 2) if len(d) else None}
    f = d.dropna(subset=["fpf_pts"])
    if len(f):
        row["fpResid"] = round(float((f.act_ppr - f.fpf_pts).mean()), 2)
        row["maeUs"] = round(float((f[col] - f.act_ppr).abs().mean()), 2)
        row["maeFp"] = round(float((f.fpf_pts - f.act_ppr).abs().mean()), 2)
        row["nFp"] = int(len(f))
    row["flag"] = bool(m is not None and se and abs(m) >= 1.5 and abs(m) / se >= 2.5 and len(d) >= 25)
    return row


def diagnostics(R):
    """Leans, calibration and volume-vs-efficiency, on the hindsight projections where available (model
    error, not news); weeks without archived inputs use the Tuesday page."""
    R = R.copy()
    R["basis"] = R.hind_ppr.where(R.hind_ppr.notna(), R.page_ppr)
    R["basis_model"] = R.hind_model_ppr.where(R.hind_model_ppr.notna(), R.model_ppr)
    for c in ("car", "tgt", "att"):
        R["basis_o_" + c] = R["hind_o_" + c].where(R["hind_o_" + c].notna(), R["o_" + c])
    out = {"basis": "hindsight" if R.hind_ppr.notna().all() else "hindsight where available, else Tuesday",
           "byPos": [], "groups": [], "calibration": [], "volume": [], "blend": {}}
    for pos in POS:
        d = R[R.pos == pos]
        row = group_row(pos, d, "basis")
        row["flag"] = bool(row["resid"] is not None and row["se"] and abs(row["resid"]) >= 0.75 and abs(row["resid"]) / row["se"] >= 2.5 and len(d) >= 60)
        row["key"] = f"{pos} level"
        out["byPos"].append(row)
    for name, f in FLAGS:
        m = f(R).fillna(False).astype(bool)
        if m.sum() >= 5:
            row = group_row(name, R[m], "basis")
            row["key"] = name
            out["groups"].append(row)
    edges = [-1, 5, 10, 15, 20, 99]
    for lo, hi in zip(edges[:-1], edges[1:]):
        d = R[(R.basis > lo) & (R.basis <= hi)]
        if len(d):
            out["calibration"].append({"bucket": f"{max(lo, 0)}–{hi}" if hi < 99 else f"{lo}+", "n": int(len(d)),
                                       "proj": round(float(d.basis.mean()), 2), "act": round(float(d.act_ppr.mean()), 2),
                                       "fp": round(float(d.fpf_pts.mean()), 2) if d.fpf_pts.notna().any() else None})
    slopes = {}
    for key, d in [("all", R)] + [(p, R[R.pos == p]) for p in POS]:
        if len(d) >= 20 and d.basis.std() > 0:
            x, y = d.basis.values.astype(float), d.act_ppr.values.astype(float)
            b, a0 = np.polyfit(x, y, 1)
            res = y - (a0 + b * x)
            se = np.sqrt((res ** 2).sum() / (len(x) - 2) / ((x - x.mean()) ** 2).sum())
            slopes[key] = {"slope": round(float(b), 3), "se": round(float(se), 3), "n": int(len(x))}
    out["slopes"] = slopes
    for pos in POS:
        d = R[R.pos == pos]
        if not len(d):
            continue
        po = (d.basis_o_att if pos == "QB" else d.basis_o_car + d.basis_o_tgt).astype(float)
        ao = (d.a_att if pos == "QB" else d.a_car + d.a_tgt).astype(float)
        ppo = np.where(po > 0.1, d.basis_model / po.clip(lower=0.1), 0.0)
        vol = (ao - po) * ppo
        tot = d.act_ppr - d.basis_model
        eff = tot - vol
        oe, ose = cluster_mean(ao - po, d.cl)
        row = {"pos": pos, "n": int(len(d)), "oppBias": round(oe, 2), "oppSe": round(ose, 2) if ose else None,
               "volMae": round(float(np.abs(vol).mean()), 2), "effMae": round(float(np.abs(eff).mean()), 2),
               "volBias": round(float(vol.mean()), 2), "effBias": round(float(eff.mean()), 2)}
        if pos != "QB":
            row["tgtBias"] = round(float((d.a_tgt - d.basis_o_tgt).mean()), 2)
            row["carBias"] = round(float((d.a_car - d.basis_o_car).mean()), 2)
        out["volume"].append(row)
    for src, col in (("fp_early", "fpe_pts"), ("fp_final", "fpf_pts")):
        d = R.dropna(subset=[col])
        if len(d) >= 50:
            ws = np.round(np.arange(0, 1.0001, 0.05), 2)
            maes = [float(((1 - w) * d.page_ppr + w * d[col] - d.act_ppr).abs().mean()) for w in ws]
            k = int(np.argmin(maes))
            out["blend"][src] = {"best": float(ws[k]), "maeBest": round(maes[k], 3), "maePage": round(maes[0], 3),
                                 "maeFp": round(maes[-1], 3), "n": int(len(d)), "curve": [round(x, 3) for x in maes]}
    return out


def expert_sweep(R):
    """MAE of this week's projection for every pair of expert weights, rebuilt exactly from the frozen parts:
    page = max(0, model + corr·w/w0 + we·(weekly expert − model)). Tuesday information, so it's fair to
    FantasyPros' Tuesday numbers. The improvement loop moves the defaults toward the best pair."""
    d = R.dropna(subset=["model_ppr", "w0", "we0"]).copy()
    d = d[d.w0.astype(float) > 0]
    if len(d) < 50:
        return None
    grid = np.round(np.arange(0, 0.8001, 0.05), 2)
    model, corr = d.model_ppr.astype(float).values, d.corr_ppr.fillna(0).astype(float).values
    wk = d.wkexp_ppr.astype(float).values
    has = ~np.isnan(wk)
    w0 = d.w0.astype(float).values
    act = d.act_ppr.astype(float).values

    def predict(w, we):
        return np.maximum(0, model + corr * (w / w0) + np.where(has, we * (np.nan_to_num(wk) - model), 0))
    cur = d.page_ppr.astype(float).values
    surf = np.array([[np.abs(predict(w, we) - act).mean() for we in grid] for w in grid])
    i, j = np.unravel_index(np.argmin(surf), surf.shape)
    best = predict(grid[i], grid[j])
    m, se = cluster_mean(np.abs(best - act) - np.abs(cur - act), d.cl)
    w0c, we0c = float(np.median(w0)), float(np.median(d.we0.astype(float)))
    return {"n": int(len(d)), "weeks": int(d.sw.nunique()), "current": {"expertWeight": w0c, "weeklyExpert": we0c, "mae": round(float(np.abs(cur - act).mean()), 3)},
            "best": {"expertWeight": float(grid[i]), "weeklyExpert": float(grid[j]), "mae": round(float(surf[i, j]), 3)},
            "diff": round(m, 3), "se": round(se, 3) if se else None, "grid": [float(x) for x in grid],
            "surface": [[round(float(x), 3) for x in row] for row in surf]}


# ----------------------------------------------------------------------------- rest of season
def ros_eval(games, graded_weeks):
    """Accuracy beyond next week, which is what trade values run on. For each frozen week, its projection
    for every later week that has been played (horizon h = weeks ahead) vs what happened, on weeks the
    player played; FantasyPros' rest-of-season rank at the freeze is the benchmark for ordering."""
    rows = []
    done_weeks = {}
    for p in sorted(glob.glob(dpath("freeze", "*.json"))):
        if p.endswith(".ros.json"):
            continue
        meta, _ = load_freeze(p)
        S, W = int(meta["season"]), int(meta["week"])
        ros = ros_vectors(S, W)
        if not ros:
            continue
        weeks = ros["weeks"]
        for i, G in enumerate(weeks):
            if (S, G) not in done_weeks:
                g = games[(games.season == S) & (games.week == G) & (games.game_type == "REG")]
                done_weeks[(S, G)] = len(g) > 0 and g.home_score.notna().all() and os.path.exists(f"s{yy(S)}.csv") and \
                    (season_stats(S).week == G).any()
            if not done_weeks[(S, G)]:
                continue
            A, played, _ = actuals(S, G)
            act = comp_pts(A, "a_")
            for pl in ros["players"]:
                if i >= len(pl["page_wk"]) or not pl["avail_wk"][i] or pl["id"] not in played:
                    continue
                rows.append({"season": S, "week": W, "target": G, "h": G - W, "id": pl["id"], "pos": pl["pos"],
                             "team": pl["team"], "er": pl["er"], "proj": pl["page_wk"][i], "model": pl["model_wk"][i],
                             "act": float(act.get(pl["id"], 0.0)), "rosmean": float(np.mean([x for x, a in zip(pl["page_wk"], pl["avail_wk"]) if a]) if any(pl["avail_wk"]) else 0)})
    if not rows:
        return None
    H = pd.DataFrame(rows)
    # relevance fixed at the freeze: top N by our rest-of-season average or by FantasyPros' rest-of-season rank
    keep = pd.Series(False, index=H.index)
    for (S, W, pos), d in H.groupby(["season", "week", "pos"]):
        ids = d.drop_duplicates("id")
        n = REL_N[pos]
        top = set(ids.nlargest(n, "rosmean").id) | set(ids.dropna(subset=["er"]).nsmallest(n, "er").id)
        keep.loc[d.index[d.id.isin(top)]] = True
    H = H[keep].copy()
    H["cl"] = H.season.astype(str) + "-" + H.target.astype(str) + "-" + H.team
    out = {"byH": [], "rosMean": None, "nFrozen": int(H.groupby(["season", "week"]).ngroups)}
    for h in sorted(H.h.unique()):
        d = H[H.h == h]
        if len(d) < 20:
            continue
        m, se = cluster_mean((d.proj - d.act).abs(), d.cl)
        rus, rfp = [], []
        for _, g in d.groupby(["season", "week", "target", "pos"]):
            if len(g) >= 8:
                rus.append(g.proj.rank().corr(g.act.rank()))
                gg = g.dropna(subset=["er"])
                rfp.append((-gg.er).rank().corr(gg.act.rank()) if len(gg) >= 8 else np.nan)
        rus, rfp = np.array(rus, float), np.array(rfp, float)
        ok = ~np.isnan(rus) & ~np.isnan(rfp)
        dd = rus[ok] - rfp[ok]
        out["byH"].append({"h": int(h), "n": int(len(d)), "mae": round(m, 3), "se": round(se, 3) if se else None,
                           "bias": round(float((d.act - d.proj).mean()), 3),
                           "rhoUs": round(float(np.nanmean(rus)), 3) if len(rus) else None,
                           "rhoFpRos": round(float(np.nanmean(rfp)), 3) if ok.any() else None,
                           "rhoDiff": round(float(dd.mean()), 3) if len(dd) else None,
                           "rhoSe": round(float(dd.std(ddof=1) / np.sqrt(len(dd))), 3) if len(dd) > 1 else None})
    # rest-of-season average so far: players with 3+ played weeks after a freeze
    agg = H.groupby(["season", "week", "id", "pos"]).agg(proj=("proj", "mean"), act=("act", "mean"), g=("act", "size"),
                                                         er=("er", "first")).reset_index()
    agg = agg[agg.g >= 3]
    if len(agg) >= 30:
        rus, rfp = [], []
        for _, g in agg.groupby(["season", "week", "pos"]):
            if len(g) >= 8:
                rus.append(g.proj.rank().corr(g.act.rank()))
                gg = g.dropna(subset=["er"])
                rfp.append((-gg.er).rank().corr(gg.act.rank()) if len(gg) >= 8 else np.nan)
        out["rosMean"] = {"n": int(len(agg)), "mae": round(float((agg.proj - agg.act).abs().mean()), 3),
                          "bias": round(float((agg.act - agg.proj).mean()), 3),
                          "rhoUs": round(float(np.nanmean(rus)), 3) if rus else None,
                          "rhoFpRos": round(float(np.nanmean(rfp)), 3) if rfp else None}
    return out


# ----------------------------------------------------------------------------- candidates for the improvement loop
def candidates(diag, cum, sweep, weeks_final):
    """Leans strong enough to act on, each with the parameters that could explain it. The improvement loop
    (improve/improve.py) tests these first; nothing here changes the model by itself."""
    c = []
    for r in diag["byPos"]:
        if r["flag"]:
            c.append({"area": r["key"], "evidence": f"actual − projection {r['resid']:+.2f} pts/player (±{r['se']:.2f}, n={r['n']})",
                      "direction": "up" if r["resid"] > 0 else "down", "params": PARAM_HINTS.get(r["key"], [])})
    for r in diag["groups"]:
        if r["flag"]:
            c.append({"area": r["key"], "evidence": f"actual − projection {r['resid']:+.2f} (±{r['se']:.2f}, n={r['n']}); FantasyPros {r.get('fpResid', float('nan')):+.2f}",
                      "direction": "up" if r["resid"] > 0 else "down", "params": PARAM_HINTS.get(r["key"], [])})
    s = diag["slopes"].get("all")
    if s and abs(s["slope"] - 1) >= 0.1 and abs(s["slope"] - 1) / max(s["se"], 1e-9) >= 2.5:
        c.append({"area": "calibration", "evidence": f"actual rises {s['slope']:.2f} pts per projected pt (±{s['se']:.2f})",
                  "direction": "shrink" if s["slope"] < 1 else "spread", "params": PARAM_HINTS["calibration"]})
    for r in diag["volume"]:
        if r["oppSe"] and abs(r["oppBias"]) >= 0.75 and abs(r["oppBias"]) / r["oppSe"] >= 2.5 and r["n"] >= 60:
            c.append({"area": f"{r['pos']} opportunities", "evidence": f"actual − projected {'attempts' if r['pos'] == 'QB' else 'carries+targets'} {r['oppBias']:+.2f} (±{r['oppSe']:.2f})",
                      "direction": "up" if r["oppBias"] > 0 else "down", "params": PARAM_HINTS[f"{r['pos']} opportunities"]})
    if sweep and weeks_final >= 3 and sweep.get("se") and sweep["diff"] / sweep["se"] <= -2.0:
        c.append({"area": "expert weights", "evidence": f"expert weight {sweep['best']['expertWeight']:.2f} / weekly {sweep['best']['weeklyExpert']:.2f} would have cut the miss {sweep['current']['mae']:.2f} → {sweep['best']['mae']:.2f} ({sweep['diff']:+.3f} ± {sweep['se']:.3f})",
                  "direction": "toward best", "params": PARAM_HINTS["expert weights"], "target": sweep["best"]})
    return c


# ----------------------------------------------------------------------------- grade command
def grade(a):
    games = pd.read_csv("games.csv", low_memory=False)
    paths = sorted(p for p in glob.glob(dpath("freeze", "*.json")))
    if not paths:
        sys.exit("no frozen weeks in freeze/")
    os.makedirs(dpath("graded"), exist_ok=True)
    todo = []
    for p in paths:
        meta, F = load_freeze(p)
        S, W = int(meta["season"]), int(meta["week"])
        gp = dpath("graded", tag(S, W) + ".csv")
        if a.weeks and W not in a.weeks:
            continue
        if os.path.exists(gp) and not a.regrade:
            st = pd.read_csv(gp, nrows=1).get("status")
            if st is not None and st.iloc[0] == "final":
                continue
        gw = games[(games.season == S) & (games.week == W) & (games.game_type == "REG") & games.home_score.notna()]
        if not (set(gw.home_team) | set(gw.away_team)) & set(F.team):
            continue   # none of the frozen players' games has finished yet
        todo.append((p, S, W))
    hist = {}
    for S in sorted({s for _, s, _ in todo}):
        tw = [(p, w) for p, s, w in todo if s == S]
        starts = week_starts(games, S)
        last_kick = {W: max(kickoffs(games, S, W).values()) for _, W in tw}
        try:
            hist[S] = fp_history(S, starts, [W for _, W in tw], last_kick)
        except Exception as e:  # history is a bonus; the freeze kept FantasyPros' Tuesday numbers
            print("FantasyPros history unavailable:", e)
            hist[S] = None
    sc_path = dpath("scorecard", "scorecard.json")
    infos = json.load(open(sc_path)).get("weeks", []) if os.path.exists(sc_path) else []
    infos = {(i["season"], i["week"]): {k: v for k, v in i.items() if k not in ("metrics", "vsFinal", "vsEarly", "vsHind")} for i in infos}
    for p, S, W in todo:
        F, info = grade_week(p, games, hist.get(S))
        F["status"] = info["status"]
        F.to_csv(dpath("graded", tag(S, W) + ".csv"), index=False)
        infos[(S, W)] = info
        print(f"graded {S} week {W}: {info['status']} ({info['gamesDone']}/{info['games']} games), {int(F.played.sum())} players played"
              f"{', hindsight rerun' if info['hindsight'] else ', no archived inputs (no hindsight)'}")
    G = [pd.read_csv(f, low_memory=False) for f in sorted(glob.glob(dpath("graded", "*.csv")))]
    if not G:
        write_outputs({"updated": stamp(), "labels": LABEL, "weeks": [], "pending": pending(paths)})
        return
    D = pd.concat(G, ignore_index=True)
    for c in ("hind_ppr", "hind_model_ppr", "hind_o_car", "hind_o_tgt", "hind_o_att", "w0", "we0"):
        if c not in D:
            D[c] = np.nan
    D = D[(D.played == 1) & (D.game_done == 1)].copy()
    if not len(D):
        write_outputs({"updated": stamp(), "labels": LABEL, "weeks": [], "pending": pending(paths)})
        return
    D = add_sw(D)
    D["rel"] = relevant(D)
    R = D[D.rel]
    weeks = []
    for (S, W), d in R.groupby(["season", "week"]):
        i = dict(infos.get((S, W), {"season": int(S), "week": int(W)}))
        i["metrics"] = {s: metrics(d, s) for s in SOURCES}
        i["vsFinal"] = compare(d, "page", "fp_final")
        i["vsEarly"] = compare(d, "page", "fp_early")
        i["vsHind"] = compare(d, "page", "hind")
        i["nRel"], i["nAll"] = int(len(d)), int(((D.season == S) & (D.week == W)).sum())
        weeks.append(i)
    nfinal = sum(1 for w in weeks if w.get("status") == "final")
    cum = {"rel": {s: metrics(R, s) for s in SOURCES}, "all": {s: metrics(D, s) for s in SOURCES},
           "byPos": {pos: {s: metrics(R[R.pos == pos], s) for s in SOURCES} for pos in POS},
           "page_vs_final": compare(R, "page", "fp_final"), "page_vs_early": compare(R, "page", "fp_early"),
           "model_vs_page": compare(R, "model", "page"), "hind_vs_page": compare(R, "hind", "page"),
           "hind_vs_final": compare(R, "hind", "fp_final"), "early_vs_final": compare(R, "fp_early", "fp_final")}
    for k in ("page_vs_final", "page_vs_early", "hind_vs_final"):
        cum[k]["verdict"] = {"mae": verdict(cum[k], "mae", True), "rho": verdict(cum[k], "rho", False), "pairs": verdict(cum[k], "pairs", False)}
    diag = diagnostics(R)
    sweep = expert_sweep(R)
    ros = ros_eval(games, weeks)
    cand = candidates(diag, cum, sweep, nfinal)
    lastkey = max(zip(R.season, R.week))
    last = R[(R.season == lastkey[0]) & (R.week == lastkey[1])].copy()
    last["err"] = last.act_ppr - last.page_ppr
    misses = []
    for r in last.reindex(last.err.abs().sort_values(ascending=False).index).head(15).itertuples():
        notes = [n for n, f in FLAGS[:9] if bool(f(last.loc[[r.Index]]).fillna(False).iloc[0])]
        misses.append({"name": r.name, "pos": r.pos, "team": r.team, "page": round(r.page_ppr, 1), "act": round(r.act_ppr, 1),
                       "hind": None if pd.isna(r.hind_ppr) else round(r.hind_ppr, 1),
                       "fp": None if pd.isna(r.fpf_pts) else round(r.fpf_pts, 1),
                       "opp": f"{(r.o_att if r.pos == 'QB' else r.o_car + r.o_tgt):.1f} → {(r.a_att if r.pos == 'QB' else r.a_car + r.a_tgt):.0f}",
                       "notes": notes})
    out = {"updated": stamp(), "season": int(R.season.max()), "labels": LABEL, "relN": REL_N, "close": CLOSE,
           "goal": goal_status(cum, nfinal), "weeks": weeks, "cumulative": cum, "diagnostics": diag, "expertSweep": sweep,
           "ros": ros, "candidates": cand, "misses": {"season": int(lastkey[0]), "week": int(lastkey[1]), "rows": misses},
           "pending": pending(paths), "improvement": improvement_summary()}
    write_outputs(out)


def goal_status(cum, nfinal):
    """Two goals. Model: beat FantasyPros' Tuesday consensus (same information) by 3%+ in average miss
    with 95% confidence and make more right start/sit calls, over 6+ graded weeks. Product: the same
    against their final consensus (all the week's news), which a Tuesday freeze can only reach with
    late-week updates."""
    def one(c):
        m, p = c.get("mae"), c.get("pairs")
        st = {"weeks": nfinal, "needWeeks": GOAL_WEEKS, "maeTargetPct": GOAL_PCT}
        if m:
            st["maeGapPct"] = round(-100 * m["diff"] / m["b"], 1) if m["b"] else None
            st["maeSig"] = bool(m.get("se") and m["diff"] / m["se"] < -1.96)
        if p:
            st["pairsGap"] = p["diff"]
            st["pairsSig"] = bool(p.get("se") and p["diff"] / p["se"] > 1.96)
        st["met"] = bool(nfinal >= GOAL_WEEKS and st.get("maeSig") and (st.get("maeGapPct") or 0) >= GOAL_PCT and (p is None or p["diff"] > 0))
        return st
    return {"model": one(cum["page_vs_early"]), "product": one(cum["page_vs_final"])}


def improvement_summary():
    """Latest entries from the improvement ledger, for the scorecard page."""
    out = {"paramsVersion": None, "recent": [], "probation": []}
    try:
        out["paramsVersion"] = load_params_file().get("version")
    except Exception:
        pass
    lp = os.path.join(ROOT, "ledger", "experiments.jsonl")
    if os.path.exists(lp):
        rows = [json.loads(x) for x in open(lp) if x.strip()]
        out["recent"] = [{k: r.get(k) for k in ("date", "week", "kind", "change", "source", "decision", "reason", "summary")} for r in rows[-25:]][::-1]
        out["nTested"] = len(rows)
        out["nPromoted"] = sum(1 for r in rows if r.get("decision") == "promoted")
        out["nReverted"] = sum(1 for r in rows if r.get("decision") == "reverted")
    sp = os.path.join(ROOT, "ledger", "state.json")
    if os.path.exists(sp):
        out["probation"] = json.load(open(sp)).get("probation", [])
    return out


def pending(paths):
    """Frozen weeks not fully graded yet, with a preview of what was frozen (top players per position)."""
    out = []
    for p in paths:
        meta, F = load_freeze(p)
        gp = dpath("graded", tag(meta["season"], meta["week"]) + ".csv")
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
    os.makedirs(dpath("scorecard"), exist_ok=True)
    out.setdefault("improvement", improvement_summary())
    json.dump(out, open(dpath("scorecard", "scorecard.json"), "w"), separators=(",", ":"),
              default=lambda x: None if (isinstance(x, float) and np.isnan(x)) else (x.item() if hasattr(x, "item") else str(x)))
    open(dpath("scorecard", "scorecard.md"), "w").write(markdown(out))
    print(open(dpath("scorecard", "scorecard.md")).read())


def fmt(x, nd=2):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def markdown(o):
    L = ["# Fantasy Trader — projection scorecard", "", f"Updated {o['updated']}."]
    if o.get("pending"):
        L.append("Frozen, waiting for games: " + ", ".join(f"{p['season']} week {p['week']} ({p['n']} players, frozen {p['frozenAt']})" for p in o["pending"]) + ".")
    imp = o.get("improvement") or {}
    if imp.get("paramsVersion") is not None:
        L.append(f"Model parameters: version {imp['paramsVersion']}; {imp.get('nTested', 0)} changes tested, {imp.get('nPromoted', 0)} adopted, {imp.get('nReverted', 0)} reverted.")
    if not o.get("weeks"):
        return "\n".join(L + ["", "No graded weeks yet."]) + "\n"
    c, g = o["cumulative"], o["goal"]
    L += ["", "## Where we stand", ""]
    for key, name in (("model", "Model goal (vs FantasyPros Tuesday, same information)"), ("product", "Product goal (vs FantasyPros final, all the week's news)")):
        x = g[key]
        L.append(f"- {name}: {x['weeks']} of {x['needWeeks']} weeks; miss lead {fmt(x.get('maeGapPct'), 1)}% vs {x['maeTargetPct']}% target{' (significant)' if x.get('maeSig') else ''} — {'MET' if x['met'] else 'not met yet'}")
    for key, name in (("page_vs_early", "FantasyPros Tuesday"), ("page_vs_final", "FantasyPros final"), ("hind_vs_final", "FantasyPros final, our model with hindsight availability")):
        x = c[key]
        parts = []
        if x.get("mae"):
            m = x["mae"]
            parts.append(f"average miss {m['a']:.2f} vs {m['b']:.2f} ({m['diff']:+.2f} ± {fmt(m.get('se'))}, n={m['n']}) → {x['verdict']['mae']}")
        if x.get("pairs"):
            p = x["pairs"]
            parts.append(f"start/sit {p['a']:.1f}% vs {p['b']:.1f}% ({p['diff']:+.1f} ± {fmt(p.get('se'), 1)}) → {x['verdict']['pairs']}")
        L.append(f"- vs {name}: " + "; ".join(parts))
    h = c.get("hind_vs_page", {}).get("mae")
    if h:
        L.append(f"- News after Tuesday: knowing who played would have changed our miss by {h['diff']:+.2f} pts ({h['a']:.2f} vs {h['b']:.2f})")
    L += ["", "## Cumulative (fantasy-relevant players who played, PPR)", "",
          "| Source | n | Avg miss | Actual − proj | RMSE | r | Rank corr | Start/sit % |", "|---|---|---|---|---|---|---|---|"]
    for s in SOURCES:
        m = c["rel"][s]
        L.append(f"| {o['labels'][s]} | {m.get('n', 0)} | {fmt(m.get('mae'))} | {fmt(m.get('bias'))} | {fmt(m.get('rmse'))} | {fmt(m.get('r'))} | {fmt(m.get('rho'), 3)} | {fmt(m.get('pairs'), 1)} |")
    L += ["", "## By week", "", "| Season-week | Status | Ours | Hindsight | FP Tue | FP final | Start/sit ours vs FP final |", "|---|---|---|---|---|---|---|"]
    for w in o["weeks"]:
        M = w["metrics"]
        p = w["vsFinal"].get("pairs") or {}
        L.append(f"| {w['season']}-{w['week']} | {w.get('status', '')} | {fmt(M['page'].get('mae'))} | {fmt(M['hind'].get('mae'))} | {fmt(M['fp_early'].get('mae'))} | {fmt(M['fp_final'].get('mae'))} | {fmt(p.get('a'), 1)} vs {fmt(p.get('b'), 1)} |")
    ros = o.get("ros")
    if ros and ros.get("byH"):
        L += ["", "## Rest of season (what trade values run on)", "", "| Weeks ahead | n | Avg miss | Actual − proj | Rank corr ours | Rank corr FP ROS rank |", "|---|---|---|---|---|---|"]
        for r in ros["byH"]:
            L.append(f"| {r['h']} | {r['n']} | {fmt(r['mae'])} | {fmt(r['bias'])} | {fmt(r.get('rhoUs'), 3)} | {fmt(r.get('rhoFpRos'), 3)} |")
        if ros.get("rosMean"):
            rm = ros["rosMean"]
            L.append(f"\nRest-of-season average so far ({rm['n']} player-freezes with 3+ games): miss {fmt(rm['mae'])}, rank corr ours {fmt(rm.get('rhoUs'), 3)} vs FantasyPros {fmt(rm.get('rhoFpRos'), 3)}")
    sw = o.get("expertSweep")
    if sw:
        L += ["", f"## Expert weights (rebuilt from the frozen parts, {sw['n']} players)", "",
              f"Current {sw['current']['expertWeight']:.2f} / {sw['current']['weeklyExpert']:.2f}: miss {sw['current']['mae']:.3f}. Best {sw['best']['expertWeight']:.2f} / {sw['best']['weeklyExpert']:.2f}: {sw['best']['mae']:.3f} ({sw['diff']:+.3f} ± {fmt(sw.get('se'), 3)})."]
    d = o["diagnostics"]
    L += ["", f"## Diagnostics ({d['basis']}; actual − projection, + = projected too low)", ""]
    for r in d["byPos"] + d["groups"]:
        L.append(f"- {r['group']}: {fmt(r['resid'])} ± {fmt(r['se'])} (n={r['n']}; our miss {fmt(r.get('maeUs'))} vs FP {fmt(r.get('maeFp'))}){'  ← flag' if r['flag'] else ''}")
    for r in d["volume"]:
        L.append(f"- {r['pos']} opportunities: actual − projected {fmt(r['oppBias'])} ± {fmt(r['oppSe'])}; miss from volume {fmt(r['volMae'])} vs per-play {fmt(r['effMae'])} pts")
    if d["slopes"].get("all"):
        s = d["slopes"]["all"]
        L.append(f"- calibration: actual rises {s['slope']:.2f} per projected point (± {s['se']:.2f}; 1.00 = calibrated)")
    L += ["", "## Leans the improvement loop will test", ""]
    L += [f"- **{x['area']}**: {x['evidence']} — parameters: {', '.join(x['params']) or 'none mapped'}" for x in o["candidates"]] or ["- none yet: not enough evidence (needs several graded weeks)"]
    if imp.get("recent"):
        L += ["", "## Recent improvement-loop decisions", ""]
        L += [f"- {r.get('date')} {r.get('decision')}: {r.get('summary') or r.get('change')}" for r in imp["recent"][:8]]
    L += ["", f"## Biggest misses, {o['misses']['season']} week {o['misses']['week']}", "", "| Player | Ours | Hindsight | FP final | Actual | Opps proj → actual | Notes |", "|---|---|---|---|---|---|---|"]
    for m in o["misses"]["rows"]:
        L.append(f"| {m['name']} ({m['pos']} {m['team']}) | {m['page']} | {fmt(m.get('hind'), 1)} | {fmt(m['fp'], 1)} | {m['act']} | {m['opp']} | {', '.join(m['notes'])} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="the repo's data folder (default: ../data next to this script)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--page", required=True)
    f.add_argument("--cbs", default="cbs_injuries.tsv")
    f.add_argument("--version", default="")
    f.add_argument("--now", default="")
    f.add_argument("--note", default="")
    f.add_argument("--force", action="store_true")
    g = sub.add_parser("grade")
    g.add_argument("--weeks", type=lambda s: [int(x) for x in s.split(",")], default=None)
    g.add_argument("--regrade", action="store_true")
    a = ap.parse_args()
    if a.data:
        DATA = os.path.abspath(a.data)
    freeze(a) if a.cmd == "freeze" else grade(a)
