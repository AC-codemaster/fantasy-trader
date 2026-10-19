"""Fit and check the weekly points distributions (params/dist.json) on the backtest.

    python3 ../dist/bt_frames.py                  # backtest projections + expected and actual stat lines
    python3 ../dist/fit_dist.py report            # how well params/dist.json describes what happened
    python3 ../dist/fit_dist.py means --write     # weekly: recalibrate the means to the live projection model
    python3 ../dist/fit_dist.py fit [--write]     # yearly: refit everything (holdout check on the later seasons)

Run from the work folder. What "describes what happened" means here:
  calibration  among player-games where the simulation says P(score >= t) = 30%, about 30% did; actual scores
               fall below the simulated 10th / 50th / 90th percentiles 10 / 50 / 90% of the time
  sharpness    CRPS (the average distance between the whole predicted distribution and the result; lower is
               better), against a baseline that ignores the player's role: the scores of past players with
               the same position and projection
  structure    correlations between teammates' and opponents' scores (QB with his receivers, two backs on one
               team, the two QBs in a game) match the real ones
  scoring      the fit is done in PPR; standard and half-PPR are checked without refitting
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
DIST_PATH = os.path.join(ROOT, "params", "dist.json")
SCORING = {"ppr": sim.PPR, "half": np.r_[sim.PPR[:5], 0.5, sim.PPR[6:]], "std": np.r_[sim.PPR[:5], 0.0, sim.PPR[6:]]}
MIN_PRED = 3.0
ROLE_PAIRS = [("QB1", "WR1", 1), ("QB1", "WR2", 1), ("QB1", "TE1", 1), ("QB1", "RB1", 1), ("WR1", "WR2", 1), ("RB1", "RB2", 1),
              ("RB1", "WR1", 1), ("QB1", "QB1", 0), ("WR1", "WR1", 0), ("RB1", "RB1", 0), ("QB1", "WR1", 0)]

DEFAULT = {
    "version": 0,
    "team": {"sd_pass": 0.15, "sd_rush": 0.20, "sd_eff": 0.08, "td_el": 1.5},
    "game": {"pace_vol": 0.04, "pace_eff": 0.06, "script_pass": 0.08, "script_rush": 0.15},
    "player": {"share_rb": 0.25, "share_wr": 0.25, "share_te": 0.25, "share_qb": 0.03, "exit": 0.03, "exit_qb": 0.02,
               "eff": {"QB": 0.0, "RB": 0.10, "WR": 0.12, "TE": 0.08}},
    "play": {"cv_rush": 1.4, "cv_qbrush": 1.3, "cv_catch_rb": 1.15, "cv_catch_wr": 0.82, "cv_catch_te": 0.80,
             "other_ypt": 7.0, "other_cv": 1.6, "other_min": 0.05, "other_car": 0.03, "other_tgt": 0.06},
    "mean": {p: {"vr": 1.0, "vt": 1.0, "ypc": 1.0, "rtd": 1.0, "ypr": 1.0, "ctd": 1.0, "py": 1.0, "ptd": 1.0, "int": 1.0} for p in ("QB", "RB", "WR", "TE")},
}


def load_frame(path="dist_bt.csv.gz"):
    F = pd.read_csv(path)
    F = F[F.opp.notna()].copy()
    return sim.order(F)


def crps_sample(samples, y):
    """CRPS of each column's sample (n, N) against y (N): E|X - y| - E|X - X'| / 2."""
    x = np.sort(samples, axis=0)
    n = x.shape[0]
    a = np.mean(np.abs(x - y[None, :]), axis=0)
    w = (2 * np.arange(1, n + 1) - n - 1)[:, None]
    b = np.sum(w * x, axis=0) / (n * n)
    return a - b


def roles(F):
    k = ["season", "week", "team"]
    rk = F.groupby(k + ["pos"]).pred.rank(ascending=False, method="first")
    return F.pos + rk.astype(int).astype(str)


def pair_corr(F, res, a, b, same):
    """Correlation of res between the role-a player and the role-b player of the same team (same=1) or of the
    opponent (same=0), over team-games where both exist and both are projected for MIN_PRED+ points."""
    k = ["season", "week", "team"]
    D = F[k + ["opp"]].assign(role=roles(F).values, r=res, ok=F.pred.values >= 5)
    A = D[(D.role == a) & D.ok]
    B = D[(D.role == b) & D.ok]
    if same:
        M = A.merge(B, on=k, suffixes=("_a", "_b"))
    else:
        M = A.merge(B.drop(columns=["team"]).rename(columns={"opp": "team"}), on=k, suffixes=("_a", "_b"))
    if len(M) < 30:
        return np.nan, len(M)
    return float(np.corrcoef(M.r_a, M.r_b)[0, 1]), len(M)


def sim_pair_corr(F, Pts, a, b, same):
    """Same correlation inside the simulation (pooled over draws)."""
    k = ["season", "week", "team"]
    D = F[k + ["opp"]].assign(role=roles(F).values, ok=F.pred.values >= 5, i=np.arange(len(F)))
    A = D[(D.role == a) & D.ok]
    B = D[(D.role == b) & D.ok]
    if same:
        M = A.merge(B, on=k, suffixes=("_a", "_b"))
    else:
        M = A.merge(B.drop(columns=["team"]).rename(columns={"opp": "team"}), on=k, suffixes=("_a", "_b"))
    if len(M) < 30:
        return np.nan
    xa, xb = Pts[:, M.i_a.values], Pts[:, M.i_b.values]
    xa, xb = xa - xa.mean(0), xb - xb.mean(0)
    return float((xa * xb).sum() / np.sqrt((xa * xa).sum() * (xb * xb).sum()))


def baseline_crps(Ftr, Fte, w, n=200, seed=1):
    """Role-blind baseline: sample the actual scores of training player-games with the same position and a
    projection within 10% (at least 0.75 points), scaled by the projection ratio."""
    rng = np.random.default_rng(seed)
    out = np.zeros(len(Fte))
    ptr, atr = sim.expected_points(Ftr, w), sim.actual_points(Ftr, w)
    pte, ate = sim.expected_points(Fte, w), sim.actual_points(Fte, w)
    for pos in ["QB", "RB", "WR", "TE"]:
        mtr, mte = (Ftr.pos == pos).values, np.flatnonzero((Fte.pos == pos).values)
        P, A = ptr[mtr], atr[mtr]
        o = np.argsort(P)
        P, A = P[o], A[o]
        for j in mte:
            p = pte[j]
            h = max(0.75, 0.1 * p)
            lo, hi = np.searchsorted(P, p - h), np.searchsorted(P, p + h)
            if hi - lo < 30:
                c = np.searchsorted(P, p)
                lo, hi = max(0, c - 15), min(len(P), c + 15)
            s = rng.integers(lo, hi, n)
            x = A[s] * (p / np.maximum(P[s], 0.5))
            out[j] = crps_sample(x[:, None], np.array([ate[j]]))[0]
    return out


def evaluate(F, P, n=200, seed=7, scorings=("ppr", "std"), corr=True, base_train=None, quiet=False):
    X = sim.prep(F)
    S = sim.simulate(X, P, n=n, seed=seed)
    rep = {}
    m = F.pred.values >= MIN_PRED
    for sc in scorings:
        w = SCORING[sc]
        Pts = sim.points(S, w)
        y = sim.actual_points(F, w)
        e = sim.expected_points(F, w)
        cr = crps_sample(Pts, y)
        q = np.quantile(Pts, [0.1, 0.5, 0.9], axis=0)
        r = {"n": int(m.sum()), "crps": float(cr[m].mean()), "mean_sim": float(Pts.mean(0)[m].mean()), "mean_act": float(y[m].mean()),
             "mean_proj": float(e[m].mean()),
             "below_p10": float((y < q[0])[m].mean()), "below_p50": float((y < q[1])[m].mean()), "below_p90": float((y < q[2])[m].mean()),
             "byPos": {}}
        for pos in ["QB", "RB", "WR", "TE"]:
            mm = m & (F.pos.values == pos)
            r["byPos"][pos] = {"n": int(mm.sum()), "crps": round(float(cr[mm].mean()), 3), "mean_sim": round(float(Pts.mean(0)[mm].mean()), 2),
                               "mean_act": round(float(y[mm].mean()), 2), "sd_sim": round(float(Pts.std(0)[mm].mean()), 2),
                               "rmse_res": round(float(np.sqrt(np.mean((y[mm] - Pts.mean(0)[mm]) ** 2))), 2),
                               "p10": round(float((y < q[0])[mm].mean()), 3), "p50": round(float((y < q[1])[mm].mean()), 3),
                               "p90": round(float((y < q[2])[mm].mean()), 3)}
        # reliability of P(score >= t)
        rel = []
        for t in (5, 10, 15, 20, 25):
            pr = (Pts >= t).mean(0)[m]
            ob = (y >= t)[m]
            bins = np.clip((pr * 10).astype(int), 0, 9)
            for b in range(10):
                k = bins == b
                if k.sum() >= 40:
                    rel.append({"t": t, "bin": b, "n": int(k.sum()), "pred": round(float(pr[k].mean()), 3), "obs": round(float(ob[k].mean()), 3)})
        r["reliability"] = rel
        r["rel_err"] = float(np.average([abs(x["pred"] - x["obs"]) for x in rel], weights=[x["n"] for x in rel])) if rel else None
        if base_train is not None:
            bc = baseline_crps(base_train, F[m].reset_index(drop=True), w)
            r["crps_baseline"] = float(bc.mean())
        rep[sc] = r
    if corr:
        w = SCORING["ppr"]
        Pts = sim.points(S, w)
        y = sim.actual_points(F, w)
        res = y - Pts.mean(0)
        rep["corr"] = []
        for a, b, same in ROLE_PAIRS:
            c_act, nn = pair_corr(F, res, a, b, same)
            c_sim = sim_pair_corr(F, Pts, a, b, same)
            rep["corr"].append({"pair": f"{a}-{b}" + (" same team" if same else " opponents"), "actual": round(c_act, 3), "sim": round(c_sim, 3), "n": nn})
    if not quiet:
        show(rep)
    return rep


def show(rep):
    for sc, r in rep.items():
        if sc == "corr":
            continue
        base = f" (baseline {r['crps_baseline']:.3f})" if "crps_baseline" in r else ""
        print(f"[{sc}] n {r['n']}  CRPS {r['crps']:.3f}{base}  mean sim {r['mean_sim']:.2f} actual {r['mean_act']:.2f} proj {r['mean_proj']:.2f}"
              f"  below P10/P50/P90: {r['below_p10']:.3f} {r['below_p50']:.3f} {r['below_p90']:.3f}  P(>=t) error {r['rel_err']:.3f}")
        for pos, x in r["byPos"].items():
            print(f"    {pos}: {x}")
    if "corr" in rep:
        print("correlations (actual vs simulated):", ", ".join(f"{c['pair']} {c['actual']:+.2f}/{c['sim']:+.2f}" for c in rep["corr"]))


# chance a player listed Questionable plays, by his last practice of the week (fitted on 2023-25 regulars by
# fit_pplay; this is the starting point when there's no injury history to fit on)
PPLAY_DEFAULT = {"base": {"Full": 0.92, "Limited": 0.70, "DNP": 0.50, "none": 0.75}, "missed_last_or": 0.5, "qb_or": 0.35,
                 "doubtful": 0.02, "listed_no_status": 0.97, "unlisted": 0.995, "active": 0.995}

MIN_EVENTS = {"vr": 300, "vt": 300, "ypc": 300, "rtd": 300, "ypr": 300, "ctd": 300, "py": 3000, "ptd": 100, "int": 3000}


def fit_means(F):
    """Mean multipliers per position: what really happened against the projection's expected stat line, on
    player-games projected for MIN_PRED+ points. Volumes and totals are ratios of sums; per-play rates are
    ratios of rates (given the plays that happened), so volume and efficiency aren't counted twice."""
    out = {}
    D = F[F.pred >= MIN_PRED]
    for pos in ["QB", "RB", "WR", "TE"]:
        d = D[D.pos == pos]
        s = {c: float(d[c].sum()) for c in d.columns if c.startswith(("a_", "c_")) or c in ("car", "tgt", "att", "qc")}
        r = lambda a, b: a / b if b > 0 else 1.0  # noqa: E731
        car = s["qc"] if pos == "QB" else s["car"]
        m = {"vr": r(s["a_car"], car), "vt": r(s["a_att"], s["att"]) if pos == "QB" else r(s["a_tgt"], s["tgt"]),
             "ypc": r(r(s["a_ry"], s["a_car"]), r(s["c_ry"], car)), "rtd": r(r(s["a_rtd"], s["a_car"]), r(s["c_rtd"], car)),
             "ypr": r(r(s["a_recy"], s["a_rec"]), r(s["c_recy"], s["c_rec"])), "ctd": r(r(s["a_rectd"], s["a_rec"]), r(s["c_rectd"], s["c_rec"])),
             "py": r(s["a_py"], s["c_py"]), "ptd": r(s["a_ptd"], s["c_ptd"]), "int": r(r(s["a_int"], s["a_att"]), r(s["c_int"], s["att"]))}
        # too few events at this position to say anything (a tight end's carries): leave it at 1
        n = {"vr": car, "vt": s["att"] if pos == "QB" else s["tgt"], "ypc": s["a_car"], "rtd": s["a_car"], "ypr": s["a_rec"],
             "ctd": s["a_rec"], "py": s["a_py"], "ptd": s["a_ptd"] * 20, "int": s["a_att"]}
        out[pos] = {k: round(float(np.clip(v, 0.6, 1.6)), 3) if n[k] >= MIN_EVENTS[k] else 1.0 for k, v in m.items()}
    return out


# fitted on the whole distribution and the correlations; the per-play spreads are measured directly (fit_play)
SEARCH = [("team", "sd_pass"), ("team", "sd_rush"), ("team", "sd_eff"), ("team", "td_el"),
          ("game", "pace_vol"), ("game", "pace_eff"), ("game", "script_pass"), ("game", "script_rush"),
          ("player", "share_rb"), ("player", "share_wr"), ("player", "share_te"), ("player", "share_qb"),
          ("player", "exit"), ("player", "exit_qb"), ("player", "eff", "QB"), ("player", "eff", "RB"), ("player", "eff", "WR"),
          ("player", "eff", "TE")]


def fit_play(F):
    """Per-play spread, measured from box scores given the plays that happened: E[(yards - plays x rate)^2] =
    plays x s^2 + plays^2 x v (s = per-play sd, v = game-to-game variance of the rate). CV = s / rate."""
    out = {}
    def cv(d, n_col, y_col, rate):
        X = np.c_[d[n_col], d[n_col] ** 2]
        b = np.linalg.lstsq(X, (d[y_col] - d[n_col] * rate) ** 2, rcond=None)[0]
        return float(np.sqrt(max(b[0], 1e-6)) / max(np.average(rate, weights=d[n_col]), 1e-6))
    r = F[(F.pos != "QB") & (F.car > 0.5) & (F.a_car >= 1)]
    out["cv_rush"] = cv(r, "a_car", "a_ry", r.c_ry / r.car)
    q = F[(F.pos == "QB") & (F.qc > 0.5) & (F.a_car >= 1)]
    out["cv_qbrush"] = cv(q, "a_car", "a_ry", q.c_ry / q.qc)
    for pos in ["RB", "WR", "TE"]:
        c = F[(F.pos == pos) & (F.tgt > 0.5) & (F.a_rec >= 1)]
        out["cv_catch_" + pos.lower()] = cv(c, "a_rec", "a_recy", c.c_recy / c.c_rec)
    return {k: round(v, 3) for k, v in out.items()}
BOUNDS = {"td_el": (0.5, 3.0), "exit": (0.0, 0.15), "exit_qb": (0.0, 0.1)}


def getp(P, path):
    x = P
    for k in path:
        x = x[k]
    return x


def setp(P, path, v):
    x = P
    for k in path[:-1]:
        x = x[k]
    x[path[-1]] = v


def corr_targets(F):
    w = SCORING["ppr"]
    y = sim.actual_points(F, w)
    # residual against the simulated mean is what the simulation compares; for the target use the projection
    # scaled to the actual mean of its position (the same thing up to a constant per position)
    res = y - sim.expected_points(F, w)
    return [pair_corr(F, res, a, b, s)[0] for a, b, s in ROLE_PAIRS]


def loss(F, X, P, targets, n, seed, w_corr):
    S = sim.simulate(X, P, n=n, seed=seed)
    m = F.pred.values >= MIN_PRED
    tot = 0.0
    for sc, wt in (("ppr", 1.0), ("std", 0.5)):
        Pts = sim.points(S, SCORING[sc])
        tot += wt * float(crps_sample(Pts, sim.actual_points(F, SCORING[sc]))[m].mean())
    Pts = sim.points(S, SCORING["ppr"])
    ce = [sim_pair_corr(F, Pts, a, b, s) - t for (a, b, s), t in zip(ROLE_PAIRS, targets)]
    return tot + w_corr * float(np.nansum(np.square(ce))), ce


def fit(F, P0, n=150, seed=11, passes=3, w_corr=5.0, step=0.3, log=print):
    """Coordinate search on the dispersion and correlation parameters (common random numbers), means from data."""
    P = json.loads(json.dumps(P0))
    P["mean"] = fit_means(F)
    P["play"].update(fit_play(F))
    log("per-play spread: " + json.dumps({k: P["play"][k] for k in ("cv_rush", "cv_qbrush", "cv_catch_rb", "cv_catch_wr", "cv_catch_te")}))
    X = sim.prep(F)
    targets = corr_targets(F)
    best, ce = loss(F, X, P, targets, n, seed, w_corr)
    log(f"start loss {best:.4f}")
    for it in range(passes):
        improved = False
        for path in SEARCH:
            cur = getp(P, path)
            for mult in (1 + step, 1 / (1 + step)):
                v = cur * mult if cur > 0 else (0.02 if mult > 1 else 0.0)
                lo, hi = BOUNDS.get(path[-1], (0.0, 5.0))
                v = float(np.clip(v, lo, hi))
                if abs(v - cur) < 1e-6:
                    continue
                setp(P, path, v)
                l, c = loss(F, X, P, targets, n, seed, w_corr)
                if l < best - 1e-4:
                    best, ce, improved = l, c, True
                    log(f"  pass {it + 1}: {'.'.join(path)} {cur:.4g} -> {v:.4g}  loss {best:.4f}")
                    break
                setp(P, path, cur)
        step *= 0.6 if not improved else 0.85
    log(f"end loss {best:.4f}; correlation errors " + ", ".join(f"{e:+.2f}" for e in ce))
    for path in SEARCH:
        setp(P, path, round(float(getp(P, path)), 4))
    return P


NV = "https://github.com/nflverse/nflverse-data/releases/download"


def ensure_injury_files(seasons):
    """nflverse injury reports and snap counts for past seasons (GitHub only), if missing from the work folder."""
    import subprocess
    for y in seasons:
        for url, out in ((f"{NV}/injuries/injuries_{y}.csv", f"inj{str(y)[2:]}.csv"), (f"{NV}/snap_counts/snap_counts_{y}.csv", f"snaps{str(y)[2:]}.csv")):
            if not os.path.exists(out):
                subprocess.run(["curl", "-sSLf", "-o", out, url], check=False)


def fit_pplay(seasons=(2023, 2024, 2025), min_share=0.35):
    """Chance a player plays, from past injury reports (nflverse injuries_{yy}.csv, snaps{yy}.csv, games.csv in the
    work folder): regulars (35%+ of offensive snaps over his team's last 4 games) listed Questionable, by his last
    practice of the week (full / limited / did not practice / no report), whether he missed his team's last game,
    and quarterbacks separately (a QB listed Questionable sits more often). Logistic fit; Doubtful and players on
    the report with no game status are simple rates."""
    ensure_injury_files(seasons)
    ids = pd.read_csv("db_playerids.csv", low_memory=False, usecols=["pfr_id", "gsis_id"]).dropna()
    pfr2g = ids.drop_duplicates("pfr_id").set_index("pfr_id").gsis_id.to_dict()
    games = pd.read_csv("games.csv", low_memory=False)
    rows = []
    for y in seasons:
        fi, fs = f"inj{str(y)[2:]}.csv", f"snaps{str(y)[2:]}.csv"
        if not (os.path.exists(fi) and os.path.exists(fs)):
            continue
        inj = pd.read_csv(fi, low_memory=False)
        inj = inj[(inj.game_type == "REG") & inj.position.isin(["QB", "RB", "WR", "TE"])].copy()
        sn = pd.read_csv(fs, low_memory=False)
        sn = sn[sn.game_type == "REG"].assign(g=lambda d: d.pfr_player_id.map(pfr2g)).dropna(subset=["g"])
        pct = {(g, int(w)): p for g, w, p in zip(sn.g, sn.week, sn.offense_pct)}
        gy = games[(games.season == y) & (games.game_type == "REG")]
        tw = {}
        for r in gy.itertuples():
            tw.setdefault(r.home_team, []).append(int(r.week))
            tw.setdefault(r.away_team, []).append(int(r.week))
        feats = []
        for gsis, t, w in zip(inj.gsis_id, inj.team, inj.week):
            prev = [x for x in sorted(tw.get(t, [])) if x < int(w)]
            sh = [pct.get((gsis, x), 0.0) for x in prev[-4:]]
            feats.append((np.mean(sh) if sh else np.nan, pct.get((gsis, prev[-1]), 0.0) if prev else np.nan, pct.get((gsis, int(w)), 0.0) > 0))
        inj["share4"], inj["lastpct"], inj["played"] = zip(*feats)
        rows.append(inj)
    if not rows:
        return None
    D = pd.concat(rows)
    D = D[D.share4 >= min_share].copy()
    D["prac"] = D.practice_status.map({"Full Participation in Practice": "Full", "Limited Participation in Practice": "Limited",
                                        "Did Not Participate In Practice": "DNP"}).fillna("none")
    D["missed"] = (D.lastpct.fillna(0) <= 0).astype(float)
    D["qb"] = (D.position == "QB").astype(float)
    q = D[D.report_status == "Questionable"]
    # logistic regression by Newton steps with a weak ridge (small sample)
    levels = ["Full", "Limited", "DNP", "none"]
    Xm = np.c_[[(q.prac == l).astype(float).values for l in levels]].T
    Xm = np.c_[Xm, q.missed.values, q.qb.values]
    yv = q.played.astype(float).values
    beta = np.zeros(Xm.shape[1])
    lam = np.r_[np.full(len(levels), 0.1), 1.0, 1.0]
    for _ in range(50):
        p = 1 / (1 + np.exp(-Xm @ beta))
        g = Xm.T @ (yv - p) - lam * beta
        H = (Xm * (p * (1 - p))[:, None]).T @ Xm + np.diag(lam)
        beta += np.linalg.solve(H, g)
    sig = lambda z: float(1 / (1 + np.exp(-z)))  # noqa: E731
    out = {"base": {l: round(sig(beta[i]), 3) for i, l in enumerate(levels)},
           "missed_last_or": round(float(np.exp(beta[len(levels)])), 3), "qb_or": round(float(np.exp(beta[len(levels) + 1])), 3),
           "doubtful": round(float(D[D.report_status == "Doubtful"].played.mean()), 3),
           "listed_no_status": round(float(D[D.report_status.isna()].played.mean()), 3),
           "unlisted": 0.995, "active": 0.995,
           "n": {"questionable": int(len(q)), "doubtful": int((D.report_status == "Doubtful").sum()),
                 "listed_no_status": int(D.report_status.isna().sum()), "seasons": [int(s) for s in seasons]},
           "observed": {f"{l}{' missed last' if m else ''}": [round(float(g.played.mean()), 3), int(len(g))]
                        for (l, m), g in q.groupby(["prac", "missed"]) if len(g) >= 10}}
    return out


def fit_kdst(years=None):
    """How kickers' and defenses' weeks spread, from box scores (pipeline/kdst.py tables), for the page's start/sit
    simulation. k_sd / dst_sd: week-to-week spread of their points (ESPN standard), used only for data without
    kickers or defenses. pat_rho: PATs vs the team's offensive touchdowns; pat_fga: PAT tries vs field-goal tries;
    fga_vm: field-goal tries' variance over their mean (below 1: steadier than Poisson). pa_rho: points allowed vs the opposing offense's touchdowns; ya_pa:
    yards allowed vs points allowed. ev: for sacks, interceptions and fumble recoveries, [sigma, c]: a game shock
    of size sigma on the rate (from the variance over the mean) that moves with a good defensive day (low points
    allowed) by c, so the simulated events keep their real correlation with points allowed."""
    sys.path.insert(0, os.path.join(HERE, "..", "pipeline"))
    import kdst
    if years is None and os.path.exists("games.csv"):   # the last four completed regular seasons with box scores here
        g = pd.read_csv("games.csv", low_memory=False)
        g = g[g.game_type == "REG"]
        done = sorted(int(y) for y, d in g.groupby("season") if d.home_score.notna().all() and os.path.exists(f"s{str(y)[2:]}.csv"))
        years = done[-4:]
    st = {y: pd.read_csv(f"s{str(y)[2:]}.csv", low_memory=False) for y in (years or []) if os.path.exists(f"s{str(y)[2:]}.csv")}
    if not st or not os.path.exists("games.csv"):
        return None
    TG, KG = kdst.history(st, pd.read_csv("games.csv", low_memory=False))
    S = pd.concat(st.values())
    S = S[S.season_type == "REG"]
    tds = S.groupby(["season", "week", "team"])[["passing_tds", "rushing_tds"]].sum().sum(axis=1).rename("td").reset_index()
    T = TG.merge(tds.rename(columns={"team": "opp", "td": "otd"}), on=["season", "week", "opp"], how="left")
    dp = np.array([kdst.d_points(v) for v in kdst.actual_dst(TG)[kdst.D_COMP].values.astype(float)])
    kp = KG.assign(pts=[kdst.k_points(v) for v in kdst.actual_k(KG)[kdst.K_COMP].values.astype(float)])
    regular = kp.groupby("id").pts.agg(["size", "std"])
    k_sd = float(np.sqrt(np.mean(np.square(regular[regular["size"] >= 10]["std"]))))
    kt = KG.groupby(["season", "week", "team"]).patM.sum().rename("pat").reset_index().merge(tds, on=["season", "week", "team"])
    zc = 0.97   # how closely points allowed follow its own latent normal (integer scores, tiers); fitted in the sim
    ev = {}
    for c in ("sk", "it", "fr"):
        lam, vm = float(T[c].mean()), float(T[c].var() / T[c].mean())
        sig2 = math.log(1 + max(0.02, vm - 1) / lam)
        cmax = math.sqrt(lam * (math.exp(sig2) - 1) / max(vm, 1.0)) * zc
        r = float(-T[c].corr(T.pa))
        ev[c] = [round(math.sqrt(sig2), 3), round(min(1.0, max(0.0, r / cmax)), 3)]
    return {"k_sd": round(k_sd, 2), "dst_sd": round(float(dp.std()), 2), "pat_rho": round(float(kt.pat.corr(kt.td)), 3),
            "pat_fga": round(float(TG.pata.corr(TG.fga)), 3), "fga_vm": round(float(TG.fga.var() / TG.fga.mean()), 3), "pa_rho": round(float(T.pa.corr(T.otd)), 3),
            "ya_pa": round(float(T.pa.corr(T.oyds)), 3), "ev": ev, "seasons": sorted(int(y) for y in st),
            "note": "fitted on box scores (dist/fit_dist.py fit_kdst); see its docstring"}


def load_params(path=None):
    p = path or DIST_PATH
    return json.load(open(p)) if os.path.exists(p) else json.loads(json.dumps(DEFAULT))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["report", "fit", "means"])
    ap.add_argument("--frame", default="dist_bt.csv.gz")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--default", action="store_true", help="start from the built-in defaults, not params/dist.json")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--w-corr", dest="w_corr", type=float, default=5.0)
    ap.add_argument("--step", type=float, default=0.3)
    ap.add_argument("--start", default=None, help="start from this parameter file")
    a = ap.parse_args()
    F = load_frame(a.frame)
    P = json.loads(json.dumps(DEFAULT)) if a.default else load_params(a.start)
    tr = F[F.season == F.season.min()].reset_index(drop=True)
    te = F[F.season > F.season.min()].reset_index(drop=True)
    if a.cmd == "means":
        # the projection model changes week to week (improvement loop), so its bias does too: refresh the mean
        # multipliers and the chance-he-plays table, keep the fitted spreads and correlations
        P0 = load_params()
        P1 = json.loads(json.dumps(P0))
        P1["mean"] = fit_means(F)
        rep = evaluate(F, P1, n=200, quiet=True, corr=False)
        old = evaluate(F, P0, n=200, quiet=True, corr=False)
        ch = {pos: {k: v for k, v in P1["mean"][pos].items() if abs(v - P0["mean"].get(pos, {}).get(k, 1.0)) >= 0.005} for pos in P1["mean"]}
        print("mean multipliers changed:", json.dumps({p: c for p, c in ch.items() if c}) or "none")
        print(f"CRPS all weeks {old['ppr']['crps']:.4f} -> {rep['ppr']['crps']:.4f}; simulated mean {old['ppr']['mean_sim']:.2f} -> "
              f"{rep['ppr']['mean_sim']:.2f} (actual {rep['ppr']['mean_act']:.2f})")
        pp = fit_pplay()
        if pp:
            P1["pplay"] = pp
        if a.write:
            P1["meansFitted"] = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
            P1.setdefault("check", {})["means"] = {"crps": round(rep["ppr"]["crps"], 4), "mean_sim": round(rep["ppr"]["mean_sim"], 3),
                                                  "mean_act": round(rep["ppr"]["mean_act"], 3), "prob_error": round(rep["ppr"]["rel_err"], 4)}
            json.dump(P1, open(DIST_PATH, "w"), indent=1)
            print("wrote", DIST_PATH)
    elif a.cmd == "report":
        print(f"train ({tr.season.min()}):")
        evaluate(tr, P, n=a.n)
        print(f"test ({sorted(te.season.unique())}):")
        evaluate(te, P, n=a.n, base_train=tr)
    else:
        print("holdout check: fit on", tr.season.min(), "only, then test on later seasons")
        Pt = fit(tr, P, n=a.n, passes=a.passes, w_corr=a.w_corr, step=a.step)
        json.dump(Pt, open("dist_holdout.json", "w"), indent=1)
        print("train:"); evaluate(tr, Pt, n=200)
        print("test:"); rep_test = evaluate(te, Pt, n=200, base_train=tr)
        if a.write:
            print("final fit on every season")
            Pf = fit(F, Pt, n=a.n, passes=max(1, a.passes - 1), w_corr=a.w_corr, step=a.step * 0.5)
            rep_all = evaluate(F, Pf, n=200, quiet=True)
            Pf["version"] = int(P.get("version", 0)) + 1
            Pf["fitted"] = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
            Pf["data"] = {str(s): sorted(int(w) for w in F[F.season == s].week.unique()) for s in sorted(F.season.unique())}
            Pf["check"] = {"holdout": {"trainedOn": int(tr.season.min()), "crps": round(rep_test["ppr"]["crps"], 3),
                                       "crps_baseline": round(rep_test["ppr"]["crps_baseline"], 3),
                                       "below_p10_p50_p90": [round(rep_test["ppr"][k], 3) for k in ("below_p10", "below_p50", "below_p90")],
                                       "prob_error": round(rep_test["ppr"]["rel_err"], 3)},
                           "all": {"crps": round(rep_all["ppr"]["crps"], 3), "prob_error": round(rep_all["ppr"]["rel_err"], 3),
                                   "corr": rep_all["corr"]}}
            Pf["pplay"] = fit_pplay() or P.get("pplay", PPLAY_DEFAULT)
            Pf["kdst"] = fit_kdst() or P.get("kdst")
            json.dump(Pf, open(DIST_PATH, "w"), indent=1)
            print("wrote", DIST_PATH)
