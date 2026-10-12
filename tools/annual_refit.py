"""Yearly refit of the constants in params/annual.json, gated by the improvement loop's backtest gate, followed
by the sealed holdout. Runbook: runbooks/annual-refit.md (scheduled each February).

    cd work && python3 ../tools/annual_refit.py --cache rk            # refit, gate, adopt, holdout
    python3 ../tools/annual_refit.py --cache rk --dry-run             # report only (no files written, no holdout)

H = the most recent completed regular season (games.csv). It is sealed: nothing below fits on it or is gated
on it. Fits use completed seasons up to H-1, recent seasons weighted more (RECENCY per season back).
 - yoy: per-game PPR of players with 6+ games in consecutive seasons, by age in the new season; the shape is
   refitted (weighted, non-increasing in age past the youngest bracket), its level stays anchored to the
   current table (the ratio also carries regression to the mean, which is not aging); shrunk toward the current
   factor by SHRINK players per age.
 - env_k: team-game log change of attempts, pass yards/TDs, skill carries, rush yards/TDs vs the team's
   leave-one-out season average, on x (implied total vs the team's usual, minus 1) and the spread.
 - low_volume: the low-volume cuts scaled by 0.75 and 1.25 (two challengers).
 - faab: the breakout-pool thresholds are league-structure definitions with no backtest; the refit reports
   the pool averaged over more seasons and leaves the values (the user decides).
Gate: improve.gate on evaluate.paired over weeks 3–18 of H-2 and H-1. Each candidate alone, then the passing
ones together; the bundle if it passes, else the best single. Adoption writes annual.json (version + 1), a
changelog entry "annual constants vN" and ledger/annual.jsonl.
Sealed holdout, last and once: the final constants vs the ones the run started with, on H weeks 2–18, logged
in ledger/holdout.jsonl. A second evaluation of the same H is refused.
"""
import argparse
import copy
import json
import multiprocessing as mp
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "backtest"))
sys.path.insert(0, os.path.join(ROOT, "improve"))
import evaluate as ev  # noqa: E402
import improve as im  # noqa: E402
from ftlib import ANNUAL_PATH, backtest_params, load_annual, load_params_file, values  # noqa: E402

NV = "https://github.com/nflverse/nflverse-data/releases/download"
POS = ["QB", "RB", "WR", "TE"]
RECENCY = 0.8
SHRINK = 50.0
FIRST = 2012
LEDGER = os.path.join(ROOT, "ledger")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def completed_season():
    g = pd.read_csv("games.csv", low_memory=False)
    g = g[g.game_type == "REG"]
    done = g.groupby("season").home_score.apply(lambda s: s.notna().all())
    return int(max(s for s, ok in done.items() if ok))


def fetch(cache, H):
    os.makedirs(os.path.join(cache, "nfl"), exist_ok=True)
    jobs = [(f"{NV}/players/players.csv", os.path.join(cache, "players.csv"))]
    for y in range(FIRST, H + 1):
        jobs.append((f"{NV}/stats_player/stats_player_week_{y}.csv", os.path.join(cache, "nfl", f"s{y}.csv")))
    for url, p in jobs:
        if not os.path.exists(p):
            if subprocess.run(["curl", "-sSLf", "-o", p + ".tmp", url]).returncode == 0:
                os.replace(p + ".tmp", p)
            else:
                print("download failed:", url)


def stats(cache, y):
    p = os.path.join(cache, "nfl", f"s{y}.csv")
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p, low_memory=False)
    return d[(d.season_type == "REG") & d.position.isin(POS)].copy()


# ----------------------------------------------------------------------------- yoy
def fit_yoy(cache, H, cur):
    pl = pd.read_csv(os.path.join(cache, "players.csv"), low_memory=False)
    bd = pd.to_datetime(pl.dropna(subset=["gsis_id", "birth_date"]).drop_duplicates("gsis_id").set_index("gsis_id").birth_date, errors="coerce")
    rows = []
    prev = None
    for y in range(FIRST, H):          # pairs (y-1, y) with y <= H-1
        d = stats(cache, y)
        if d is None:
            prev = None
            continue
        g = d.groupby(["player_id", "position"]).agg(pts=("fantasy_points_ppr", "sum"), g=("week", "nunique")).reset_index()
        g = g[g.g >= 6].set_index("player_id")
        if prev is not None:
            j = prev.join(g, lsuffix="0", rsuffix="1", how="inner")
            j = j[j.position0 == j.position1]
            age = ((pd.Timestamp(f"{y}-09-01") - bd.reindex(j.index)).dt.days / 365.25).astype(float)
            rows.append(pd.DataFrame({"pos": j.position1, "age": np.floor(age), "p0": j.pts0 / j.g0, "p1": j.pts1 / j.g1,
                                      "w": RECENCY ** (H - 1 - y), "season": y}).dropna())
        prev = g
    R = pd.concat(rows)
    R = R[R.p0 >= 3]   # ratios of near-zero seasons are noise
    out, report = {}, {}
    for pos in POS:
        table = cur[pos]
        h = R[R.pos == pos]
        # bracket each player-season into the table's age brackets
        lo = -1
        brk = []
        for a, f in table:
            x = h[(h.age > lo) & (h.age <= a)]
            r = (x.w * x.p1).sum() / max((x.w * x.p0).sum(), 1e-9) if len(x) else np.nan
            brk.append((a, f, float(r), float(x.w.sum()), len(x)))
            lo = a
        B = pd.DataFrame(brk, columns=["age", "cur", "ratio", "w", "n"])
        ok = B.ratio.notna() & (B.n >= 10)
        # anchor the level: same weighted mean log factor as the current table
        shift = np.average(np.log(B.cur[ok]), weights=B.w[ok]) - np.average(np.log(B.ratio[ok]), weights=B.w[ok])
        B["fit"] = np.where(ok, B.ratio * np.exp(shift), B.cur)
        # non-increasing in age (pool adjacent violators, weighted)
        vals, ws = list(B.fit), list(np.maximum(B.w, 1e-6))
        blocks = [[v, w_, 1] for v, w_ in zip(vals, ws)]
        i = 0
        while i < len(blocks) - 1:
            if blocks[i][0] < blocks[i + 1][0]:
                v = (blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / (blocks[i][1] + blocks[i + 1][1])
                blocks[i] = [v, blocks[i][1] + blocks[i + 1][1], blocks[i][2] + blocks[i + 1][2]]
                del blocks[i + 1]
                i = max(i - 1, 0)
            else:
                i += 1
        mono = [b[0] for b in blocks for _ in range(b[2])]
        B["mono"] = mono
        B["new"] = ((B.n * B.mono + SHRINK * B.cur) / (B.n + SHRINK)).round(2)
        out[pos] = [[int(a), float(f)] for a, f in zip(B.age, B.new)]
        report[pos] = B.round(3).to_dict("records")
    return out, report


# ----------------------------------------------------------------------------- env_k
def fit_env(cache, H, seasons=4):
    g = pd.read_csv("games.csv", low_memory=False)
    g = g[(g.game_type == "REG") & g.total_line.notna() & g.spread_line.notna()]
    rows = []
    for y in range(H - seasons, H):
        d = stats(cache, y)
        if d is None:
            continue
        q = d[d.position == "QB"].groupby(["team", "week"])[["attempts", "passing_yards", "passing_tds"]].sum()
        k = d[d.position != "QB"].groupby(["team", "week"])[["carries", "rushing_yards", "rushing_tds"]].sum()
        T = q.join(k, how="outer").fillna(0).reset_index()
        gy = g[g.season == y]
        L = {}
        for r in gy.itertuples():
            L[(r.home_team, int(r.week))] = (r.total_line / 2 + r.spread_line / 2, r.spread_line)
            L[(r.away_team, int(r.week))] = (r.total_line / 2 - r.spread_line / 2, -r.spread_line)
        T["imp"] = [L.get((t, w), (np.nan, np.nan))[0] for t, w in zip(T.team, T.week)]
        T["s"] = [L.get((t, w), (np.nan, np.nan))[1] for t, w in zip(T.team, T.week)]
        T = T.dropna(subset=["imp"])
        for c in ("imp", "attempts", "passing_yards", "passing_tds", "carries", "rushing_yards", "rushing_tds"):
            tot = T.groupby("team")[c].transform("sum")
            n = T.groupby("team")[c].transform("size")
            T[c + "_loo"] = (tot - T[c]) / (n - 1)
        T["x"] = T.imp / T.imp_loo - 1
        T["w"] = RECENCY ** (H - 1 - y)
        rows.append(T)
    T = pd.concat(rows)
    out = {}
    for key, col, tdish in (("att", "attempts", False), ("pyd", "passing_yards", False), ("ptd", "passing_tds", True),
                            ("car", "carries", False), ("ryd", "rushing_yards", False), ("rtd", "rushing_tds", True)):
        a = 0.5 if tdish else 0.0
        U = T[(T[col] + a > 0) & (T[col + "_loo"] + a > 0) & np.isfinite(T.x)]
        y_ = np.log((U[col] + a) / (U[col + "_loo"] + a))
        X = np.c_[np.ones(len(U)), U.x, U.s]
        W = U.w.values
        b = np.linalg.solve(X.T @ (X * W[:, None]), X.T @ (W * y_))
        out[key] = [round(float(b[1]), 4), round(float(b[2]), 5)]
    return out, {"team_games": int(len(T)), "seasons": f"{H - seasons}–{H - 1}"}


# ----------------------------------------------------------------------------- faab (report only)
def faab_report(cache, H, cur):
    return {"note": "thresholds are league-structure definitions (12-team starters / waiver level); no backtest can grade "
                    "them, so they are not changed automatically", "values": cur}


# ----------------------------------------------------------------------------- backtest with annual challengers
def predict_annual(vals, A, weeks, procs=None):
    P = backtest_params(vals, env_k={k: tuple(v) for k, v in A["env_k"].items()})
    P["yoy"] = {k: [tuple(x) for x in v] for k, v in A["yoy"].items()}
    P["low_volume"] = {"lowcut": {k: tuple(v) for k, v in A["low_volume"]["lowcut"].items()}, "afull": dict(A["low_volume"]["afull"])}
    for S in weeks:
        ev.season(S)
    tasks = [(S, W, P) for S, ws in weeks.items() for W in ws]
    procs = procs or min(2, os.cpu_count() or 1)
    with mp.get_context("fork").Pool(procs) as pool:
        parts = pool.map(ev._task, tasks)
    return pd.concat([p for p in parts if len(p)], ignore_index=True)


def describe(A0, A1):
    ch = [k for k in ("yoy", "env_k", "low_volume") if A0[k] != A1[k]]
    return ", ".join(ch) or "nothing"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="rk")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--procs", type=int, default=None)
    a = ap.parse_args()
    H = completed_season()
    fetch(a.cache, H)
    A0 = load_annual()
    vals = values(load_params_file())
    rep = [f"# Annual refit, {today()}", "", f"Completed seasons up to {H}; {H} is the sealed holdout. Fits use {FIRST}–{H - 1} "
           f"(recent seasons weighted {RECENCY} per season back); the gate uses weeks 3–18 of {H - 2} and {H - 1}.", ""]
    yoy, yrep = fit_yoy(a.cache, H, A0["yoy"])
    env, erep = fit_env(a.cache, H)
    cands = []
    A = copy.deepcopy(A0); A["yoy"] = yoy; cands.append(("yoy", A))
    A = copy.deepcopy(A0); A["env_k"] = env; cands.append(("env_k", A))
    for f in (0.75, 1.25):
        A = copy.deepcopy(A0)
        A["low_volume"]["lowcut"] = {k: [v[0], int(round(v[1] * f))] for k, v in A0["low_volume"]["lowcut"].items()}
        cands.append((f"low_volume x{f}", A))
    rep += ["## Refitted values", "", "Aging (age bracket: current → refit):"]
    for pos in POS:
        rep.append(f"- {pos}: " + ", ".join(f"≤{a_}: {f0:.2f}→{f1:.2f}" for (a_, f0), (_, f1) in zip(A0["yoy"][pos], yoy[pos])))
    rep += ["", f"Game environment ({erep['team_games']} team-games, {erep['seasons']}): " +
            ", ".join(f"{k} {A0['env_k'][k]} → {v}" for k, v in env.items()), "",
            f"FAAB: {faab_report(a.cache, H, A0['faab'])['note']}.", ""]
    weeks = {H - 2: list(range(3, 19)), H - 1: list(range(3, 19))}
    champ = predict_annual(vals, A0, weeks, a.procs)
    results = []
    rep.append("## Gate (improve.py's, on the backtest)")
    for name, A in cands:
        if A == A0:
            continue
        r = ev.paired(champ, predict_annual(vals, A, weeks, a.procs))
        ok, why = im.gate(r)
        results.append((name, A, r, ok, why))
        rep.append(f"- {name}: {r['diff']:+.4f} ± {r['se']:.4f} pts (z {r['z']}) → {'passes' if ok else 'rejected: ' + '; '.join(why)}")
    passing = [x for x in results if x[3]]
    winner = None
    if len(passing) >= 2:
        B = copy.deepcopy(A0)
        for name, A, *_ in passing:
            key = name.split()[0]
            B[key] = A[key]
        r = ev.paired(champ, predict_annual(vals, B, weeks, a.procs))
        ok, why = im.gate(r)
        rep.append(f"- bundle of {', '.join(n for n, *_ in passing)}: {r['diff']:+.4f} (z {r['z']}) → {'passes' if ok else 'rejected: ' + '; '.join(why)}")
        if ok:
            winner = ("bundle", B, r)
    if winner is None and passing:
        name, A, r, _, _ = sorted(passing, key=lambda x: x[2]["diff"])[0]
        winner = (name, A, r)
    final = winner[1] if winner else A0
    if winner:
        rep += ["", f"**Adopted:** {describe(A0, final)} ({winner[0]}): average miss {winner[2]['champ']['mae']:.3f} → "
                f"{winner[2]['chal']['mae']:.3f} on {winner[2]['n']:,} player-games."]
    else:
        rep += ["", "**Nothing adopted:** no refitted constant passed the gate; annual.json unchanged."]
    if a.dry_run:
        print("\n".join(rep + ["", "(dry run: nothing written, holdout not run)"]))
        return
    os.makedirs(LEDGER, exist_ok=True)
    with open(os.path.join(LEDGER, "annual.jsonl"), "a") as f:
        for name, A, r, ok, why in results:
            f.write(json.dumps({"date": today(), "holdout": H, "candidate": name, "eval": im.trim(r), "passed": ok, "why": why,
                                "adopted": bool(winner) and (winner[0] == name or (winner[0] == "bundle" and ok))}, default=float) + "\n")
    if winner:
        final = copy.deepcopy(final)
        final["version"] = int(A0.get("version", 1)) + 1
        final["updated"] = today()
        json.dump(final, open(ANNUAL_PATH, "w"), indent=1)
        with open(os.path.join(LEDGER, "changelog.md"), "a") as f:
            f.write(f"\n## {today()} — annual constants v{final['version']}: {describe(A0, final)}\n\nAnnual refit on {FIRST}–{H - 1} "
                    f"(holdout {H} sealed). Backtest {H - 2}–{H - 1}: average miss {winner[2]['champ']['mae']:.3f} → "
                    f"{winner[2]['chal']['mae']:.3f} ({winner[2]['diff']:+.4f} ± {winner[2]['se']:.4f}, z {winner[2]['z']}).\n")
    # sealed holdout: last, once
    hp = os.path.join(LEDGER, "holdout.jsonl")
    seen = [json.loads(x) for x in open(hp)] if os.path.exists(hp) else []
    if any(x.get("season") == H for x in seen):
        rep += ["", f"Sealed holdout {H} was already evaluated ({[x['date'] for x in seen if x['season'] == H][0]}); not evaluated again."]
    else:
        hw = {H: [w for w in range(2, 19)]}
        p0 = predict_annual(vals, A0, hw, a.procs)
        p1 = p0 if final is A0 else predict_annual(vals, final, hw, a.procs)
        r = ev.paired(p0, p1)
        base = ev.summarize(p1[p1.pred >= ev.MIN_PROJ])
        row = {"date": today(), "season": H, "weeks": "2–18", "annualVersion": final.get("version", A0.get("version")),
               "paramsVersion": load_params_file().get("version"), "mae": base["mae"], "n": base["n"], "slope": base["slope"],
               "byPos": base["byPos"], "refitVsBefore": {"diff": r["diff"], "se": r["se"], "z": r["z"]} if final is not A0 else None}
        with open(hp, "a") as f:
            f.write(json.dumps(row, default=float) + "\n")
        rep += ["", f"## Sealed holdout {H} (evaluated once)", "",
                f"Live model with the final constants: average miss {base['mae']:.3f} over {base['n']:,} player-games "
                f"(calibration slope {base['slope']})" + (f"; refit vs the constants before: {r['diff']:+.4f} ± {r['se']:.4f} (z {r['z']})."
                                                          if final is not A0 else "; constants unchanged.")]
    open(os.path.join(LEDGER, "annual_last_run.md"), "w").write("\n".join(rep) + "\n")
    json.dump({"yoy": yrep, "env": erep}, open(os.path.join(LEDGER, "annual_fit_detail.json"), "w"), indent=1, default=float)
    print("\n".join(rep))


if __name__ == "__main__":
    main()
