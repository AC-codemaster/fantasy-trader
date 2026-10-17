"""Backtest projections with their expected stat lines, joined to what happened: the data the weekly
points distributions (start/sit, floor and ceiling) are fitted on.

    python3 ../dist/bt_frames.py [--out dist_bt.csv.gz] [--procs 2]

Run from the work folder (season files from build_db.py --fetch and backtest/fetch_history.py). Uses the
live parameters and the improvement loop's evaluation weeks, so `pred` is exactly the champion projection.
"""
import argparse
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backtest"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import backtest_core as bc  # noqa: E402
import evaluate as ev  # noqa: E402
from ftlib import backtest_params, load_params_file, values  # noqa: E402

ACT = {"passing_yards": "a_py", "passing_tds": "a_ptd", "passing_interceptions": "a_int", "rushing_yards": "a_ry",
       "rushing_tds": "a_rtd", "receptions": "a_rec", "receiving_yards": "a_recy", "receiving_tds": "a_rectd",
       "fl": "a_fl", "two": "a_two", "carries": "a_car", "targets": "a_tgt", "attempts": "a_att"}


def _task(args):
    S, W, P = args
    return ev.season(S).project(W, P)


def frames(weeks, procs=2):
    P = backtest_params(values(load_params_file()))
    for S in weeks:
        ev.season(S)
    tasks = [(S, W, P) for S, ws in weeks.items() for W in ws]
    if procs > 1:
        with mp.get_context("fork").Pool(procs) as pool:
            parts = pool.map(_task, tasks)
    else:
        parts = [_task(t) for t in tasks]
    R = pd.concat([p for p in parts if len(p)], ignore_index=True)
    # actual stat line (the project() frame has PPR points and opportunities only)
    acts = []
    for S in weeks:
        d = bc.load_stats(S)
        a = d.groupby(["player_id", "week"])[list(ACT)].sum().rename(columns=ACT).reset_index()
        a["season"] = S
        acts.append(a)
    A = pd.concat(acts).rename(columns={"player_id": "id"})
    R = R.drop(columns=["a_car", "a_tgt", "a_att"]).merge(A, on=["season", "week", "id"], how="left")
    for c in ACT.values():
        R[c] = R[c].fillna(0.0)
    return R


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist_bt.csv.gz")
    ap.add_argument("--procs", type=int, default=2)
    a = ap.parse_args()
    weeks = ev.eval_weeks()
    print("weeks:", {S: f"{w[0]}–{w[-1]}" for S, w in weeks.items() if w}, flush=True)
    R = frames(weeks, a.procs)
    R.to_csv(a.out, index=False)
    print(f"wrote {a.out}: {len(R)} player-games", flush=True)
