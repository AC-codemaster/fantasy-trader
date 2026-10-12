"""Tests of the rookie-prior model on past draft classes, and the mock-draft stress tests.

    python3 rookie/evaluate_rookies.py --cache DIR [--backtest-dir work] [--rookie-prior 1]

Reads data/rookie/players.csv and predictions.csv (rookie_model.py build / fit). Writes tables to
data/rookie/eval/*.csv and data/rookie/eval/summary.md (pasted into docs/rookie-model.md).

1. Holdout: classes 2019–2025, each predicted by a model fitted on earlier classes only. Rookie PPR per game
   (players with 1+ games) vs (a) a draft-pick-only curve fitted the same way and (b) what the current
   projection model gives rookies in weeks 3–8 (backtest_core replay, where the season files exist).
2. Year 2: does the rookie prior still help predict the second season once the rookie season is known?
3. Mock draft 1 (no draft slot): predicted NFL round from college production, age and combine only.
4. Mock draft 2 (fantasy rookie draft): rank each class by projected rookie value and compare by actual
   NFL round with what happened (PPR/G, top-24 RB/WR and top-12 QB/TE finishes), and with draft order.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import rookie_model as rm  # noqa: E402

EV = os.path.join(rm.OUT, "eval")
POS = rm.POS
HIT = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}
HOLD = list(range(2019, 2026))
MOCK = list(range(2021, 2026))


def rho(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = ~(np.isnan(a) | np.isnan(b))
    return float(spearmanr(a[ok], b[ok])[0]) if ok.sum() > 4 else np.nan


def line_fit(x, y):
    b, a = np.polyfit(x, y, 1)
    return a, b


def pick_curve(D, Y, pos, col="r1_ppg"):
    """Draft-pick-only baseline: line of rookie PPR/G on log(pick), fitted on classes before Y."""
    t = D[(D.season < Y) & (D.pos == pos) & (D.r1_games >= 1)]
    a, b = line_fit(t.lp, t[col])
    return a, b


def games_curve(D, Y, pos):
    t = D[(D.season < Y) & (D.pos == pos) & D.season.isin(set(D.dropna(subset=["r1_games"]).season))]
    g = t.r1_games.fillna(0)
    a, b = line_fit(t.lp, g)
    return a, b


def table(df):
    return df.to_markdown(index=False) if hasattr(df, "to_markdown") else df.to_string(index=False)


INT_COLS = {"class", "n", "drafted", "played", "player-weeks", "season", "pick", "round", "actual round", "predicted round",
            "model_rank", "draft_rank", "actual_rank"}


def md(df, floatfmt=2):
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)) and not np.isnan(v) and float(v).is_integer() and (
                    str(c) in INT_COLS or str(c).startswith(("model top", "draft-order top", "hits")) or isinstance(c, (int, np.integer))):
                cells.append(str(int(v)))
            elif isinstance(v, float):
                cells.append("" if np.isnan(v) else (f"{v:.{floatfmt}f}" if abs(v) < 1000 else f"{v:,.0f}"))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


# ----------------------------------------------------------------------------- 1. holdout
def holdout(D, R):
    M = R.merge(D[["season", "gsis_id", "lp", "r1_games", "r1_ppg", "r2_games", "r2_ppg", "r1_fin", "r1_fantasy_points_ppr"]],
                on=["season", "gsis_id"], how="left")
    rows, per = [], []
    for Y in HOLD:
        for pos in POS:
            a, b = pick_curve(D, Y, pos)
            m = (M.season == Y) & (M.pos == pos)
            M.loc[m, "base_pick"] = a + b * M.loc[m, "lp"]
    H = M[M.season.isin(HOLD) & (M.r1_games >= 1)].copy()
    for pos in POS + ["All"]:
        h = H if pos == "All" else H[H.pos == pos]
        rows.append({"pos": pos, "n": len(h), "actual PPR/G": h.r1_ppg.mean(),
                     "MAE model": (h.ppg - h.r1_ppg).abs().mean(), "MAE pick curve": (h.base_pick - h.r1_ppg).abs().mean(),
                     "rank corr model": rho(h.ppg, h.r1_ppg), "rank corr pick curve": rho(h.base_pick, h.r1_ppg),
                     "bias model": (h.r1_ppg - h.ppg).mean()})
    for Y in HOLD:
        h = H[H.season == Y]
        per.append({"class": Y, "n": len(h), "MAE model": (h.ppg - h.r1_ppg).abs().mean(), "MAE pick curve": (h.base_pick - h.r1_ppg).abs().mean(),
                    "rank corr model": rho(h.ppg, h.r1_ppg), "rank corr pick curve": rho(h.base_pick, h.r1_ppg)})
    H.to_csv(os.path.join(EV, "holdout_players.csv"), index=False)
    return pd.DataFrame(rows), pd.DataFrame(per), M


def variants(D):
    """Out-of-sample miss of every competing feature set (the model uses, per class, the best on earlier classes)."""
    V = pd.read_csv(os.path.join(EV, "variants_oos.csv"), low_memory=False).merge(
        D[["season", "gsis_id", "r1_games", "r1_ppg"]], on=["season", "gsis_id"])
    V = V[(V.r1_games >= 1)]
    rows = []
    for v, h in V.groupby("variant", sort=False):
        r = {"features": v}
        for lab, ys in (("MAE 2015–18", range(2015, 2019)), ("MAE 2019–25", HOLD)):
            x = h[h.season.isin(ys)]
            r[lab] = (x.ppg - x.r1_ppg).abs().mean()
        x = h[h.season.isin(HOLD)]
        for pos in POS:
            y = x[x.pos == pos]
            r[pos] = (y.ppg - y.r1_ppg).abs().mean()
        r["rank corr 2019–25"] = rho(x.ppg, x.r1_ppg)
        rows.append(r)
    return pd.DataFrame(rows)


def share_eval(D, R):
    """Share and efficiency targets themselves (classes 2019–2025, 1+ games)."""
    M = R.merge(D, on=["season", "gsis_id"], suffixes=("", "_d"))
    M = M[M.season.isin(HOLD) & (M.r1_games >= 1)]
    rows = []
    for pos, s in (("QB", "sh_p"), ("RB", "sh_r"), ("RB", "sh_t"), ("WR", "sh_t"), ("TE", "sh_t")):
        h = M[M.pos == pos]
        base = np.full(len(h), np.nan)
        for Y in HOLD:
            t = D[(D.season < Y) & (D.pos == pos) & (D.r1_games >= 1)]
            a, b = line_fit(t.lp, t[f"r1_{s}"].fillna(0))
            mk = (h.season == Y).values
            base[mk] = a + b * h.lp.values[mk]
        act = h[f"r1_{s}"].fillna(0)
        rows.append({"pos": pos, "share": {"sh_p": "pass attempts", "sh_r": "carries", "sh_t": "targets"}[s], "n": len(h),
                     "actual mean": act.mean(), "MAE model": (h[s] - act).abs().mean(), "MAE pick only": np.nanmean(np.abs(base - act)),
                     "rank corr model": rho(h[s], act), "rank corr pick only": rho(base, act)})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- current model (backtest weeks 3–8)
def current_model(D, R, bdir, seasons=(2024, 2025, 2026), weeks=range(3, 9), rookie_prior=None):
    """Rookies in backtest_core replays of weeks 3–8: the current model vs the rookie model's static PPR/G
    (and the integrated rookie_prior, when the backtest supports it)."""
    sys.path.insert(0, os.path.join(ROOT, "backtest"))
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    cwd = os.getcwd()
    os.chdir(bdir)
    try:
        import evaluate as ev
        from ftlib import load_params_file, values
        vals = values(load_params_file())
        S_have = [S for S in seasons if all(os.path.exists(f"s{str(y)[2:]}.csv") for y in (S - 2, S - 1, S))
                  and os.path.exists(f"snaps{str(S)[2:]}.csv")]
        wk = {}
        for S in S_have:
            have = set(pd.read_csv(f"s{str(S)[2:]}.csv", low_memory=False, usecols=["week", "season_type"]).query("season_type=='REG'").week)
            wk[S] = [w for w in weeks if w in have]
        base = ev.predict(vals, wk)
        out = base.rename(columns={"pred": "cur"})
        if rookie_prior:
            for rp in rookie_prior:
                v2 = dict(vals, rookie_prior=rp)
                alt = ev.predict(v2, wk)
                out = out.merge(alt[["season", "week", "id", "pred"]].rename(columns={"pred": f"rp{rp:g}"}), on=["season", "week", "id"], how="left")
    finally:
        os.chdir(cwd)
    rk = R[["season", "gsis_id", "ppg"]].rename(columns={"gsis_id": "id", "ppg": "rookie"})
    out = out.merge(rk, on=["season", "id"], how="inner")
    return out, wk


def current_table(C):
    rows = []
    cols = [c for c in C.columns if c.startswith("rp")]
    for pos in POS + ["All"]:
        h = C if pos == "All" else C[C.pos == pos]
        r = {"pos": pos, "player-weeks": len(h), "actual": h.actual.mean(),
             "MAE current model": (h.cur - h.actual).abs().mean(), "MAE rookie model (static)": (h.rookie - h.actual).abs().mean(),
             "rank corr current": rho(h.cur, h.actual), "rank corr rookie": rho(h.rookie, h.actual)}
        for c in cols:
            r[f"MAE with rookie_prior {c[2:]}"] = (h[c] - h.actual).abs().mean()
        rows.append(r)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- 2. year 2
def year2(D, R):
    M = R.merge(D[["season", "gsis_id", "r1_games", "r1_ppg", "r2_games", "r2_ppg"]], on=["season", "gsis_id"])
    M = M[(M.r1_games >= 1) & (M.r2_games >= 1)].copy()
    rows = []
    preds = []
    for Y in range(2019, 2025):
        t = M[M.season < Y]
        p = M[M.season == Y].copy()
        if not len(p):
            continue
        for pos in POS:
            tt, mk = t[t.pos == pos], p.pos == pos
            if len(tt) < 15 or not mk.any():
                continue
            # (a) rookie season only, shrunk by games: line on r1_ppg; (b) plus the prior
            Xa = np.c_[np.ones(len(tt)), tt.r1_ppg]
            ba = np.linalg.lstsq(Xa, tt.r2_ppg, rcond=None)[0]
            Xb = np.c_[np.ones(len(tt)), tt.r1_ppg, tt.ppg]
            bb = np.linalg.lstsq(Xb, tt.r2_ppg, rcond=None)[0]
            pp = p[mk]
            p.loc[mk, "y2_a"] = np.c_[np.ones(len(pp)), pp.r1_ppg] @ ba
            p.loc[mk, "y2_b"] = np.c_[np.ones(len(pp)), pp.r1_ppg, pp.ppg] @ bb
            p.loc[mk, "w_prior"] = bb[2]
        preds.append(p)
    P = pd.concat(preds)
    for pos in POS + ["All"]:
        h = P if pos == "All" else P[P.pos == pos]
        rows.append({"pos": pos, "n": len(h), "year-2 PPR/G": h.r2_ppg.mean(),
                     "MAE rookie season only": (h.y2_a - h.r2_ppg).abs().mean(), "MAE + rookie prior": (h.y2_b - h.r2_ppg).abs().mean(),
                     "MAE prior alone": (h.ppg - h.r2_ppg).abs().mean(),
                     "rank corr rookie season": rho(h.r1_ppg, h.r2_ppg), "rank corr + prior": rho(h.y2_b, h.r2_ppg),
                     "weight on prior (2024 fit)": h[h.season == h.season.max()].w_prior.mean()})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- 3. mock draft 1 (round)
def round_of(pick, cuts):
    for r, c in enumerate(cuts, 1):
        if pick <= c:
            return r
    return len(cuts)


def mock_round(D, cache):
    dp = pd.read_csv(os.path.join(cache, "draft_picks.csv"), low_memory=False)
    cuts = {Y: list(g.groupby("round").pick.max().sort_index()) for Y, g in dp.groupby("season")}
    T0 = D[D.season >= 2015]
    out = []
    for Y in MOCK:
        pr = rm.predict_draft_slot(T0[T0.season < Y], D[D.season == Y])
        pr["pred_pick"] = np.exp(pr.lp_pred).clip(1, max(cuts[Y]))
        pr["pred_round_raw"] = [round_of(p, cuts[Y]) for p in pr.pred_pick]
        # a mock draft fills a fixed number of slots: order the class by predicted pick and give each round
        # as many of these players as it actually took
        pr = pr.sort_values("pred_pick")
        pr["pred_round"] = sorted(pr["round"].astype(int))
        out.append(pr)
    P = pd.concat(out)
    P["miss"] = P.pred_round - P["round"]
    conf = pd.crosstab(P["round"], P.pred_round).reindex(index=range(1, 8), columns=range(1, 8), fill_value=0)
    conf.index.name = "actual round"
    by = []
    for g, h in list(P.groupby("season")) + [("2021–25", P)]:
        by.append({"class": g, "n": len(h), "exact round": (h.miss == 0).mean(), "within one round": (h.miss.abs() <= 1).mean(),
                   "rank corr (pick)": rho(h.pred_pick, h.pick),
                   "within one round, unordered": ((h.pred_round_raw - h["round"]).abs() <= 1).mean()})
    bypos = []
    for pos, h in P.groupby("pos"):
        bypos.append({"pos": pos, "n": len(h), "exact round": (h.miss == 0).mean(), "within one round": (h.miss.abs() <= 1).mean(),
                      "rank corr (pick)": rho(h.pred_pick, h.pick), "mean predicted − actual round": h.miss.mean()})
    P.to_csv(os.path.join(EV, "mock_round_players.csv"), index=False)
    big = P.assign(am=P.miss.abs()).sort_values("am", ascending=False).head(12)
    big = big[["season", "name", "pos", "college", "round", "pred_round", "pick"]].rename(columns={"round": "actual round", "pred_round": "predicted round"})
    return conf, pd.DataFrame(by), pd.DataFrame(bypos), big


# ----------------------------------------------------------------------------- 4. mock draft 2 (fantasy)
def udfa(cache, D):
    """Undrafted rookies at the four positions (players.csv: rookie season, no draft round) and their seasons."""
    pl = pd.read_csv(os.path.join(cache, "players.csv"), low_memory=False)
    u = pl[pl.draft_round.isna() & pl.position.isin(POS) & pl.rookie_season.isin(MOCK)]
    rows = []
    for Y in MOCK:
        d = rm.load_stats(cache, Y)
        if d is None:
            continue
        o = rm.season_outcomes(d)
        o["pos_"] = d.drop_duplicates("player_id").set_index("player_id").position.reindex(o.index)
        o["fin"] = o.groupby("pos_").fantasy_points_ppr.rank(ascending=False, method="first")
        uy = u[u.rookie_season == Y]
        for _, r in uy.iterrows():
            if r.gsis_id in o.index:
                x = o.loc[r.gsis_id]
                rows.append({"season": Y, "pos": r.position, "r1_games": x.games, "r1_ppg": x.ppg, "r1_fin": x.fin,
                             "r1_fantasy_points_ppr": x.fantasy_points_ppr})
            else:
                rows.append({"season": Y, "pos": r.position, "r1_games": 0})
    return pd.DataFrame(rows)


def rgroup(r):
    return {1: "1", 2: "2", 3: "3"}.get(int(r), "4–7")


def mock_fantasy(D, M, cache):
    P = M[M.season.isin(MOCK)].copy()
    for Y in MOCK:
        for pos in POS:
            a, b = games_curve(D, Y, pos)
            mk = (P.season == Y) & (P.pos == pos)
            P.loc[mk, "exp_games"] = np.clip(a + b * P.loc[mk, "lp"], 0, 17)
    P["value"] = P.ppg * P.exp_games                         # projected rookie-season points
    P["actual_pts"] = P.r1_fantasy_points_ppr.fillna(0)
    P["hit"] = (P.r1_fin <= P.pos.map(HIT)).astype(float)
    P["grp"] = P["round"].map(rgroup)
    # predicted hit: projected season points at least the position's hit line in that class's season
    # (line = the HIT-th best total among all players that season, from the actual finishes)
    lines = {}
    for Y in MOCK:
        d = rm.load_stats(cache, Y)
        t = d.groupby(["player_id", "position"]).fantasy_points_ppr.sum().reset_index()
        for pos in POS:
            lines[(Y, pos)] = t[t.position == pos].fantasy_points_ppr.nlargest(HIT[pos]).min()
    P["line"] = [lines[(y, p)] for y, p in zip(P.season, P.pos)]
    P["pred_hit"] = (P.value >= P.line).astype(float)
    U = udfa(cache, D)
    rows = []
    for g in ["1", "2", "3", "4–7"]:
        for pos in POS + ["All"]:
            h = P[(P.grp == g) & ((P.pos == pos) if pos != "All" else True)]
            pl_ = h[h.r1_games >= 1]
            rows.append({"round": g, "pos": pos, "drafted": len(h), "played": len(pl_),
                         "predicted PPR/G": pl_.ppg.mean(), "actual PPR/G": pl_.r1_ppg.mean(), "actual − predicted": (pl_.r1_ppg - pl_.ppg).mean(),
                         "hit rate": h.hit.mean(), "predicted hit rate": h.pred_hit.mean()})
    for pos in POS + ["All"]:
        h = U if pos == "All" else U[U.pos == pos]
        pl_ = h[h.r1_games >= 1]
        rows.append({"round": "undrafted", "pos": pos, "drafted": len(h), "played": len(pl_), "predicted PPR/G": np.nan,
                     "actual PPR/G": pl_.r1_ppg.mean() if len(pl_) else np.nan, "actual − predicted": np.nan,
                     "hit rate": (h.r1_fin <= h.pos.map(HIT)).mean() if len(h) else np.nan, "predicted hit rate": np.nan})
    byr = pd.DataFrame(rows)
    # ranking: model vs draft order, within each class
    rk = []
    for Y, h in P.groupby("season"):
        top = 12
        m_top = h.nlargest(top, "value")
        d_top = h.nsmallest(top, "pick")
        a_top = set(h.nlargest(top, "actual_pts").gsis_id)
        rk.append({"class": Y, "n": len(h), "rank corr model": rho(h.value, h.actual_pts), "rank corr draft order": rho(-h.pick, h.actual_pts),
                   "model top 12 in actual top 12": len(set(m_top.gsis_id) & a_top), "draft-order top 12 in actual top 12": len(set(d_top.gsis_id) & a_top),
                   "hits in model top 12": int(m_top.hit.sum()), "hits in draft-order top 12": int(d_top.hit.sum())})
    rk = pd.DataFrame(rk)
    tot = {"class": "2021–25", "n": int(rk.n.sum())}
    for c in rk.columns[2:]:
        tot[c] = rk[c].mean() if "corr" in c else rk[c].sum()
    rk = pd.concat([rk, pd.DataFrame([tot])], ignore_index=True)
    P.to_csv(os.path.join(EV, "mock_fantasy_players.csv"), index=False)
    # biggest model disagreements with draft order that paid off / didn't
    P["model_rank"] = P.groupby("season").value.rank(ascending=False)
    P["draft_rank"] = P.groupby("season").pick.rank()
    P["actual_rank"] = P.groupby("season").actual_pts.rank(ascending=False)
    dis = P.assign(gap=P.draft_rank - P.model_rank).sort_values("gap")
    show = ["season", "name", "pos", "round", "pick", "model_rank", "draft_rank", "actual_rank", "ppg", "r1_ppg"]
    return byr, rk, pd.concat([dis.tail(6)[show], dis.head(6)[show]])


def biases(byr):
    out = []
    for _, r in byr.iterrows():
        if r["pos"] == "All" or r["round"] == "undrafted" or r.played < 8:
            continue
        if abs(r["actual − predicted"]) >= 1.0:
            out.append(f"round {r['round']} {r['pos']}: actual {r['actual PPR/G']:.1f} vs predicted {r['predicted PPR/G']:.1f} PPR/G "
                       f"({'under' if r['actual − predicted'] > 0 else 'over'}rated by {abs(r['actual − predicted']):.1f}, {int(r.played)} players)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--backtest-dir", default=None)
    ap.add_argument("--rookie-prior", default="", help="comma-separated rookie_prior values to replay (needs the integration)")
    a = ap.parse_args()
    os.makedirs(EV, exist_ok=True)
    D = pd.read_csv(os.path.join(rm.OUT, "players.csv"), low_memory=False)
    R = pd.read_csv(os.path.join(rm.OUT, "predictions.csv"), low_memory=False)
    out = []
    t1, t1c, M = holdout(D, R)
    t1.to_csv(os.path.join(EV, "holdout_by_position.csv"), index=False)
    t1c.to_csv(os.path.join(EV, "holdout_by_class.csv"), index=False)
    tv = variants(D)
    tv.to_csv(os.path.join(EV, "variants.csv"), index=False)
    ts = share_eval(D, R)
    ts.to_csv(os.path.join(EV, "holdout_shares.csv"), index=False)
    out += ["## Holdout: rookie PPR per game, classes 2019–2025 (each fitted on earlier classes only)", "", md(t1), "", "By class:", "", md(t1c), "",
            "Competing feature sets (out of sample; the model picks, for each class, the set with the lowest miss on all earlier classes):", "", md(tv), "",
            "The usage shares themselves (share of team carries / targets / QB attempts in games played):", "", md(ts, 3), ""]
    if a.backtest_dir:
        rps = [float(x) for x in a.rookie_prior.split(",") if x]
        C, wk = current_model(D, R, a.backtest_dir, rookie_prior=rps)
        C.to_csv(os.path.join(EV, "current_model_rookie_weeks.csv"), index=False)
        tc = current_table(C)
        tc.to_csv(os.path.join(EV, "current_model_vs_rookie.csv"), index=False)
        out += ["## Rookies in the current model (backtest replay, weeks " + ", ".join(f"{S} wk {w[0]}–{w[-1]}" for S, w in wk.items() if w)
                + ", every rookie who played)", "", md(tc), ""]
    t2 = year2(D, R)
    t2.to_csv(os.path.join(EV, "year2.csv"), index=False)
    out += ["## Year 2: second-season PPR/G (classes 2019–2024, played both seasons)", "", md(t2), ""]
    conf, by, bypos, big = mock_round(D, a.cache)
    conf.to_csv(os.path.join(EV, "mock_round_confusion.csv"))
    by.to_csv(os.path.join(EV, "mock_round_by_class.csv"), index=False)
    out += ["## Mock draft 1: NFL round from pre-draft information only (classes 2021–2025)", "",
            "Each class is ordered by predicted pick and each round gets as many of these players as it actually took (a mock draft fills fixed slots). "
            "Confusion table (rows: actual round, columns: predicted round):", "", md(conf.reset_index(), 0), "", md(by), "", md(bypos), "",
            "Biggest misses:", "", md(big, 0), ""]
    byr, rk, dis = mock_fantasy(D, M, a.cache)
    byr.to_csv(os.path.join(EV, "mock_fantasy_by_round.csv"), index=False)
    rk.to_csv(os.path.join(EV, "mock_fantasy_ranking.csv"), index=False)
    out += ["## Mock draft 2: fantasy rookie draft (classes 2021–2025)", "", "By actual NFL round:", "", md(byr), "",
            "Ranking each class (projected rookie-season points vs draft order):", "", md(rk), "",
            "Biggest disagreements with draft order (model rank much higher, then much lower):", "", md(dis, 1), "",
            "Biases flagged (|actual − predicted| ≥ 1 PPR/G, 8+ players):", ""] + [f"- {b}" for b in biases(byr)] + [""]
    open(os.path.join(EV, "summary.md"), "w").write("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
