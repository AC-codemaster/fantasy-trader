"""Waiver upside: what happened next to players like this free agent (the bank behind the Waivers tab).

    python3 waivers/stash_study.py frames [--seasons 2022,2023,2024,2025]   # replay (about a minute a season)
    python3 waivers/stash_study.py fit [--write]                             # bank + checks -> ../params/stash.json

Run from a folder with the season files (backtest/fetch_history.py 2022 2023 2024 2025 brings 2020-2025). Uses the
live parameters. `frames` appends to stash_frames.csv.gz (a season already in it is replaced).

A free agent's value is his projection plus an option: if his role grows (the starter ahead of him gets hurt, he
wins the job, the team trades someone) you keep him and start him; if not, he sits on your bench or you drop him.
The option is worth more the wider the range of where his role can go, which a projection alone doesn't show.
This replays the projection model at every week of past seasons and records, for every player on an active roster:

  p0   his projection that week as if he plays (a player who sat gets his own share added back to his team's pool,
       the way the engine projects him)
  c    his projection if the best teammate at his position ahead of him were out that week (the contingent role;
       c = p0 when nobody at his position projects above him)
  path his projection in each later week given who actually played then: 0 when his team played without him
       (hurt, inactive, cut), blank on his team's bye

Everything is measured against the weekly-starter line: the projection of the 12th QB, 24th RB, 30th WR, 12th TE
that week (a weekly starter in a 12-team league). In those units the bank works for any scoring and league size:
the page draws the same line from its own projections.

`fit` keeps the rows a league could have on waivers (outside the clear starters at the position, weeks 3-15), and
checks, each past season predicted from the other seasons' rows only:
  - the chance he projects as a weekly starter in one of the next four weeks: predicted vs what happened, and the
    log loss of the nearest-neighbour prediction with and without each feature (which features the page matches on)
  - how well the bank's expected surplus over the line ranks who ends up useful, against his projection alone
Then writes the bank (every row's path, one character per week) and the checks to params/stash.json.
"""
import argparse
import json
import os
import sys
import zlib
from datetime import date

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "backtest"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import backtest_core as bc  # noqa: E402
from ftlib import backtest_params, load_params_file, values  # noqa: E402

FRAMES = "stash_frames.csv.gz"
OUT = os.path.join(ROOT, "params", "stash.json")
POS = ["QB", "RB", "WR", "TE"]
ON_TEAM = ("ACT", "INA")          # on the active roster (INA: inactive for the game, hurt or a healthy scratch)
# clear starters stay out of the bank (nobody drops them): position rank by p0 that week, any league size
STARTERS = {"QB": 8, "RB": 18, "WR": 24, "TE": 6}
# the weekly-starter line (position rank by projection among players who played that week)
START_N = {"QB": 12, "RB": 24, "WR": 30, "TE": 12}
HORIZON = 4                        # breakout checks look this many weeks ahead
W_MIN, W_MAX = 3, 15               # decision weeks
# path encoding: relative level (projection / weekly-starter line) in steps of STEP, one character a week
STEP = 0.04
ALPHA = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+/"   # 64 levels: 0 .. 2.52
BYE = "."


def frames(seasons):
    P = backtest_params(values(load_params_file()))
    rows = []
    for S in seasons:
        sea = bc.Season(S, P)
        weeks = sorted(int(w) for w in sea.st[S].week.unique())
        for W in weeks:
            if W < 2:
                continue
            got = []

            def hook(st, got=got, sea=sea):
                tm, roW, U, uu, D, T, mult = st["team"], st["roW"], st["U"], st["uu"], st["D"], st["T"], st["mult"]
                damp = st["damp"]
                ids = set(st["ids"])
                mem = roW[(roW.team == tm) & roW.status.isin(ON_TEAM) & roW.position.isin(POS)]
                healthy = set(mem.index)

                def proj(pid, pos, Dx, u):
                    car = T["r"] * u["r"] / Dx["r"] if Dx["r"] > 0 else 0.0
                    tgt = T["t"] * u["t"] / Dx["t"] if Dx["t"] > 0 else 0.0
                    att = T["p"] * u["p"] / Dx["p"] if Dx["p"] > 0 else 0.0
                    return bc.points(pos, st["efficiency"](pid, pos), car, tgt, att, mult)[0]

                # as if he plays: a player who sat gets his own (first-game-back) weight added to the pool; a healthy
                # teammate's absence already sent `damp` of it to depth players, so that part comes back out
                own, base = {}, {}
                for pid in mem.index:
                    pos = mem.loc[pid].position
                    if pid in ids:
                        u = {c: uu[c][pid] for c in "rtp"}
                        Dx = dict(D)
                    else:
                        u = {c: U[c].get((tm, pid), 0.0) * st["back"](pid) for c in "rtp"}
                        Dx = {c: D[c] + u[c] * (1 - (damp if c != "p" and pid in healthy else 0.0)) for c in "rtp"}
                    own[pid] = (u, Dx)
                    base[pid] = proj(pid, pos, Dx, u)
                for pid in mem.index:
                    pos = mem.loc[pid].position
                    u, Dx = own[pid]
                    # the best teammate at his position who played this week and projects above him; his work goes to
                    # the others as in a short absence (damp of it to depth players; a quarterback's attempts in full)
                    ahead = [q for q in ids if q != pid and q in mem.index and mem.loc[q].position == pos and base[q] > base[pid]]
                    c, cid = base[pid], ""
                    if ahead:
                        j = max(ahead, key=lambda q: base[q])
                        uj = own[j][0]
                        Dc = {k: Dx[k] - uj[k] * (1 - (damp if k != "p" else 0.0)) for k in "rtp"}
                        c, cid = proj(pid, pos, Dc, u), j
                    got.append(dict(season=S, week=W, id=pid, team=tm, pos=pos, played=int(pid in ids),
                                    status=mem.loc[pid].status, p0=round(base[pid], 3), c=round(c, 3), cid=cid,
                                    age=sea.ages.get(pid)))

            sea.project(W, P, extra=hook)
            rows += got
        prev = set()
        for y in (S - 1, S - 2):
            prev |= set(pd.read_csv(f"s{str(y)[2:]}.csv", low_memory=False, usecols=["player_id"]).player_id)
        for r in rows:
            if r["season"] == S:
                r["rookie"] = int(r["id"] not in prev)
        print(S, "weeks", weeks[0], "-", weeks[-1], flush=True)
    F = pd.DataFrame(rows)
    if os.path.exists(FRAMES):
        old = pd.read_csv(FRAMES)
        F = pd.concat([old[~old.season.isin(seasons)], F], ignore_index=True)
    F.sort_values(["season", "week", "team", "id"]).to_csv(FRAMES, index=False)
    print("wrote", FRAMES, len(F), "rows; seasons", sorted(F.season.unique()))


def schedule():
    g = pd.read_csv("games.csv", low_memory=False)
    g = g[g.game_type == "REG"]
    games = set()
    for r in g.itertuples():
        games.add((int(r.season), r.home_team, int(r.week)))
        games.add((int(r.season), r.away_team, int(r.week)))
    last = g.groupby("season").week.max().astype(int).to_dict()
    return games, last


def decision_rows(F, complete_only=True):
    """FA-zone rows with their relative paths (k = 0 is the decision week)."""
    games, last = schedule()
    F = F.copy()
    F["rk"] = F.groupby(["season", "week", "pos"]).p0.rank(ascending=False, method="first")
    line = {}
    for (s, w, p), d in F[F.played == 1].groupby(["season", "week", "pos"]):
        v = np.sort(d.p0.values)[::-1]
        line[(s, w, p)] = float(v[min(len(v), START_N[p]) - 1])
    lv = {}
    for r in F.itertuples(index=False):
        lv.setdefault((r.season, r.id), {})[r.week] = (r.p0 if r.played else 0.0, r.team)
    done = F.groupby("season").week.max().to_dict()
    out = []
    keep = F[(F.rk > F.pos.map(STARTERS)) & (F.week >= W_MIN) & (F.week <= W_MAX)]
    for r in keep.itertuples(index=False):
        if complete_only and done[r.season] < last.get(r.season, 18):
            continue
        L, tm = lv[(r.season, r.id)], r.team
        th0 = line.get((r.season, r.week, r.pos))
        if not th0:
            continue
        path = []
        for w in range(r.week, last[r.season] + 1):
            th = line.get((r.season, w, r.pos), th0)
            if w in L:
                v, tm = L[w]
                path.append(v / th)
            elif (r.season, tm, w) in games:
                path.append(0.0)        # his team played without him, or he's on no active roster
            else:
                path.append(np.nan)     # bye
        path[0] = r.p0 / th0
        fut = np.array(path[1:HORIZON + 1], dtype=float)
        b4 = int(np.nanmax(np.append(fut, 0)) >= 1.0)
        out.append(dict(season=r.season, week=r.week, id=r.id, pos=r.pos, rel0=r.p0 / th0, relc=r.c / th0,
                        rookie=int(r.rookie), played=r.played, b4=b4, path=path))
    return pd.DataFrame(out)


def surplus(path, k1=1, k2=8):
    """Weeks k1..k2: how far above the line he projects, summed (a startable week's edge, in line units)."""
    v = np.array(path[k1:k2 + 1], dtype=float)
    return float(np.nansum(np.maximum(0.0, v - 1.0)))


FEATS = {"rel0": 0.06, "relc": 0.15, "week": 4.0, "rookie": 0.5}   # kernel widths (chosen on held-out seasons, see fit)


def knn_predict(train, test, feats, k=60):
    """Kernel-weighted nearest neighbours (same position): predicted b4 and expected surplus for each test row."""
    pb, ps = np.zeros(len(test)), np.zeros(len(test))
    for pos in POS:
        tr = train[train.pos == pos]
        te_idx = np.where(test.pos.values == pos)[0]
        if not len(te_idx) or not len(tr):
            continue
        X = np.stack([tr[f].values.astype(float) / s for f, s in feats.items()], axis=1)
        b, sp = tr.b4.values.astype(float), tr.sp.values.astype(float)
        rw = tr.wt.values.astype(float) if "wt" in tr else np.ones(len(tr))
        te = test.iloc[te_idx]
        Y = np.stack([te[f].values.astype(float) / s for f, s in feats.items()], axis=1)
        for j, y in enumerate(Y):
            d2 = ((X - y) ** 2).sum(axis=1)
            nn = np.argpartition(d2, min(k, len(d2) - 1))[:k]
            w = np.exp(-0.5 * d2[nn]) * rw[nn]
            w = w / w.sum() if w.sum() > 0 else np.full(len(nn), 1 / len(nn))
            pb[te_idx[j]] = (w * b[nn]).sum()
            ps[te_idx[j]] = (w * sp[nn]).sum()
    return pb, ps


def logloss(y, p):
    p = np.clip(p, 0.005, 0.995)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def spearman(a, b):
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


# The page carries a thinned bank: players far below the line are nearly all alike (almost none break out), so most
# of their rows go and the rest stand in for them with a weight. Every row from 30% of the line up stays: thinning
# those (every other week of a player) cost a sixth of the top-10 stash-zone surplus on held-out seasons.
THIN = [(0.1, 8), (0.3, 3), (99, 1)]     # rel0 up to x: keep 1 row in n (weight n)


def thin(R):
    keep, wt = [], []
    for i, r in enumerate(R.itertuples(index=False)):
        n = next(n for x, n in THIN if r.rel0 <= x)
        h = (zlib.crc32(f"{int(r.season)}{r.id}".encode()) + int(r.week)) % n if n > 1 else 0
        keep.append(h == 0)
        wt.append(n)
    T = R[np.array(keep)].copy()
    T["wt"] = np.array(wt)[np.array(keep)]
    return T


def encode_row(r):
    """One string per row: week, rel0 (steps of 0.02), relc (0.04), flags (rookie + 2 x broke out within the horizon
    + 4 x weight code), then the path, a character a week from the decision week on."""
    q = lambda v, st: ALPHA[int(min(len(ALPHA) - 1, max(0, round(v / st))))]
    wcode = [n for _, n in THIN].index(int(r.wt)) + 1 if int(r.wt) > 1 else 0
    return ALPHA[int(r.week)] + q(r.rel0, 0.02) + q(r.relc, STEP) + ALPHA[int(r.rookie) + 2 * int(r.b4) + 4 * wcode] + encode(r.path)


def encode(path):
    s = []
    for v in path:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            s.append(BYE)
        else:
            s.append(ALPHA[int(min(len(ALPHA) - 1, max(0, round(v / STEP))))])
    return "".join(s)


def loso(R, feats, train_filter=None):
    """Leave one season out: predicted breakout chance and expected surplus for every row."""
    pb, ps = np.zeros(len(R)), np.zeros(len(R))
    for s in sorted(R.season.unique()):
        m = (R.season == s).values
        tr = R[~m] if train_filter is None else train_filter(R[~m])
        b, sp_ = knn_predict(tr, R[m], feats)
        pb[m], ps[m] = b, sp_
    return pb, ps


def scores(R, pb, ps, zone):
    """Log loss of the breakout chance; rank correlation of expected vs actual surplus, all rows and the stash zone
    (below 80% of the line now); the actual surplus of each week's top 10 stash-zone players by this ranking."""
    top = []
    for _, d in R.assign(ps=ps)[zone].groupby(["season", "week"]):
        top.append(float(d.sort_values("ps", ascending=False).head(10).sp.mean()))
    return {"logloss": round(logloss(R.b4.values, pb), 4), "rank_corr": round(spearman(ps, R.sp.values), 4),
            "rank_corr_zone": round(spearman(ps[zone], R.sp.values[zone]), 4), "top10_zone_surplus": round(float(np.mean(top)), 4)}


def fit(write):
    F = pd.read_csv(FRAMES)
    R = decision_rows(F)
    R["sp"] = [surplus(p) for p in R.path]
    zone = (R.rel0 < 0.8).values
    seasons = sorted(R.season.unique())
    print("decision rows", len(R), "seasons", seasons, R.groupby("pos").size().to_dict())
    checks = {"seasons": [int(s) for s in seasons], "rows": int(len(R)), "horizon": HORIZON, "surplus_weeks": 8, "variants": {}}
    # which features help (held-out seasons)
    variants = {"all": FEATS, "no_relc": {k: v for k, v in FEATS.items() if k != "relc"},
                "no_week": {k: v for k, v in FEATS.items() if k != "week"}, "no_rookie": {k: v for k, v in FEATS.items() if k != "rookie"},
                "rel0_only": {"rel0": FEATS["rel0"]}}
    for name, feats in variants.items():
        checks["variants"][name] = scores(R, *loso(R, feats), zone)
        print(f"{name:10s}", checks["variants"][name])
    # baselines: one breakout rate per position; ranking by the projection alone
    base = R.groupby("pos").b4.transform("mean").values
    checks["baseline"] = {"logloss_base_rate": round(logloss(R.b4.values, base), 4), **{k: v for k, v in scores(R, base, R.rel0.values, zone).items() if k != "logloss"}}
    print("projection only", checks["baseline"])
    # the thinned bank the page carries
    pb, ps = loso(R, FEATS, thin)
    checks["thinned"] = scores(R, pb, ps, zone)
    print("thinned bank  ", checks["thinned"])
    R["pb"] = pb
    R["bin"] = pd.cut(R.pb, [0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 1.01], right=False)
    cal = R.groupby("bin", observed=True).agg(pred=("pb", "mean"), actual=("b4", "mean"), n=("b4", "size"))
    print(cal.round(3).to_string())
    checks["calibration"] = [{"pred": round(float(x.pred), 3), "actual": round(float(x.actual), 3), "n": int(x.n)} for x in cal.itertuples()]
    if not write:
        return
    T = thin(R)
    bank = {pos: [encode_row(r) for r in T[T.pos == pos].sort_values(["season", "week", "id"]).itertuples(index=False)] for pos in POS}
    out = {
        "version": 1, "fitted": str(date.today()),
        "about": "waivers/stash_study.py: past free agents' projection paths, relative to the weekly-starter line",
        "startN": START_N, "starters": STARTERS, "step": STEP, "rel0Step": 0.02, "alpha": ALPHA, "bye": BYE,
        "thin": [n for _, n in THIN], "feats": FEATS, "k": 60, "horizon": HORIZON,
        "checks": checks, "rows": bank,
    }
    txt = json.dumps(out, separators=(",", ":"))
    open(OUT, "w").write(txt + "\n")
    print(f"wrote {OUT} ({len(txt) // 1024} KB, {len(T)} rows of {len(R)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["frames", "fit"])
    ap.add_argument("--seasons", default="2022,2023,2024,2025,2026")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    if a.cmd == "frames":
        frames([int(x) for x in a.seasons.split(",")])
    else:
        fit(a.write)
