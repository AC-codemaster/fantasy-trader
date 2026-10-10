"""Backtest a parameter set: replay past weeks with backtest_core and compare against another set.

    python3 backtest/evaluate.py                       # the live parameters, all evaluation weeks
    python3 backtest/evaluate.py --set decay=0.875     # a challenger vs the live parameters

Run from a folder with the season files (backtest/fetch_history.py, build_db.py --fetch).
Evaluation weeks: every regular-season week from week 3 of the two previous seasons, and week 2 on of
the current season up to the last completed week. Players count when the live (champion) projection is
3+ PPR points, so both sets are scored on the same player-games.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import backtest_core as bc  # noqa: E402
from ftlib import backtest_params, load_params_file, values  # noqa: E402

MIN_PROJ = 3.0
_SEASONS = {}


def current_season_and_week():
    g = pd.read_csv("games.csv", low_memory=False)
    g = g[g.game_type == "REG"]
    S = int(g[g.home_score.notna()].season.max())
    s = g[g.season == S]
    done = s.groupby("week").home_score.apply(lambda x: x.notna().all())
    last = int(max([w for w, ok in done.items() if ok] or [0]))
    return S, last


def eval_weeks(current=None, last_done=None, back=2):
    """{season: [weeks]} for the evaluation set."""
    if current is None:
        current, last_done = current_season_and_week()
    out = {}
    for S in range(current - back, current):
        out[S] = list(range(3, 19))
    if last_done and last_done >= 2:
        stats = pd.read_csv(f"s{str(current)[2:]}.csv", low_memory=False, usecols=["week", "season_type"])
        have = set(stats[stats.season_type == "REG"].week.astype(int))
        out[current] = [w for w in range(2, last_done + 1) if w in have]
    return out


def season(S):
    if S not in _SEASONS:
        _SEASONS[S] = bc.Season(S)
    return _SEASONS[S]


def _task(args):
    S, W, P = args
    R = season(S).project(W, P)
    keep = ["season", "week", "id", "team", "pos", "pred", "actual", "g_cur", "age", "qbrank", "car", "tgt", "att", "a_car", "a_tgt", "a_att"]
    return R[keep] if len(R) else R


def predict(vals, weeks, procs=None):
    """Backtest projections for a parameter set (values dict) over {season: [weeks]}."""
    P = backtest_params(vals)
    for S in weeks:
        season(S)   # load before forking so workers share it
    tasks = [(S, W, P) for S, ws in weeks.items() for W in ws]
    procs = procs or min(2, os.cpu_count() or 1)
    if procs > 1 and len(tasks) > 1:
        with mp.get_context("fork").Pool(procs) as pool:
            parts = pool.map(_task, tasks)
    else:
        parts = [_task(t) for t in tasks]
    return pd.concat([p for p in parts if len(p)], ignore_index=True)


def _cluster(d, cl):
    d = np.asarray(d, float)
    n = len(d)
    if n < 2:
        return float(d.mean()) if n else 0.0, None
    m = d.mean()
    s = pd.Series(d - m).groupby(np.asarray(cl)).sum()
    k = len(s)
    return float(m), float(np.sqrt((s ** 2).sum() * k / max(k - 1, 1)) / n)


def summarize(A):
    """MAE, bias, calibration slope and a few guard groups for one prediction set (rows already masked)."""
    e = A.pred - A.actual
    b, a0 = np.polyfit(A.pred.values, A.actual.values, 1) if len(A) > 20 else (np.nan, np.nan)
    bq = A[(A.pos == "QB") & (A.qbrank.fillna(1) >= 2)]
    return {"n": int(len(A)), "mae": round(float(e.abs().mean()), 4), "bias": round(float(-e.mean()), 3),
            "slope": round(float(b), 3),
            "byPos": {p: {"mae": round(float((g.pred - g.actual).abs().mean()), 4), "bias": round(float((g.actual - g.pred).mean()), 3), "n": int(len(g))}
                      for p, g in A.groupby("pos")},
            "backupQbBias": round(float((bq.actual - bq.pred).mean()), 3) if len(bq) >= 10 else None}


def paired(champ, chal):
    """Challenger minus champion absolute error on the champion's player-games (champion projection ≥ 3)."""
    key = ["season", "week", "id"]
    M = champ[champ.pred >= MIN_PROJ][key + ["team", "pos", "pred", "actual", "qbrank"]].merge(
        chal[key + ["pred"]].rename(columns={"pred": "pred2"}), on=key, how="inner")
    M["cl"] = M.season.astype(str) + "-" + M.week.astype(str) + "-" + M.team
    d = (M.pred2 - M.actual).abs() - (M.pred - M.actual).abs()
    m, se = _cluster(d, M.cl)
    out = {"n": int(len(M)), "diff": round(m, 4), "se": round(se, 4) if se else None, "z": round(m / se, 2) if se else None,
           "champ": summarize(M), "chal": summarize(M.assign(pred=M.pred2)), "seasons": {}, "byPos": {}}
    for S, g in M.groupby("season"):
        dm, ds = _cluster((g.pred2 - g.actual).abs() - (g.pred - g.actual).abs(), g.cl)
        out["seasons"][str(S)] = {"n": int(len(g)), "diff": round(dm, 4), "se": round(ds, 4) if ds else None,
                                  "z": round(dm / ds, 2) if ds else None}
    for p, g in M.groupby("pos"):
        dm, ds = _cluster((g.pred2 - g.actual).abs() - (g.pred - g.actual).abs(), g.cl)
        out["byPos"][p] = {"n": int(len(g)), "diff": round(dm, 4), "se": round(ds, 4) if ds else None, "z": round(dm / ds, 2) if ds else None}
    return out


def params_hash(vals):
    return hashlib.sha1(json.dumps(vals, sort_keys=True).encode()).hexdigest()[:10]


def code_hash():
    h = hashlib.sha1()
    for f in ("backtest_core.py",):
        h.update(open(os.path.join(HERE, f), "rb").read())
    h.update(open(os.path.join(HERE, "..", "tools", "ftlib.py"), "rb").read())
    return h.hexdigest()[:10]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], help="name=value overrides for a challenger")
    ap.add_argument("--procs", type=int, default=None)
    a = ap.parse_args()
    vals = values(load_params_file())
    weeks = eval_weeks()
    print("evaluation weeks:", {S: f"{w[0]}–{w[-1]} ({len(w)})" for S, w in weeks.items() if w})
    champ = predict(vals, weeks, a.procs)
    m = champ[champ.pred >= MIN_PROJ]
    print("live parameters:", json.dumps(summarize(m)))
    if a.set:
        chal_vals = dict(vals)
        for kv in a.set:
            k, v = kv.split("=")
            chal_vals[k] = float(v)
        chal = predict(chal_vals, weeks, a.procs)
        print(json.dumps(paired(champ, chal), indent=1))
