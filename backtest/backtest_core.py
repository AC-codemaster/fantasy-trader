"""Replay of the Fantasy Trader projection formula at past weeks, for backtesting.

Mirrors build_db.py (usage shares + efficiency) and engine.js (sharePts). For a target week W of
season S it uses only data from before W, then splits each team's pools among the players who
actually played in W ("oracle availability"), so it measures the formula rather than injury news.
Variants are switched on through a params dict.
"""
import json
import os

import numpy as np
import pandas as pd

POS = ["QB", "RB", "WR", "TE"]
POOLS = {"r": ("carries", ["RB", "WR", "TE"]), "t": ("targets", ["RB", "WR", "TE"]), "p": ("attempts", ["QB"])}
COLS = ["attempts", "passing_yards", "passing_tds", "passing_interceptions", "carries", "rushing_yards",
        "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds", "fl", "two"]
YOY = {
    "RB": [(24, 1.04), (25, 1.01), (26, 0.98), (27, 0.95), (28, 0.91), (29, 0.88), (99, 0.85)],
    "WR": [(23, 1.08), (24, 1.05), (25, 1.03), (26, 1.01), (27, 1.00), (28, 0.98), (29, 0.96), (30, 0.93), (31, 0.90), (99, 0.87)],
    "TE": [(24, 1.10), (25, 1.06), (26, 1.03), (27, 1.01), (28, 1.00), (29, 0.97), (30, 0.94), (31, 0.91), (99, 0.88)],
    "QB": [(25, 1.05), (26, 1.03), (27, 1.01), (32, 1.00), (33, 0.98), (34, 0.96), (35, 0.94), (36, 0.92), (99, 0.89)],
}
ANNUAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "params", "annual.json")
LOWCUT = {"QB": ("attempts", 150), "RB": ("carries", 40), "WR": ("targets", 25), "TE": ("targets", 20), "RB_rec": ("targets", 15)}
AFULL = {"QB": 300, "RB": 100, "WR": 60, "TE": 45, "RB_rec": 40}
if os.path.exists(os.environ.get("FT_ANNUAL") or ANNUAL_FILE):   # yearly-refitted constants (the literals above are version 1)
    _A = json.load(open(os.environ.get("FT_ANNUAL") or ANNUAL_FILE))
    YOY = {k: [tuple(x) for x in v] for k, v in _A.get("yoy", {}).items()} or YOY
    if "low_volume" in _A:
        LOWCUT = {k: tuple(v) for k, v in _A["low_volume"]["lowcut"].items()}
        AFULL = dict(_A["low_volume"]["afull"])
VET_AGE = {"RB": 28, "WR": 30, "TE": 30, "QB": 35}
QB_PRIOR = {1: 0.95, 2: 0.04, 3: 0.01}
CUR_OK = ("ACT", "INA", "RES", "EXE")
BASE = dict(prior_games=3.0, prior_moved=1.5, vet_prior=0.6, team_prior=3.0, w1=0.8, w2=0.4, decay=1.0,
            K=dict(ypa=150, ptd=250, int=300, ypc=100, rtd=150, cr=40, ypt=60, rectd=120, cpa=150, fl=250, two=400),
            env=None, qb_iters=300, low_target=0.0, damp=0.0, ret_disc=1.0, prior_track=0.0, blend2=0.0, rookie_prior=0.0,
            yoy=None, low_volume=None)   # yoy / low_volume: annual-refit challengers (None = params/annual.json)
# rookie prior (same as build_db.py): pseudo-opportunities per unit of rookie_prior at the rookie model's rates
ROOKIE_OPPS = {"QB": {"attempts": 150}, "RB": {"carries": 60, "targets": 20}, "WR": {"targets": 40}, "TE": {"targets": 30}}
ROOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "rookie", "predictions.csv")


def load_rookies(S, path=None):
    """{gsis_id: row} of the rookie model's predictions for class S (fitted on earlier classes only)."""
    path = path or os.environ.get("FT_ROOKIES") or ROOKIE_FILE
    if not os.path.exists(path):
        return {}
    rk = pd.read_csv(path, low_memory=False)
    return {r.gsis_id: r._asdict() for r in rk[rk.season == S].itertuples(index=False)}


def rookie_pseudo(rk, pos, rp, lg):
    """Pseudo-counts the rookie prior adds to a rookie's efficiency history ({} when off)."""
    if rp <= 0 or rk is None:
        return {}
    n = {k: rp * v for k, v in ROOKIE_OPPS.get(pos, {}).items()}
    if pos == "QB":
        a = n.get("attempts", 0.0)
        qc = a * rk["cpa"]
        out = {"attempts": a, "passing_yards": a * rk["ypa"], "passing_tds": a * rk["ptd"], "passing_interceptions": a * rk["ipa"],
               "carries": qc, "rushing_yards": qc * rk["ypc"], "rushing_tds": qc * rk["rtd"]}
    else:
        c, t = n.get("carries", 0.0), n.get("targets", 0.0)
        out = {"carries": c, "rushing_yards": c * rk["ypc"], "rushing_tds": c * rk["rtd"], "targets": t,
               "receptions": t * rk["cr"], "receiving_yards": t * rk["ypt"], "receiving_tds": t * rk["rctd"]}
    opp = out.get("carries", 0.0) + out.get("targets", 0.0) + (out.get("attempts", 0.0) if pos == "QB" else 0.0)
    lg_opp = (lg.loc[pos, "attempts"] + lg.loc[pos, "carries"]) if pos == "QB" else (lg.loc[pos, "carries"] + lg.loc[pos, "targets"])
    out["fl"] = opp * lg.loc[pos, "fl"] / max(lg_opp, 1)
    out["two"] = opp * lg.loc[pos, "two"] / max(lg_opp, 1)
    return out


def yoy(pos, age, table=None):
    if age is None or (isinstance(age, float) and np.isnan(age)):
        return 1.0
    for a, f in (table or YOY)[pos]:
        if age <= a:
            return f
    return 1.0


def load_stats(y):
    d = pd.read_csv(f"s{str(y)[2:]}.csv", low_memory=False)
    d = d[(d.season_type == "REG") & d.position.isin(POS)].copy()
    d["fl"] = d[["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]].fillna(0).sum(axis=1)
    d["two"] = d[["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"]].fillna(0).sum(axis=1)
    d["week"] = d.week.astype(int)
    return d


def status_map(y):
    rr = pd.read_csv(f"r{str(y)[2:]}.csv", low_memory=False, usecols=["gsis_id", "week", "team", "status", "position", "birth_date", "full_name"])
    return rr


def fit_luce(rows, games, smap, tm, col, here, u0=None, n=None, iters=300, decay=1.0, last=None):
    """Vectorised MM fit of share weights (same model as build_db.fit_luce).
    rows: player-game stats for this team & pool positions; games: sorted weeks."""
    u0, n = u0 or {}, n or {}
    here = sorted(p for p in here if isinstance(p, str))
    if not here or not games:
        return {}, {}, 0, 0.0
    idx = {p: i for i, p in enumerate(here)}
    gi = {w: j for j, w in enumerate(games)}
    X = np.zeros((len(here), len(games)))
    agg = rows.groupby(["player_id", "week"])[col].sum()
    for (pid, w), v in agg.items():
        if pid in idx and w in gi:
            X[idx[pid], gi[w]] = v
    has = np.zeros_like(X, dtype=bool)
    for (pid, w) in agg.index:
        if pid in idx and w in gi:
            has[idx[pid], gi[w]] = True
    P = has.copy()
    for i, pid in enumerate(here):
        for j, w in enumerate(games):
            if not P[i, j]:
                st = smap.get((pid, w))
                if st and st[0] == tm and st[1] == "ACT":
                    P[i, j] = True
    # hurt early in a game and on reserve the next week: absent for that game
    for i, pid in enumerate(here):
        for j, w in enumerate(games):
            if P[i, j]:
                nxt = smap.get((pid, w + 1))
                if nxt and nxt[1] == "RES":
                    others = [X[i, k] for k in range(len(games)) if k != j and has[i, k]]
                    if others and X[i, j] < 0.4 * np.mean(others):
                        P[i, j] = False
    X = X * P
    C = X.sum(axis=0)
    wts = np.array([decay ** ((last if last is not None else games[-1]) - w) for w in games])
    tot = C.sum() or 1.0
    U0 = np.array([u0.get(p, 0.0) for p in here])
    N = np.array([n.get(p, 0.0) for p in here])
    u = np.maximum(np.maximum(U0, X.sum(axis=1) / tot), 1e-3)
    num = (X * wts).sum(axis=1) + N * U0
    for _ in range(iters):
        D = (P * u[:, None]).sum(axis=0)
        ratio = np.where(D > 0, C / np.where(D > 0, D, 1), 0.0) * wts
        den = (P * ratio[None, :]).sum(axis=1) + N
        u = np.where(den > 0, num / np.where(den > 0, den, 1), 0.0)
    pg = P.sum(axis=1)
    ed = float((u * pg).sum() / max(len(games), 1))
    return {p: float(u[idx[p]]) for p in here}, {p: int(pg[idx[p]]) for p in here}, len(games), ed


class Season:
    """Everything for replaying season S."""

    def __init__(self, S, params=None):
        self.S = S
        self.st = {y: load_stats(y) for y in (S - 2, S - 1, S)}
        self.ro = {y: status_map(y) for y in (S - 2, S - 1, S)}
        self.smap = {y: {(r.gsis_id, int(r.week)): (r.team, r.status) for r in self.ro[y].itertuples()} for y in self.ro}
        rs = self.ro[S].dropna(subset=["birth_date"]).drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
        start = pd.Timestamp(f"{S}-09-01")
        self.ages = {}
        for pid, bd in rs.birth_date.items():
            try:
                self.ages[pid] = int((start - pd.Timestamp(bd)).days // 365.25)
            except Exception:
                pass
        self.tot = {y: self._totals(self.st[y]) for y in (S - 2, S - 1)}
        self.prior = {y: self._season_shares(y) for y in (S - 2, S - 1)}
        g = pd.read_csv("games.csv", low_memory=False)
        self.games = g[(g.season == S) & (g.game_type == "REG")].copy()
        self._dc = None
        self._rookies = None
        sn = pd.read_csv(f"snaps{str(S)[2:]}.csv", low_memory=False)
        ids = pd.read_csv("db_playerids.csv" if os.path.exists("db_playerids.csv") else "../db_playerids.csv", low_memory=False)
        pfr2g = ids.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id.to_dict()
        sn = sn[sn.game_type == "REG"] if "game_type" in sn else sn
        sn = sn.assign(gsis=sn.pfr_player_id.map(pfr2g)).dropna(subset=["gsis"])
        self.snaps = {(r.gsis, int(r.week)): r.offense_snaps for r in sn.itertuples() if r.offense_snaps > 0}
        self.played_set = set((r.player_id, int(r.week)) for r in self.st[S][['player_id', 'week']].itertuples()) | set(self.snaps.keys())
        self.lines = {}
        self.opp = {}
        for _, r in self.games.iterrows():
            self.opp[(r.home_team, int(r.week))] = r.away_team; self.opp[(r.away_team, int(r.week))] = r.home_team
        for _, r in self.games.iterrows():
            for tm, home in ((r.home_team, 1), (r.away_team, 0)):
                sp = r.spread_line if home else -r.spread_line
                if pd.notna(r.total_line):
                    self.lines[(tm, int(r.week))] = dict(implied=r.total_line / 2 + sp / 2, spread=sp, wind=r.wind, roof=r.roof, home=home)

    @staticmethod
    def _totals(d):
        t = d.groupby("player_id")[COLS].sum()
        t["g"] = d.groupby("player_id").size()
        return t

    def _season_shares(self, y):
        d = self.st[y]
        out = {}
        for tm in sorted(set(d.team)):
            for c, (col, poss) in POOLS.items():
                if c == "p":
                    continue
                rows = d[(d.team == tm) & d.position.isin(poss)]
                games = sorted(set(int(w) for w in d[d.team == tm].week))
                u, pg, ng, ed = fit_luce(rows, games, self.smap[y], tm, col, set(rows.player_id), iters=200)
                for pid, v in u.items():
                    if pg[pid] and ed > 0:
                        prev = out.get((c, pid))
                        if prev is None or pg[pid] > prev[1]:
                            out[(c, pid)] = (v / ed, pg[pid], tm)
        return out

    def qb_depth(self, W):
        """QB depth order at week W from the depth charts available before that week's games."""
        y = self.S
        if self._dc is None:
            self._dc = pd.read_csv(f"dc{str(y)[2:]}.csv", low_memory=False)
        dc = self._dc
        if "dt" in dc.columns:
            day = self.games[self.games.week == W].gameday.min()
            q = dc[(dc.pos_abb == "QB") & (dc.dt.astype(str).str[:10] < str(day))]
            if not len(q):
                return {}
            q = q[q.dt == q.dt.max()]
            return {(r.team, r.gsis_id): int(r.pos_rank) for r in q.itertuples() if isinstance(r.gsis_id, str)}
        q = dc[(dc.week == W) & (dc.position == "QB") & (dc.formation == "Offense") & (dc.game_type == "REG")]
        return {(r.club_code, r.gsis_id): int(r.depth_team) for r in q.itertuples() if isinstance(r.gsis_id, str)}

    def project(self, W, params=None):
        """Projected PPR components for every player who played in week W of season S."""
        P = dict(BASE)
        P.update(params or {})
        S = self.S
        cur = self.st[S][self.st[S].week < W]
        nxt = self.st[S][self.st[S].week == W]
        roW = self.ro[S][self.ro[S].week == W]
        roW = roW[roW.position.isin(POS) & roW.gsis_id.notna()].drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
        smap = self.smap[S]
        lg = pd.concat([self.st[S - 2], self.st[S - 1], cur]).groupby("position")[COLS].sum()
        # league rates among low-volume players (season totals below a threshold), the shrink target for thin samples
        YT = P["yoy"] or YOY
        LV = P["low_volume"] or {"lowcut": LOWCUT, "afull": AFULL}
        lowcut = {k: tuple(v) for k, v in LV["lowcut"].items()}
        seas = []
        for y_, d_ in ((S - 2, self.st[S - 2]), (S - 1, self.st[S - 1])):
            seas.append(d_.groupby(["player_id", "position"])[COLS].sum().reset_index())
        allt = pd.concat(seas)
        lg_low = {}
        for key_, (col_, cut_) in lowcut.items():   # RB_rec: RB receiving uses a target cut instead
            pos_ = "RB" if key_ == "RB_rec" else key_
            x_ = allt[(allt.position == pos_) & (allt[col_] > 0) & (allt[col_] <= cut_)]
            lg_low[key_] = x_[COLS].sum()
        AFULL_ = LV["afull"]
        tc = self._totals(cur) if len(cur) else pd.DataFrame(columns=COLS + ["g"])
        t1, t2 = self.tot[S - 1], self.tot[S - 2]
        pr1, pr2 = self.prior[S - 1], self.prior[S - 2]
        ages = self.ages
        # team pools
        pool_game = {c: cur[cur.position.isin(poss)].groupby(["team", "week"])[col].sum() for c, (col, poss) in POOLS.items()}
        lg_pool = {c: float(pool_game[c].mean()) if len(pool_game[c]) else 1.0 for c in POOLS}
        teams = sorted(set(roW.team))
        team_pool = {}
        for tm in teams:
            team_pool[tm] = {}
            for c in POOLS:
                vals = pool_game[c][tm] if tm in pool_game[c].index.get_level_values(0) else pd.Series(dtype=float)
                team_pool[tm][c] = float((vals.sum() + P["team_prior"] * lg_pool[c]) / (len(vals) + P["team_prior"]))
        qbd = self.qb_depth(W)
        RP = float(P.get("rookie_prior", 0.0))
        if RP > 0 and self._rookies is None:
            self._rookies = load_rookies(S)
        ROOK = self._rookies if RP > 0 else {}

        def prior_share(pid, pos, c):
            age = ages.get(pid)
            f1 = yoy(pos, age, YT)
            f2 = f1 * yoy(pos, age - 1 if age else None, YT)
            a1, a2 = pr1.get((c, pid)), pr2.get((c, pid))
            num = den = 0.0
            if a1:
                num += a1[0] * a1[1] * np.sqrt(f1); den += a1[1]
            if a2 and (not a1 or a1[1] < 6):
                num += a2[0] * a2[1] * np.sqrt(f2); den += a2[1]
            elif a2 and P["blend2"] > 0:
                num += P["blend2"] * a2[0] * a2[1] * np.sqrt(f2); den += P["blend2"] * a2[1]
            return (num / den) if den else None

        def prior_strength(pid, pos, team, c):
            a1, a2 = pr1.get((c, pid)), pr2.get((c, pid))
            if not a1 and not a2:
                return 0.0
            k = P["prior_moved"] if (a1 or a2)[2] != team else P["prior_games"]
            age = ages.get(pid)
            if age is not None and age >= VET_AGE[pos]:
                k *= P["vet_prior"]
            if P["prior_track"] > 0:
                gt = (a1[1] if a1 else 0) + 0.5 * (a2[1] if a2 else 0)
                k *= 1 + P["prior_track"] * min(1.0, gt / 17.0)
            return k

        U = {c: {} for c in POOLS}
        for tm in teams:
            members = roW[(roW.team == tm) & roW.status.isin(CUR_OK)]
            games = sorted(set(int(w) for w in cur[cur.team == tm].week))
            for c, (col, poss) in POOLS.items():
                cset = set(members[members.position.isin(poss)].index)
                u0, n = {}, {}
                for pid in cset:
                    pos = members.loc[pid].position
                    if c == "p":
                        rk = qbd.get((tm, pid))
                        if rk in QB_PRIOR:
                            u0[pid], n[pid] = QB_PRIOR[rk], P["prior_games"] * team_pool[tm][c]
                        continue
                    v = prior_share(pid, pos, c)
                    k = prior_strength(pid, pos, tm, c)
                    if v is not None and k > 0:
                        u0[pid], n[pid] = v, k * team_pool[tm][c]
                    elif RP > 0 and pid in ROOK and ROOK[pid]["sh_" + c] > 0:
                        u0[pid], n[pid] = ROOK[pid]["sh_" + c], RP * P["prior_games"] * team_pool[tm][c]
                tot0 = sum(u0.values())
                if tot0 > 1:
                    u0 = {k_: v / tot0 for k_, v in u0.items()}
                rows = cur[(cur.team == tm) & cur.position.isin(poss)]
                here = set(rows.player_id) | cset
                if games:
                    u, _, _, _ = fit_luce(rows, games, smap, tm, col, here, u0, n, iters=P["qb_iters"], decay=P["decay"], last=W - 1)
                else:
                    tot = sum(u0.values()) or 1.0
                    u = {k_: v for k_, v in u0.items()}
                for pid in here:
                    U[c][(tm, pid)] = u.get(pid, 0.0)
        # efficiency
        K = P["K"]
        lgq = lg.loc["QB"]

        def efficiency(pid, pos):
            a = tc.loc[pid] if pid in tc.index else None
            b = t1.loc[pid] if pid in t1.index else None
            c2 = t2.loc[pid] if pid in t2.index else None
            age = ages.get(pid)
            f1 = yoy(pos, age, YT)
            f2 = f1 * yoy(pos, age - 1 if age else None, YT)
            vet = P["vet_prior"] if (age is not None and age >= VET_AGE[pos]) else 1.0
            scaled = {"passing_yards", "passing_tds", "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds"}
            rk_add = rookie_pseudo(ROOK.get(pid), pos, RP, lg) if ROOK else {}

            def h(col, real=False):
                x = a[col] if a is not None else 0.0
                if b is not None:
                    x += P["w1"] * vet * b[col] * (np.sqrt(f1) if col in scaled else 1.0)
                if c2 is not None:
                    x += P["w2"] * vet * c2[col] * (np.sqrt(f2) if col in scaled else 1.0)
                if rk_add and not real:
                    x += rk_add.get(col, 0.0)
                return x

            def sh(num, den, k):
                lr = lg.loc[pos, num] / max(lg.loc[pos, den], 1)
                if P["low_target"] > 0:
                    key = "RB_rec" if (pos == "RB" and den == "targets") else pos
                    lo = lg_low[key]
                    lr_low = lo[num] / max(lo[den], 1)
                    w_ = min(1.0, h(den, real=True) / (AFULL_[key] * P["low_target"]))
                    lr = lr_low + (lr - lr_low) * w_
                return (h(num) + k * lr) / (h(den) + k)

            def sh2(nv, dv, k, lr):
                return (nv + k * lr) / (dv + k)
            opp_skill = h("carries") + h("targets")
            if pos == "QB":
                opp = h("attempts") + h("carries")
                lg_opp = lgq["attempts"] + lgq["carries"]
                return dict(ypa=sh("passing_yards", "attempts", K["ypa"]), ptd=sh("passing_tds", "attempts", K["ptd"]),
                            ipa=sh("passing_interceptions", "attempts", K["int"]),
                            cpa=sh2(h("carries"), h("attempts"), K["cpa"], lgq["carries"] / lgq["attempts"]),
                            ypc=sh("rushing_yards", "carries", K["ypc"]), rtd=sh("rushing_tds", "carries", K["rtd"]),
                            cr=0.0, ypt=0.0, rctd=0.0,
                            fl=sh2(h("fl"), opp, K["fl"], lgq["fl"] / lg_opp), two=sh2(h("two"), opp, K["two"], lgq["two"] / lg_opp))
            lg_opp_skill = lg.loc[pos, "carries"] + lg.loc[pos, "targets"]
            return dict(ypa=0.0, ptd=0.0, ipa=0.0, cpa=0.0, ypc=sh("rushing_yards", "carries", K["ypc"]), rtd=sh("rushing_tds", "carries", K["rtd"]),
                        cr=sh("receptions", "targets", K["cr"]), ypt=sh("receiving_yards", "targets", K["ypt"]),
                        rctd=sh("receiving_tds", "targets", K["rectd"]),
                        fl=sh2(h("fl"), opp_skill, K["fl"], lg.loc[pos, "fl"] / lg_opp_skill),
                        two=sh2(h("two"), opp_skill, K["two"], lg.loc[pos, "two"] / lg_opp_skill))

        # who played in W (oracle availability)
        played = {}
        for r in nxt.itertuples():
            played[r.player_id] = r.team
        for (pid, w), sn in self.snaps.items():
            if w == W and pid in roW.index:
                played.setdefault(pid, roW.loc[pid].team)
        out = []
        env = P.get("env")
        for tm in teams:
            ids = [pid for pid, t in played.items() if t == tm]
            prevw = max([w for w in range(1, W) if (tm, w) in self.opp] or [0])
            def back(pid):
                return P["ret_disc"] if (prevw and (pid, prevw) not in self.played_set) else 1.0
            uu = {c: {pid: U[c].get((tm, pid), 0.0) * back(pid) for pid in ids} for c in POOLS}
            D = {c: sum(uu[c].values()) for c in POOLS}
            healthy = set(roW[(roW.team == tm) & roW.status.isin(['ACT', 'INA'])].index) | set(ids)
            Dall = {c: sum(U[c].get((tm, pid), 0.0) for pid in healthy) for c in POOLS}
            if P["damp"] > 0:
                D = {c: D[c] + (P["damp"] * max(0.0, Dall[c] - D[c]) if c != "p" else 0.0) for c in POOLS}
            T = dict(team_pool[tm])
            mult = dict(ypa=1, ptd=1, ypc=1, rtd=1, ypt=1, rctd=1)
            ln = self.lines.get((tm, W))
            if env and ln:
                # relative to the team's usual implied total in games before W (fallback: league average)
                prev = [self.lines[(tm, w)]["implied"] for w in range(1, W) if (tm, w) in self.lines]
                lgavg = np.mean([v["implied"] for k_, v in self.lines.items() if k_[1] < W] or [22.0])
                usual = (sum(prev) + env.get("k_usual", 3) * lgavg) / (len(prev) + env.get("k_usual", 3))
                x = ln["implied"] / usual - 1
                s = ln["spread"]
                T["p"] *= np.exp(env["att_i"] * x + env["att_s"] * s)
                T["t"] *= np.exp(env["att_i"] * x + env["att_s"] * s)
                T["r"] *= np.exp(env["car_i"] * x + env["car_s"] * s)
                mult["ypa"] = mult["ypt"] = np.exp(env["pyd_i"] * x + env["pyd_s"] * s - env["att_i"] * x - env["att_s"] * s)
                mult["ptd"] = mult["rctd"] = np.exp(env["ptd_i"] * x + env["ptd_s"] * s - env["att_i"] * x - env["att_s"] * s)
                mult["ypc"] = np.exp(env["ryd_i"] * x + env["ryd_s"] * s - env["car_i"] * x - env["car_s"] * s)
                mult["rtd"] = np.exp(env["rtd_i"] * x + env["rtd_s"] * s - env["car_i"] * x - env["car_s"] * s)
                if env.get("wind") and pd.notna(ln["wind"]) and ln["wind"] >= 15 and ln["roof"] not in ("dome", "closed"):
                    mult["ypa"] *= np.exp(env["wind"]); mult["ypt"] *= np.exp(env["wind"])
            for pid in ids:
                if pid not in roW.index:
                    continue
                pos = roW.loc[pid].position
                ur, ut, up = uu["r"][pid], uu["t"][pid], uu["p"][pid]
                car = T["r"] * ur / D["r"] if D["r"] > 0 else 0.0
                tgt = T["t"] * ut / D["t"] if D["t"] > 0 else 0.0
                att = T["p"] * up / D["p"] if D["p"] > 0 else 0.0
                e = efficiency(pid, pos)
                if pos == "QB":
                    qc = att * e["cpa"]
                    comp = dict(py=att * e["ypa"] * mult["ypa"], ptd=att * e["ptd"] * mult["ptd"], int=att * e["ipa"],
                                ry=qc * e["ypc"] * mult["ypc"], rtd=qc * e["rtd"] * mult["rtd"], rec=0, recy=0, rectd=0,
                                fl=(att + qc) * e["fl"], two=(att + qc) * e["two"])
                else:
                    comp = dict(py=0, ptd=0, int=0, ry=car * e["ypc"] * mult["ypc"], rtd=car * e["rtd"] * mult["rtd"],
                                rec=tgt * e["cr"], recy=tgt * e["ypt"] * mult["ypt"], rectd=tgt * e["rctd"] * mult["rctd"],
                                fl=(car + tgt) * e["fl"], two=(car + tgt) * e["two"])
                pts = (comp["py"] * 0.04 + comp["ptd"] * 4 - comp["int"] * 2 + comp["ry"] * 0.1 + comp["rtd"] * 6
                       + comp["rec"] + comp["recy"] * 0.1 + comp["rectd"] * 6 - comp["fl"] * 2 + comp["two"] * 2)
                out.append(dict(id=pid, season=S, week=W, team=tm, pos=pos, pred=pts, car=car, tgt=tgt, att=att,
                                g_cur=int(tc.loc[pid].g) if pid in tc.index else 0, age=ages.get(pid),
                                qbrank=qbd.get((tm, pid)), ur=ur, ut=ut, up=up,
                                boost_r=Dall['r'] / D['r'] if D['r'] > 0 else 1, boost_t=Dall['t'] / D['t'] if D['t'] > 0 else 1, boost_p=Dall['p'] / D['p'] if D['p'] > 0 else 1,
                                opp=self.opp.get((tm, W)), implied=ln['implied'] if ln else np.nan, spread=ln['spread'] if ln else np.nan,
                                # expected stat line (the components behind pred): the start/sit distributions are fitted on these
                                qc=att * e["cpa"] if pos == "QB" else 0.0, **{"c_" + k: v for k, v in comp.items()}))
        R = pd.DataFrame(out)
        act = nxt.groupby("player_id").agg(actual=("fantasy_points_ppr", "sum"), a_car=("carries", "sum"), a_tgt=("targets", "sum"),
                                           a_att=("attempts", "sum"))
        R = R.join(act, on="id")
        R[["actual", "a_car", "a_tgt", "a_att"]] = R[["actual", "a_car", "a_tgt", "a_att"]].fillna(0)
        return R
