"""Rookie-prior model: a drafted rookie's first-season usage share and efficiency from what is known right
after the NFL draft (draft slot, age, combine, college production, landing spot).

    python3 rookie/rookie_model.py fetch  --cache DIR      # downloads (nflverse + cfbfastR-data, GitHub only)
    python3 rookie/rookie_model.py build  --cache DIR      # features + outcomes -> data/rookie/players.csv
    python3 rookie/rookie_model.py fit                      # out-of-sample predictions per class + model.json
    python3 rookie/rookie_model.py eval   --cache DIR      # tables -> data/rookie/eval/, docs/rookie-model.md parts

Outputs (data/rookie/, read by pipeline/build_db.py and backtest/backtest_core.py through rookie_prior):
  players.csv      one row per drafted QB/RB/WR/TE since 2012: features and (when played) rookie outcomes
  predictions.csv  per class Y: predictions from a model fitted only on classes before Y (time-respecting);
                   the newest class uses every completed class. Columns sh_r, sh_t, sh_p (share of the team's
                   RB/WR/TE carries, RB/WR/TE targets, QB pass attempts in a game he plays, the same terms as
                   build_db's prior_share), per-opportunity efficiency (ypc, rtd, cr, ypt, rctd, ypa, ptd, ipa, cpa)
                   and ppg (rookie PPR points per game played implied by them and last season's team volume).
  model.json       the latest fit (coefficients, feature means/scales), for reading and for the draft runbook.

Shares: ridge regression per position on standardized features (every rookie who played weighted alike), with
log(pick) constrained to lower the share as the pick gets later (refit without it if its sign flips). Efficiency:
regression of each rate on log(pick) with each rookie's opportunities capped at EFF_CAP, slope shrunk toward 0.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "rookie")
sys.path.insert(0, HERE)
import college  # noqa: E402

NV = "https://github.com/nflverse/nflverse-data/releases/download"
POS = ["QB", "RB", "WR", "TE"]
FIRST_CLASS = 2012
FIRST_PRED = 2015            # first class predicted out of sample (3 classes of training before it)
TEAM = {"GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB", "LVR": "LV", "OAK": "LV",
        "SDG": "LAC", "SD": "LAC", "STL": "LA", "LAR": "LA", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE",
        "HST": "HOU"}


def tm(x):
    return TEAM.get(x, x)


# ----------------------------------------------------------------------------- fetch
def fetch(cache, last):
    os.makedirs(os.path.join(cache, "nfl"), exist_ok=True)
    os.makedirs(os.path.join(cache, "cfbstats"), exist_ok=True)
    jobs = [(f"{NV}/draft_picks/draft_picks.csv", "draft_picks.csv", True), (f"{NV}/combine/combine.csv", "combine.csv", True),
            (f"{NV}/players/players.csv", "players.csv", True)]
    for y in range(FIRST_CLASS - 1, last + 1):
        jobs.append((f"{NV}/stats_player/stats_player_week_{y}.csv", f"nfl/s{y}.csv", y >= last - 1))
        jobs.append((f"{NV}/weekly_rosters/roster_weekly_{y}.csv", f"nfl/rw{y}.csv", y >= last - 1))
        jobs.append((f"{NV}/rosters/roster_{y}.csv", f"nfl/ro{y}.csv", y >= last - 1))
    for y in range(college.FIRST_SEASON, last):
        jobs.append((college.RAW.format(y=y), f"cfbstats/ps_{y}.csv", y >= last - 2))
    for url, f, refresh in jobs:
        p = os.path.join(cache, f)
        if os.path.exists(p) and not refresh:
            continue
        r = subprocess.run(["curl", "-sSLf", "-o", p + ".tmp", url])
        if r.returncode == 0:
            os.replace(p + ".tmp", p)
        else:
            print("download failed (skipped):", url, flush=True)


# ----------------------------------------------------------------------------- outcomes
STATCOLS = ["attempts", "completions", "passing_yards", "passing_tds", "passing_interceptions", "carries", "rushing_yards",
            "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds", "fantasy_points_ppr"]


def load_stats(cache, y):
    p = os.path.join(cache, "nfl", f"s{y}.csv")
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p, low_memory=False)
    d = d[(d.season_type == "REG") & d.position.isin(POS)].copy()
    d["team"] = d.team.map(tm)
    for c in STATCOLS:
        d[c] = d[c].fillna(0)
    return d


def team_pools(d):
    """Per team: games, per-game RB/WR/TE carries and targets, QB pass attempts."""
    g = d.groupby("team").week.nunique()
    nq = d[d.position != "QB"].groupby("team")[["carries", "targets"]].sum()
    q = d[d.position == "QB"].groupby("team").attempts.sum()
    out = pd.DataFrame({"games": g, "car": nq.carries, "tgt": nq.targets, "att": q}).fillna(0)
    for c in ("car", "tgt", "att"):
        out[c] = out[c] / out.games.clip(lower=1)
    return out


def season_outcomes(d):
    """Per player: games, shares of his team's pools in games he played, totals, PPR."""
    nq = d[d.position != "QB"].groupby(["team", "week"])[["carries", "targets"]].sum().rename(columns={"carries": "tc", "targets": "tt"})
    qa = d[d.position == "QB"].groupby(["team", "week"]).attempts.sum().rename("ta")
    x = d.join(nq, on=["team", "week"]).join(qa, on=["team", "week"])
    g = x.groupby("player_id")
    o = g[STATCOLS].sum()
    o["games"] = g.size()
    o["sh_r"] = g.carries.sum() / g.tc.sum().replace(0, np.nan)
    o["sh_t"] = g.targets.sum() / g.tt.sum().replace(0, np.nan)
    o["sh_p"] = g.attempts.sum() / g.ta.sum().replace(0, np.nan)
    o["team"] = g.team.agg(lambda s: s.mode().iloc[0])
    o["ppg"] = o.fantasy_points_ppr / o.games
    return o


# ----------------------------------------------------------------------------- build
def build(cache, last):
    dp = pd.read_csv(os.path.join(cache, "draft_picks.csv"), low_memory=False)
    dp = dp[(dp.season >= FIRST_CLASS) & (dp.season <= last) & dp.position.isin(POS)].copy()
    dp["team"] = dp.team.map(tm)
    pl = pd.read_csv(os.path.join(cache, "players.csv"), low_memory=False)
    bd = pl.dropna(subset=["gsis_id", "birth_date"]).drop_duplicates("gsis_id").set_index("gsis_id").birth_date
    pfr2g = pl.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
    dp["gsis_id"] = dp.gsis_id.fillna(dp.pfr_player_id.map(pfr2g))
    cb = pd.read_csv(os.path.join(cache, "combine.csv"), low_memory=False)

    def inches(h):
        try:
            a, b = str(h).split("-")
            return int(a) * 12 + int(b)
        except Exception:
            return np.nan
    cb["ht_in"] = cb.ht.map(inches)
    cbp = cb.dropna(subset=["pfr_id"]).drop_duplicates("pfr_id").set_index("pfr_id")
    dp["ht"] = dp.pfr_player_id.map(cbp.ht_in)
    dp["wt"] = dp.pfr_player_id.map(cbp.wt)
    dp["forty"] = dp.pfr_player_id.map(cbp.forty)
    dp["vert"] = dp.pfr_player_id.map(cbp.vertical)
    # age on Sep 1 of the draft year (birth date when known, else PFR's draft age)
    b = pd.to_datetime(dp.gsis_id.map(bd), errors="coerce")
    dp["age"] = ((pd.to_datetime(dp.season.astype(str) + "-09-01") - b).dt.days / 365.25).fillna(dp.age + 0.4)
    dp["lp"] = np.log(dp.pick)
    # competition: same-position players the team drafted earlier in this class
    dp = dp.sort_values(["season", "pick"])
    dp["ahead"] = dp.groupby(["season", "team", "position"]).cumcount()

    # college production
    C = college.build(os.path.join(cache, "cfbstats"), range(college.FIRST_SEASON, last))
    M = college.match(dp.reset_index(drop=True), C) if len(C) else {}
    dp = dp.reset_index(drop=True)
    feats = []
    for i, r in dp.iterrows():
        f = {}
        if i in M:
            fin, car = M[i]
            if fin.games < 6 and len(car) > 1 and car.iloc[-2].games >= 6 and car.iloc[-2].season >= fin.season - 2:
                fin = car.iloc[-2]   # injured or opted out in his last season: use his last full one
            gms = max(fin.games, 1)
            f["c_seasons"] = len(car)
            f["c_last"] = int(fin.season)
            f["c_games"] = fin.games
            f["c_ydsh"] = fin.rec_yds / max(fin.tm_rec_yds, 1)
            f["c_tdsh"] = fin.rec_td / max(fin.tm_rec_td, 1)
            f["c_dom"] = (f["c_ydsh"] + f["c_tdsh"]) / 2
            f["c_rec_pg"] = fin.rec / gms
            f["c_recyds_pg"] = fin.rec_yds / gms
            f["c_ypr"] = fin.rec_yds / fin.rec if fin.rec >= 5 else np.nan
            f["c_rush_sh"] = fin.rush / max(fin.tm_rush, 1)
            f["c_rushyds_sh"] = fin.rush_yds / max(fin.tm_rush_yds, 1)
            f["c_scrim_sh"] = (fin.rush_yds + fin.rec_yds) / max(fin.tm_rush_yds + fin.tm_rec_yds, 1)
            f["c_ypc"] = fin.rush_yds / fin.rush if fin.rush >= 20 else np.nan
            f["c_rushyds_pg"] = fin.rush_yds / gms
            f["c_ypa"] = fin.pass_yds / fin.pass_att if fin.pass_att >= 50 else np.nan
            f["c_ptd"] = fin.pass_td / fin.pass_att if fin.pass_att >= 50 else np.nan
            f["c_int"] = fin.pass_int / fin.pass_att if fin.pass_att >= 50 else np.nan
            f["c_cmp"] = fin.pass_cmp / fin.pass_att if fin.pass_att >= 50 else np.nan
            f["c_patt_pg"] = fin.pass_att / gms
            # breakout age: first season with a 20% dominator (receivers) / 20% scrimmage share (RB) / 2,000 yards (QB),
            # known only when the window covers his freshman year
            if r.position in ("WR", "TE"):
                ok = (car.rec_yds / car.tm_rec_yds.clip(lower=1) + car.rec_td / car.tm_rec_td.clip(lower=1)) / 2 >= 0.20
            elif r.position == "RB":
                ok = (car.rush_yds + car.rec_yds) / (car.tm_rush_yds + car.tm_rec_yds).clip(lower=1) >= 0.20
            else:
                ok = car.pass_yds >= 2000
            covered = r.season - 5 >= college.FIRST_SEASON
            if ok.any():
                f["c_bo_age"] = r.age - (r.season - int(car[ok].season.min()))
            elif covered:
                f["c_bo_age"] = r.age + 1   # never broke out
        feats.append(f)
    dp = pd.concat([dp, pd.DataFrame(feats, index=dp.index)], axis=1)

    # landing spot: last season's team volume and the share of it that left (players on another team or gone in week 1)
    rows = []
    for Y in sorted(dp.season.unique()):
        prev = load_stats(cache, Y - 1)
        if prev is None:
            continue
        pools = team_pools(prev)
        rwp = os.path.join(cache, "nfl", f"rw{Y}.csv")
        wk1 = {}
        rop = os.path.join(cache, "nfl", f"ro{Y}.csv")
        if os.path.exists(rwp):
            rw = pd.read_csv(rwp, low_memory=False, usecols=["gsis_id", "week", "team", "game_type", "status"])
            rw = rw[(rw.game_type == "REG") | rw.game_type.isna()]
            w0 = rw[rw.week == rw.week.min()]
            w0 = w0[~w0.status.isin(["CUT", "RET"])]
            wk1 = dict(zip(w0.gsis_id, w0.team.map(tm)))
        elif os.path.exists(rop):
            # before the season (e.g. right after the draft) there is no week-1 roster: use the current rosters
            ro = pd.read_csv(rop, low_memory=False, usecols=["gsis_id", "team", "status"])
            ro = ro[~ro.status.isin(["CUT", "RET"])]
            wk1 = dict(zip(ro.gsis_id, ro.team.map(tm)))
        else:
            print(f"no {Y} roster: vacated opportunity unknown for the {Y} class", flush=True)
        tot = prev.groupby(["player_id", "team", "position"])[["carries", "targets", "attempts"]].sum().reset_index()
        tot["left"] = [wk1.get(p) != t for p, t in zip(tot.player_id, tot.team)]
        for T, h in tot.groupby("team"):
            nq = h[h.position != "QB"]
            q = h[h.position == "QB"]
            rows.append({"season": Y, "team": T, "pool_car": pools.loc[T, "car"], "pool_tgt": pools.loc[T, "tgt"],
                         "pool_att": pools.loc[T, "att"],
                         "vac_r": nq[nq.left].carries.sum() / max(nq.carries.sum(), 1),
                         "vac_t": nq[nq.left].targets.sum() / max(nq.targets.sum(), 1),
                         "vac_p": q[q.left].attempts.sum() / max(q.attempts.sum(), 1),
                         "vac_rb_r": nq[nq.left & (nq.position == "RB")].carries.sum() / max(nq.carries.sum(), 1)})
            if not wk1:   # unknown: missing, not "everyone left"
                rows[-1].update({"vac_r": np.nan, "vac_t": np.nan, "vac_p": np.nan, "vac_rb_r": np.nan})
    L = pd.DataFrame(rows)
    dp = dp.merge(L, on=["season", "team"], how="left")

    # outcomes: rookie season (Y) and second season (Y+1)
    out = []
    for Y in sorted(dp.season.unique()):
        for k, yy in (("r1", Y), ("r2", Y + 1)):
            d = load_stats(cache, yy)
            if d is None or (yy == last):
                continue   # the current season is in progress
            o = season_outcomes(d)
            # season rank by total PPR (finish), all players at the position
            o["pos_"] = d.drop_duplicates("player_id").set_index("player_id").position.reindex(o.index)
            o["fin"] = o.groupby("pos_").fantasy_points_ppr.rank(ascending=False, method="first")
            o = o.drop(columns="pos_")
            cls = dp[dp.season == Y]
            o = o.reindex(cls.gsis_id.dropna())
            o.columns = [f"{k}_{c}" for c in o.columns]
            o["season"] = Y
            out.append(o.reset_index().rename(columns={"player_id": "gsis_id", "index": "gsis_id"}))
    O = pd.concat(out)
    O = O.groupby(["season", "gsis_id"]).first().reset_index()
    dp = dp.merge(O, on=["season", "gsis_id"], how="left")
    keep = ["season", "round", "pick", "team", "gsis_id", "pfr_player_id", "pfr_player_name", "position", "college", "age", "lp",
            "ht", "wt", "forty", "vert", "ahead"] + [c for c in dp.columns if c.startswith(("c_", "pool_", "vac_", "r1_", "r2_"))]
    dp = dp[keep].rename(columns={"pfr_player_name": "name", "position": "pos"})
    os.makedirs(OUT, exist_ok=True)
    dp.round(5).to_csv(os.path.join(OUT, "players.csv"), index=False)
    print(f"players.csv: {len(dp)} drafted QB/RB/WR/TE, classes {dp.season.min()}–{dp.season.max()}; "
          f"college match {dp.c_games.notna().mean():.0%} (classes {college.FIRST_SEASON + 1}+: "
          f"{dp[dp.season > college.FIRST_SEASON].c_games.notna().mean():.0%}); combine 40 {dp.forty.notna().mean():.0%}")
    return dp


# ----------------------------------------------------------------------------- model
FEATS = {
    "QB": ["lp", "age", "ht", "wt", "c_ypa", "c_ptd", "c_int", "c_cmp", "c_rushyds_pg", "vac_p", "ahead"],
    "RB": ["lp", "age", "wt", "forty", "c_rush_sh", "c_scrim_sh", "c_ydsh", "c_rec_pg", "c_ypc", "vac_r", "vac_t", "pool_car", "ahead"],
    "WR": ["lp", "age", "ht", "wt", "forty", "c_dom", "c_ydsh", "c_recyds_pg", "c_ypr", "c_bo_age", "vac_t", "pool_tgt", "ahead"],
    "TE": ["lp", "age", "ht", "wt", "forty", "c_dom", "c_ydsh", "c_recyds_pg", "vac_t", "pool_tgt", "ahead"],
}
_LAND = {"QB": ["vac_p", "ahead"], "RB": ["vac_r", "vac_t", "pool_car", "ahead"], "WR": ["vac_t", "pool_tgt", "ahead"],
         "TE": ["vac_t", "pool_tgt", "ahead"]}
# Feature sets competing for each class: the one with the lowest out-of-sample miss (rookie PPR/G, players with
# 1+ games) over every earlier predicted class is used. Classes with fewer than MIN_SELECT earlier predicted
# classes use the simplest ("pick").
VARIANTS = {
    "pick": {p: ["lp"] for p in POS},
    "pick+age": {p: ["lp", "age"] for p in POS},
    "pick+landing": {p: ["lp", "age"] + _LAND[p] for p in POS},
    "pick+college": {p: [f for f in FEATS[p] if f.startswith("c_") or f in ("lp", "age")] for p in POS},
    "pick+combine": {p: [f for f in FEATS[p] if f in ("lp", "age", "ht", "wt", "forty")] for p in POS},
    "full": FEATS,
}
MIN_SELECT = 2
PREDRAFT = {   # mock draft 1: no draft slot, no landing spot
    "QB": ["age", "ht", "wt", "forty", "c_ypa", "c_ptd", "c_int", "c_cmp", "c_rushyds_pg", "c_patt_pg", "c_games"],
    "RB": ["age", "wt", "forty", "vert", "c_rush_sh", "c_scrim_sh", "c_ydsh", "c_rec_pg", "c_ypc", "c_rushyds_pg", "c_bo_age"],
    "WR": ["age", "ht", "wt", "forty", "vert", "c_dom", "c_ydsh", "c_recyds_pg", "c_ypr", "c_bo_age"],
    "TE": ["age", "ht", "wt", "forty", "vert", "c_dom", "c_ydsh", "c_recyds_pg", "c_ypr"],
}
SHARES = {"QB": ["sh_p"], "RB": ["sh_r", "sh_t"], "WR": ["sh_t", "sh_r"], "TE": ["sh_t"]}
# efficiency: (rate, numerator, denominator) per position, and the pseudo-opportunities the builder gives the prior
EFF = {
    "QB": [("ypa", "passing_yards", "attempts"), ("ptd", "passing_tds", "attempts"), ("ipa", "passing_interceptions", "attempts"),
           ("cpa", "carries", "attempts"), ("ypc", "rushing_yards", "carries"), ("rtd", "rushing_tds", "carries")],
    "RB": [("ypc", "rushing_yards", "carries"), ("rtd", "rushing_tds", "carries"), ("cr", "receptions", "targets"),
           ("ypt", "receiving_yards", "targets"), ("rctd", "receiving_tds", "targets")],
    "WR": [("cr", "receptions", "targets"), ("ypt", "receiving_yards", "targets"), ("rctd", "receiving_tds", "targets"),
           ("ypc", "rushing_yards", "carries"), ("rtd", "rushing_tds", "carries")],
    "TE": [("cr", "receptions", "targets"), ("ypt", "receiving_yards", "targets"), ("rctd", "receiving_tds", "targets"),
           ("ypc", "rushing_yards", "carries"), ("rtd", "rushing_tds", "carries")],
}
ALPHA = 4.0          # ridge penalty on standardized features (chosen on classes 2015–2018 only: 1–64 all within 0.03 pts; see docs)
EFF_CAP = 30.0       # cap on each player's opportunities in the efficiency fit (≈ every rookie counts alike; chosen on 2015–18)
EFF_SHRINK = 10.0    # slope shrink: like 10 players at EFF_CAP with no pick effect


class Ridge:
    def __init__(self, feats, alpha=ALPHA, mono=("lp", -1)):
        self.feats, self.alpha, self.mono = list(feats), alpha, mono

    def _X(self, D):
        X = D[self.feats].astype(float).copy()
        X = (X - self.mu) / self.sd
        return X.fillna(0.0).values   # missing = average

    def fit(self, D, y, w=None):
        X0 = D[self.feats].astype(float)
        self.mu = X0.mean()
        self.sd = X0.std().replace(0, 1).fillna(1)
        self.mu = self.mu.fillna(0)
        w = np.ones(len(D)) if w is None else np.asarray(w, float)
        for _ in range(2):
            X = self._X(D)
            W = w / w.mean()
            Xc = X - np.average(X, axis=0, weights=W)
            yc = y - np.average(y, weights=W)
            A = Xc.T @ (Xc * W[:, None]) + self.alpha * np.eye(X.shape[1])
            b = np.linalg.solve(A, Xc.T @ (W * yc))
            self.b = b
            self.a = float(np.average(y, weights=W) - np.average(X, axis=0, weights=W) @ b)
            if self.mono and self.mono[0] in self.feats:
                j = self.feats.index(self.mono[0])
                if np.sign(b[j]) == -self.mono[1] and b[j] != 0:
                    self.feats.pop(j)
                    self.mu, self.sd = self.mu.drop(self.mono[0]), self.sd.drop(self.mono[0])
                    continue
            break
        return self

    def predict(self, D):
        return self.a + self._X(D) @ self.b

    def to_json(self):
        return {"feats": self.feats, "mean": [round(float(x), 6) for x in self.mu[self.feats]],
                "scale": [round(float(x), 6) for x in self.sd[self.feats]], "coef": [round(float(x), 6) for x in self.b],
                "intercept": round(self.a, 6), "alpha": self.alpha}


def eff_fit(T, pos, rate, num, den):
    """Opportunity-weighted line of the rookie-season rate on log(pick), shrunk toward the position average."""
    h = T[(T.pos == pos) & (T[f"r1_{den}"] > 0)]
    if not len(h):
        return {"a": np.nan, "b": 0.0, "avg": np.nan}
    n, d = h[f"r1_{num}"].values, h[f"r1_{den}"].values
    w = np.minimum(d, EFF_CAP)
    yv = n / d
    avg = float(np.average(yv, weights=w))
    x = h.lp.values
    xm = np.average(x, weights=w)
    sxx = (w * (x - xm) ** 2).sum()
    b = (w * (x - xm) * (yv - avg)).sum() / (sxx + EFF_SHRINK * EFF_CAP * np.var(x)) if sxx > 0 else 0.0
    a = avg - b * xm
    return {"a": float(a), "b": float(b), "avg": float(avg)}


def fit_class(T, P, feats=None):
    """Fit on training classes T; predict rows P. Returns predictions frame and the fitted models."""
    preds, models = [], {}
    for pos in POS:
        tr = T[(T.pos == pos) & (T.r1_games >= 1)]
        pp = P[P.pos == pos].copy()
        if not len(pp):
            continue
        models[pos] = {"share": {}, "eff": {}}
        for s in ("sh_r", "sh_t", "sh_p"):
            if s in SHARES[pos] and len(tr) >= 20:
                y = tr[f"r1_{s}"].fillna(0).values
                fs = (feats or FEATS)[pos]
                feats_ = fs if s == SHARES[pos][0] or pos == "RB" else ["lp"]
                m = Ridge(feats_, alpha=ALPHA).fit(tr, y)   # every rookie who played counts alike (chosen on 2015–18)
                pp[s] = np.clip(m.predict(pp), 0.0, 1.0)
                models[pos]["share"][s] = m.to_json()
            else:
                pp[s] = 0.0
        for rate, num, den in EFF[pos]:
            e = eff_fit(T, pos, rate, num, den)
            pp[rate] = e["a"] + e["b"] * pp.lp
            models[pos]["eff"][rate] = e
        for rate in ("ypc", "rtd", "cr", "ypt", "rctd", "ypa", "ptd", "ipa", "cpa"):
            if rate not in pp:
                pp[rate] = 0.0
        preds.append(pp)
    return pd.concat(preds), models


def ppg(df):
    """Rookie PPR per game implied by the predicted shares, efficiency and last season's team volume."""
    car = df.sh_r * df.pool_car.fillna(df.pool_car.mean())
    tgt = df.sh_t * df.pool_tgt.fillna(df.pool_tgt.mean())
    att = df.sh_p * df.pool_att.fillna(df.pool_att.mean())
    qb = df.pos == "QB"
    qc = att * df.cpa
    p_qb = att * df.ypa * 0.04 + att * df.ptd * 4 - att * df.ipa * 2 + qc * (df.ypc * 0.1 + df.rtd * 6)
    p_sk = car * (df.ypc * 0.1 + df.rtd * 6) + tgt * (df.cr + df.ypt * 0.1 + df.rctd * 6)
    return np.where(qb, p_qb, p_sk)


OUTCOLS = ["season", "gsis_id", "name", "pos", "team", "round", "pick", "sh_r", "sh_t", "sh_p", "ypc", "rtd", "cr", "ypt",
           "rctd", "ypa", "ptd", "ipa", "cpa", "ppg", "trained_thru"]


def fit_all(last=None):
    D = pd.read_csv(os.path.join(OUT, "players.csv"), low_memory=False)
    complete = sorted(set(D.dropna(subset=["r1_games"]).season))   # classes whose rookie season is over
    last = last or int(D.season.max())
    years = [Y for Y in range(FIRST_PRED, last + 1) if len(D[D.season == Y]) and D[(D.season < Y) & D.season.isin(complete)].season.nunique() >= 3]
    oos, mods = {}, {}
    for v, F in VARIANTS.items():
        for Y in years:
            T = D[(D.season < Y) & D.season.isin(complete)]
            pr, mods[(v, Y)] = fit_class(T, D[D.season == Y], F)
            pr["ppg"] = ppg(pr)
            pr["trained_thru"] = int(T.season.max())
            oos[(v, Y)] = pr

    def miss(v, ys):
        E = pd.concat([oos[(v, y)] for y in ys])
        E = E[(E.r1_games >= 1) & E.r1_ppg.notna()]
        return float((E.ppg - E.r1_ppg).abs().mean())
    rows, sel = [], {}
    for Y in years:
        prev = [y for y in years if y < Y and y in complete]
        if len(prev) < MIN_SELECT:
            best, scores = "pick", {}
        else:
            scores = {v: round(miss(v, prev), 4) for v in VARIANTS}
            best = min(scores, key=scores.get)
        sel[Y] = {"variant": best, "validation": scores}
        rows.append(oos[(best, Y)].assign(variant=best))
    R = pd.concat(rows)
    R = R[R.gsis_id.notna()]
    R[OUTCOLS + ["variant"]].round(5).to_csv(os.path.join(OUT, "predictions.csv"), index=False)
    # every variant's out-of-sample predictions, for the evaluation tables
    pd.concat([x.assign(variant=v) for (v, Y), x in oos.items()])[OUTCOLS + ["variant"]].round(5).to_csv(
        os.path.join(OUT, "eval", "variants_oos.csv") if os.path.isdir(os.path.join(OUT, "eval")) else os.path.join(OUT, "variants_oos.csv"), index=False)
    Y = years[-1]
    json.dump({"classes": [int(x) for x in sorted(set(D.season))], "trainedThru": int(R.trained_thru.max()), "latestClass": int(last),
               "alpha": ALPHA, "effCap": EFF_CAP, "effShrink": EFF_SHRINK, "selection": {str(k): v for k, v in sel.items()},
               "variant": sel[Y]["variant"], "features": VARIANTS[sel[Y]["variant"]], "models": mods[(sel[Y]["variant"], Y)]},
              open(os.path.join(OUT, "model.json"), "w"), indent=1, default=float)
    print(f"predictions.csv: {len(R)} rows, classes {R.season.min()}–{R.season.max()}; variants used:",
          {int(k): v["variant"] for k, v in sel.items()})
    return R


def predict_draft_slot(T, P):
    """Mock draft 1: log(pick) from pre-draft features only."""
    out = []
    for pos in POS:
        tr, pp = T[T.pos == pos], P[P.pos == pos].copy()
        if len(tr) < 20 or not len(pp):
            continue
        m = Ridge(PREDRAFT[pos], mono=None).fit(tr, tr.lp.values)
        pp["lp_pred"] = m.predict(pp)
        out.append(pp)
    return pd.concat(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "build", "fit", "all"])
    ap.add_argument("--cache", default="rookie-cache")
    ap.add_argument("--last", type=int, default=None, help="newest draft class (default: this year)")
    a = ap.parse_args()
    last = a.last or pd.Timestamp.now().year
    if a.cmd in ("fetch", "all"):
        fetch(a.cache, last)
    if a.cmd in ("build", "all"):
        build(a.cache, last)
    if a.cmd in ("fit", "all"):
        fit_all(last)
