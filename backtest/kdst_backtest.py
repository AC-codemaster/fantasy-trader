"""Backtest of the kicker and D/ST projections (pipeline/kdst.py), the K/DST counterpart of backtest_core.py.

For week W of season S it uses only games before W (plus the two seasons before S), the week's actual Vegas line
(as the offense backtest does), and every D/ST and every kicker who kicked for his team that week; scored with
ESPN standard scoring (kdst.STANDARD). The improvement loop tests the K/DST parameters (params.json, eval "kdst")
on it; the same gate as for the offense.

    python3 backtest/kdst_backtest.py                       # the live parameters, all evaluation weeks
    python3 backtest/kdst_backtest.py --set k_fg=50         # a challenger vs the live parameters

Run from the folder with the season files (s{yy}.csv for S-2..S, games.csv): backtest/fetch_history.py.
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "pipeline"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import kdst  # noqa: E402

_HIST = {}


def _hist(S):
    """(team-games, kicker-games) for seasons S-2..S, loaded once."""
    if S not in _HIST:
        st = {}
        for y in (S - 2, S - 1, S):
            f = f"s{str(y)[2:]}.csv"
            if os.path.exists(f):
                st[y] = pd.read_csv(f, low_memory=False)
        games = pd.read_csv("games.csv", low_memory=False)
        _HIST[S] = kdst.history(st, games)
    return _HIST[S]


def project_week(S, W, P):
    """Projected and actual standard points for every D/ST and kicker in week W of season S."""
    TG, KG = _hist(S)
    th, kh = kdst.cut(TG, KG, S, W)
    if not len(th):
        return pd.DataFrame()
    L = kdst.league(th, kh)
    D, K = kdst.profiles(th, kh, L, S, P)
    rows = []
    wk = TG[(TG.season == S) & (TG.week == W)]
    ad = kdst.actual_dst(wk).set_index("team")
    for r in wk.itertuples():
        v = kdst.project_dst(L, D, r.team, r.opp, r.oimp, r.imp - r.oimp, P)
        rows.append({"season": S, "week": W, "id": "DST-" + r.team, "team": r.team, "pos": "DST", "pred": kdst.d_points(v),
                     "actual": kdst.d_points(ad.loc[r.team, kdst.D_COMP].values.astype(float)), "line": int(pd.notna(r.oimp))})
    kw = KG[(KG.season == S) & (KG.week == W)]
    ak = kdst.actual_k(kw)
    imp, spr = dict(zip(wk.team, wk.imp)), dict(zip(wk.team, wk.imp - wk.oimp))
    for r, a in zip(kw.itertuples(), ak[kdst.K_COMP].values):
        v = kdst.project_k(L, D, K, r.id, r.team, imp.get(r.team), spr.get(r.team))
        rows.append({"season": S, "week": W, "id": r.id, "team": r.team, "pos": "K", "pred": kdst.k_points(v),
                     "actual": kdst.k_points(a), "line": int(pd.notna(imp.get(r.team)))})
    return pd.DataFrame(rows)


def kdst_params(vals):
    """The K/DST settings in a params.json values dict (missing ones at their defaults)."""
    return {k: float(vals[k]) for k in kdst.DEFAULTS if k in vals}


def predict(vals, weeks):
    P = kdst_params(vals)
    parts = [project_week(S, W, P) for S, ws in weeks.items() for W in ws]
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["season", "week", "id", "team", "pos", "pred", "actual"])


def _cluster(d, cl):
    d = np.asarray(d, float)
    n = len(d)
    if n < 2:
        return (float(d.mean()) if n else 0.0), None
    m = d.mean()
    s = pd.Series(d - m).groupby(np.asarray(cl)).sum()
    k = len(s)
    return float(m), float(np.sqrt((s ** 2).sum() * k / max(k - 1, 1)) / n)


def summarize(A):
    e = A.pred - A.actual
    b = np.polyfit(A.pred.values, A.actual.values, 1)[0] if len(A) > 20 else np.nan
    return {"n": int(len(A)), "mae": round(float(e.abs().mean()), 4), "bias": round(float(-e.mean()), 3), "slope": round(float(b), 3),
            "byPos": {p: {"mae": round(float((g.pred - g.actual).abs().mean()), 4), "bias": round(float((g.actual - g.pred).mean()), 3),
                          "n": int(len(g))} for p, g in A.groupby("pos")}}


def paired(champ, chal):
    """Challenger minus champion absolute error on the same player-games (same shape as evaluate.paired, so the
    improvement loop's gate reads it unchanged; there's no backup-QB guard here)."""
    key = ["season", "week", "id"]
    M = champ[key + ["team", "pos", "pred", "actual"]].merge(chal[key + ["pred"]].rename(columns={"pred": "pred2"}), on=key, how="inner")
    M["cl"] = M.season.astype(str) + "-" + M.week.astype(str)
    d = (M.pred2 - M.actual).abs() - (M.pred - M.actual).abs()
    m, se = _cluster(d, M.cl)
    out = {"n": int(len(M)), "diff": round(m, 4), "se": round(se, 4) if se else None, "z": round(m / se, 2) if se else None,
           "champ": summarize(M), "chal": summarize(M.assign(pred=M.pred2)), "seasons": {}, "byPos": {}}
    for k, g in M.groupby("season"):
        dm, ds = _cluster((g.pred2 - g.actual).abs() - (g.pred - g.actual).abs(), g.cl)
        out["seasons"][str(k)] = {"n": int(len(g)), "diff": round(dm, 4), "se": round(ds, 4) if ds else None, "z": round(dm / ds, 2) if ds else None}
    for k, g in M.groupby("pos"):
        dm, ds = _cluster((g.pred2 - g.actual).abs() - (g.pred - g.actual).abs(), g.cl)
        out["byPos"][k] = {"n": int(len(g)), "diff": round(dm, 4), "se": round(ds, 4) if ds else None, "z": round(dm / ds, 2) if ds else None}
    return out


def baselines(A, weeks):
    """Naive references on the same player-games: the league average, and each unit's season-to-date average
    (shrunk 3 games toward the league average)."""
    out = {}
    for pos, g in A.groupby("pos"):
        out[pos] = {"model": round(float((g.pred - g.actual).abs().mean()), 3)}
    rows = []
    for S, ws in weeks.items():
        TG, KG = _hist(S)
        ad = kdst.actual_dst(TG).assign(pts=lambda d: [kdst.d_points(v) for v in d[kdst.D_COMP].values.astype(float)])
        ak = kdst.actual_k(KG).assign(pts=lambda d: [kdst.k_points(v) for v in d[kdst.K_COMP].values.astype(float)])
        for W in ws:
            for pos, T, key in (("DST", ad.assign(id="DST-" + ad.team), "id"), ("K", ak, "id")):
                prev = T[(T.season == S) & (T.week < W)]
                lgm = float(T[(T.season < S) | ((T.season == S) & (T.week < W))].pts.mean())
                m = prev.groupby(key).pts.agg(["sum", "count"])
                for r in A[(A.season == S) & (A.week == W) & (A.pos == pos)].itertuples():
                    s_, c_ = (m.loc[r.id, "sum"], m.loc[r.id, "count"]) if r.id in m.index else (0.0, 0)
                    rows.append({"pos": pos, "actual": r.actual, "lg": lgm, "avg": (s_ + 3 * lgm) / (c_ + 3)})
    B = pd.DataFrame(rows)
    for pos, g in B.groupby("pos"):
        out[pos]["leagueAvg"] = round(float((g.lg - g.actual).abs().mean()), 3)
        out[pos]["seasonAvg"] = round(float((g.avg - g.actual).abs().mean()), 3)
    return out


if __name__ == "__main__":
    import evaluate as ev
    from ftlib import load_params_file, values
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], help="name=value overrides for a challenger")
    ap.add_argument("--baselines", action="store_true", help="also report naive references (league and season averages)")
    a = ap.parse_args()
    vals = values(load_params_file())
    weeks = ev.eval_weeks()
    print("evaluation weeks:", {S: f"{w[0]}–{w[-1]} ({len(w)})" for S, w in weeks.items() if w})
    champ = predict(vals, weeks)
    print("live parameters:", json.dumps(summarize(champ)))
    if a.baselines:
        print("references (average miss, standard scoring):", json.dumps(baselines(champ, weeks)))
    if a.set:
        chal_vals = dict(vals)
        for kv in a.set:
            k, v = kv.split("=")
            chal_vals[k] = float(v)
        print(json.dumps(paired(champ, predict(chal_vals, weeks)), indent=1))
