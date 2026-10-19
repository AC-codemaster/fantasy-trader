"""Kickers and team defenses (D/ST): data, projections and fantasy points.

One implementation, used by the builder (pipeline/build_db.py: this season's weekly projections), the backtest
(backtest/kdst_backtest.py: the same projections replayed at past weeks, which the improvement loop tunes) and
the scorecard (pipeline/scorecard.py: actual points for grading). The page's engine only scores the expected
stat lines built here, with each league's own scoring.

Kicker, per game:  PAT attempts and field-goal attempts from his team's Vegas implied total (more points, more
  PATs; field-goal volume is nearly flat), times a shrunk team factor (some coaches kick more); attempts split
  by distance (league mix, shrunk toward his own); made and missed by distance at his make rates, shrunk toward
  the league's rate at each distance.
D/ST, per game:  sacks, interceptions and fumble recoveries at the league rate for the opponent's implied total
  (log-linear: a weak offense gives up more), times the defense's own factor and the opponent offense's factor
  (both shrunk); safeties at the league rate; blocked kicks and return TDs at the league rate times a heavily
  shrunk team factor; defensive TDs as a share of takeaways. Points allowed: the opponent's implied total plus
  the spread of real scores around it (empirical, from past games), so each points-allowed tier gets a
  probability. Yards allowed: a line on the opponent's implied total plus each side's shrunk yardage tendency,
  with a normal spread.
History: this season counts 1, last season W_PREV, the one before W_PREV²; league constants are fitted on every
completed game in the history window that has a Vegas line.

Points allowed (ESPN): the opponent's points minus its defensive touchdowns (a pick-six against your offense
isn't your defense's fault; return touchdowns against your special teams count), 7 per touchdown.
Yards allowed: the opponent's net offensive yards (passing minus sack yardage, plus rushing).
"""
import math
import re

import numpy as np
import pandas as pd

K_COMP = ["patM", "patX", "fg0", "fg40", "fg50", "fg60", "fx0", "fx40", "fx50"]
D_EVT = ["sk", "it", "fr", "sf", "dtd", "sttd", "blk"]
D_COMP = D_EVT + ["pa", "ya"] + [f"pa{i}" for i in range(9)] + [f"ya{i}" for i in range(9)]
PA_EDGES = [0, 1, 7, 14, 18, 22, 28, 35, 46]                  # tier i: PA_EDGES[i] .. PA_EDGES[i+1]-1 (ESPN)
YA_EDGES = [-1e9, 100, 200, 300, 350, 400, 450, 500, 550]     # tier i: YA_EDGES[i] .. YA_EDGES[i+1)
BUCKETS = ["0", "40", "50", "60"]                              # field goals 0-39, 40-49, 50-59, 60+
# ESPN standard scoring (support.espn.com "Scoring Formats"; yards-allowed tiers as in ESPN's default leagues).
# The engine's DEFAULT_SETTINGS.scoring holds the same numbers (tests check they agree).
STANDARD = {
    "patMade": 1, "patMiss": 0, "fg0": 3, "fg40": 4, "fg50": 5, "fg60": 6, "fgMiss": -1, "fgMiss0": 0, "fgMiss40": 0, "fgMiss50": 0,
    "sack": 1, "dInt": 2, "fumRec": 2, "safety": 2, "dTd": 6, "stTd": 6, "blk": 2, "ptsAllowed": 0, "ydsAllowed": 0,
    "paTier": [5, 4, 3, 1, 0, 0, -1, -3, -5], "yaTier": [5, 3, 2, 0, -1, -3, -5, -6, -7],
}
# Tunable settings (params/params.json, eval "kdst"; these are the neutral fallbacks, set from an Oct 2026 sweep
# on the 2024-26 backtest): shrink strengths in attempts (k_fg, k_pat, k_mix, k_kvol, k_pvol) or games of
# league-average play (k_dst, k_off, k_st, k_ya), last-season weights, and a scale on the points-allowed spread.
DEFAULTS = dict(k_fg=40.0, k_pat=20.0, k_mix=30.0, k_kvol=40.0, k_pvol=20.0, w_kprev=0.8,
                k_dst=10.0, k_off=10.0, k_st=40.0, k_ya=40.0, w_dprev=0.5, pa_scale=1.0)
IMP0 = 22.0   # implied total the league constants are centered on


# ----------------------------------------------------------------------------- scoring
def k_points(v, sc=STANDARD):
    """Fantasy points from a kicker component vector (K_COMP order)."""
    pm, px, f0, f4, f5, f6, x0, x4, x5 = v
    return (pm * sc["patMade"] + px * sc["patMiss"] + f0 * sc["fg0"] + f4 * sc["fg40"] + f5 * sc["fg50"] + f6 * sc["fg60"]
            + (x0 + x4 + x5) * sc["fgMiss"] + x0 * sc["fgMiss0"] + x4 * sc["fgMiss40"] + x5 * sc["fgMiss50"])


def d_points(v, sc=STANDARD):
    """Fantasy points from a D/ST component vector (D_COMP order)."""
    sk, it, fr, sf, dtd, sttd, blk, pa, ya = v[:9]
    s = (sk * sc["sack"] + it * sc["dInt"] + fr * sc["fumRec"] + sf * sc["safety"] + dtd * sc["dTd"] + sttd * sc["stTd"]
         + blk * sc["blk"] + pa * sc["ptsAllowed"] + ya * sc["ydsAllowed"])
    s += sum(v[9 + i] * sc["paTier"][i] for i in range(9)) + sum(v[18 + i] * sc["yaTier"][i] for i in range(9))
    return s


def pa_tier(pa):
    return max(i for i in range(9) if pa >= PA_EDGES[i])


def ya_tier(ya):
    return max(i for i in range(9) if ya >= YA_EDGES[i])


# ----------------------------------------------------------------------------- history tables
def _bucket(dist):
    d = float(dist)
    return 0 if d < 40 else 1 if d < 50 else 2 if d < 60 else 3


def _dists(x):
    if not isinstance(x, str) or not x.strip():
        return []
    return [float(t) for t in re.split(r"[;,\s]+", x.strip()) if t]


def kicker_games(stats):
    """One row per kicker-game: PATs and field goals made/missed by distance (blocked kicks count as misses)."""
    d = stats[(stats.season_type == "REG") & ((stats.fg_att.fillna(0) > 0) | (stats.pat_att.fillna(0) > 0))].copy()
    out = pd.DataFrame({"season": d.season.astype(int), "week": d.week.astype(int), "id": d.player_id, "name": d.player_display_name,
                        "team": d.team, "pos": d.position})
    f = lambda c: d[c].fillna(0).astype(float).values  # noqa: E731
    out["patM"] = f("pat_made")
    out["patX"] = f("pat_att") - f("pat_made")
    out["fg0"] = f("fg_made_0_19") + f("fg_made_20_29") + f("fg_made_30_39")
    out["fg40"], out["fg50"], out["fg60"] = f("fg_made_40_49"), f("fg_made_50_59"), f("fg_made_60_")
    miss = np.zeros((len(d), 4))
    miss[:, 0] = f("fg_missed_0_19") + f("fg_missed_20_29") + f("fg_missed_30_39")
    miss[:, 1], miss[:, 2], miss[:, 3] = f("fg_missed_40_49"), f("fg_missed_50_59"), f("fg_missed_60_")
    for i, lst in enumerate(d.fg_blocked_list.values if "fg_blocked_list" in d else []):
        for x in _dists(lst):
            miss[i, _bucket(x)] += 1
    # blocked kicks without a distance list: count them at 40-49
    nb = f("fg_blocked") - np.array([len(_dists(x)) for x in (d.fg_blocked_list.values if "fg_blocked_list" in d else [""] * len(d))])
    miss[:, 1] += np.maximum(0, nb)
    out["fx0"], out["fx40"], out["fx50"], out["fx60"] = miss[:, 0], miss[:, 1], miss[:, 2], miss[:, 3]
    return out.reset_index(drop=True)


def team_games(stats, games):
    """One row per team-game (regular season, games played): the D/ST's events, points and yards allowed, the
    offense's yards and the events it gave up, kicking volume, and the Vegas implied totals (NaN without a line)."""
    s = stats[stats.season_type == "REG"].copy()
    z = lambda c: s[c].fillna(0).astype(float) if c in s else 0.0  # noqa: E731
    s["_frtd"] = np.where(z("fumble_recovery_opp") > 0, z("fumble_recovery_tds"), 0.0)
    s["_blk"] = z("def_punt_blocks") + z("def_pat_blocks") + z("def_fg_blocks")
    s["_dtd"] = z("def_tds") + s["_frtd"]
    s["_yds"] = z("passing_yards") + z("sack_yards_lost").where(z("sack_yards_lost") <= 0, -z("sack_yards_lost")) + z("rushing_yards")
    for c in ("def_sacks", "def_interceptions", "fumble_recovery_opp", "def_safeties", "special_teams_tds", "fg_att", "pat_att"):
        s[c] = z(c)
    a = s.groupby(["season", "week", "team"]).agg(sk=("def_sacks", "sum"), it=("def_interceptions", "sum"), fr=("fumble_recovery_opp", "sum"),
                                                  sf=("def_safeties", "sum"), dtd=("_dtd", "sum"), sttd=("special_teams_tds", "sum"),
                                                  blk=("_blk", "sum"), yds=("_yds", "sum"), fga=("fg_att", "sum"), pata=("pat_att", "sum")).reset_index()
    g = games[(games.game_type == "REG") & games.home_score.notna()]
    rows = []
    for r in g.itertuples():
        line = pd.notna(r.total_line) and pd.notna(r.spread_line)
        hi = r.total_line / 2 + r.spread_line / 2 if line else np.nan
        ai = r.total_line / 2 - r.spread_line / 2 if line else np.nan
        rows.append((int(r.season), int(r.week), r.home_team, r.away_team, 1, float(r.home_score), float(r.away_score), hi, ai))
        rows.append((int(r.season), int(r.week), r.away_team, r.home_team, 0, float(r.away_score), float(r.home_score), ai, hi))
    G = pd.DataFrame(rows, columns=["season", "week", "team", "opp", "home", "pts", "opts", "imp", "oimp"])
    G = G.merge(a, on=["season", "week", "team"], how="inner")
    o = a[["season", "week", "team", "sk", "it", "fr", "dtd", "yds"]].rename(
        columns={"team": "opp", "sk": "osk", "it": "oit", "fr": "ofr", "dtd": "odtd", "yds": "oyds"})
    G = G.merge(o, on=["season", "week", "opp"], how="left")
    for c in ("osk", "oit", "ofr", "odtd", "oyds"):
        G[c] = G[c].fillna(0.0)
    G["pa"] = (G.opts - 7 * G.odtd).clip(lower=0)
    return G.reset_index(drop=True)


def actual_dst(TG):
    """D/ST component vectors of games played (one-hot tiers): DataFrame with D_COMP columns."""
    out = TG[["season", "week", "team", "opp"]].copy()
    for c in D_EVT:
        out[c] = TG[c].astype(float)
    out["pa"], out["ya"] = TG.pa.astype(float), TG.oyds.astype(float)
    pt, yt = TG.pa.map(pa_tier), TG.oyds.map(ya_tier)
    for i in range(9):
        out[f"pa{i}"] = (pt == i).astype(float)
        out[f"ya{i}"] = (yt == i).astype(float)
    return out


def actual_k(KG):
    """Kicker component vectors of games played (K_COMP order; 50+ misses together)."""
    out = KG[["season", "week", "id", "team"]].copy()
    for c in K_COMP:
        out[c] = (KG.fx50 + KG.fx60) if c == "fx50" else KG[c]
    return out


# ----------------------------------------------------------------------------- league constants
def _poisson_loglin(y, X, iters=30):
    """log E[y] = b0 + X b by IRLS (Poisson). Returns [b0, b1, ...]."""
    y = np.asarray(y, float)
    A = np.column_stack([np.ones(len(y)), np.asarray(X, float)])
    b = np.zeros(A.shape[1])
    b[0] = math.log(max(1e-6, y.mean()))
    for _ in range(iters):
        mu = np.exp(A @ b)
        z = A @ b + (y - mu) / np.maximum(mu, 1e-9)
        H = A.T @ (A * mu[:, None])
        b = np.linalg.solve(H + 1e-9 * np.eye(len(b)), A.T @ (mu * z))
    return [float(x) for x in b]


def league(TG, KG):
    """League constants from the history window (rows with a Vegas line for the line-based fits)."""
    L = {}
    T = TG[TG.imp.notna()]
    # the defense's events: fewer against a good offense (its implied total), more when the defense's team is
    # favored (the opponent trails and throws)
    X = np.column_stack([T.oimp - IMP0, T.imp - T.oimp])
    for c in ("sk", "it", "fr"):
        L[c] = _poisson_loglin(T[c], X) if len(T) > 50 else [math.log(max(1e-6, TG[c].mean())), 0.0, 0.0]
    n = max(1, len(TG))
    for c in ("sf", "sttd", "blk"):
        L[c] = float(TG[c].sum() / n)
    L["td_per_take"] = float(TG.dtd.sum() / max(1.0, (TG.it + TG.fr).sum()))
    # kicking volume: least squares on the team's implied total and spread (favorites kick more field goals;
    # at the same spread, a higher total means touchdowns instead)
    for c in ("pata", "fga"):
        A = np.column_stack([np.ones(len(T)), T.imp - IMP0, T.imp - T.oimp])
        L[c] = [float(v) for v in np.linalg.lstsq(A, T[c].values, rcond=None)[0]] if len(T) > 50 else [float(TG[c].mean()), 0.0, 0.0]
    att = np.array([KG[f"fg{b}"].sum() + KG[f"fx{b}"].sum() for b in BUCKETS], float)
    L["mix"] = (att / att.sum()).tolist() if att.sum() else [0.62, 0.25, 0.12, 0.01]
    made = np.array([KG[f"fg{b}"].sum() for b in BUCKETS], float)
    L["make"] = [float(m / a) if a else 0.5 for m, a in zip(made, att)]
    pa_att = KG.patM.sum() + KG.patX.sum()
    L["pat"] = float(KG.patM.sum() / pa_att) if pa_att else 0.95
    # points allowed around the opponent's implied total (integer residuals); yards allowed on a line
    r = np.round(T.pa - T.oimp).astype(int)
    vals, cnt = np.unique(r, return_counts=True)
    L["pa_resid"] = [[int(v), int(c)] for v, c in zip(vals, cnt)]
    if len(T) > 20:
        x = (T.oimp - IMP0).values
        A = np.column_stack([np.ones_like(x), x])
        b = np.linalg.lstsq(A, T.oyds.values, rcond=None)[0]
        L["ya"] = [float(b[0]), float(b[1])]
        L["ya_sd"] = float(np.std(T.oyds.values - A @ b))
    else:
        L["ya"], L["ya_sd"] = [float(TG.oyds.mean()), 0.0], float(TG.oyds.std() or 75.0)
    return L


def lam(L, c, oimp, spr):
    """League rate of a defensive event against an offense with implied total oimp, the defense's team favored by spr."""
    a, b, g = L[c]
    return math.exp(a + b * (oimp - IMP0) + g * spr)


def vol(L, c, imp, spr, floor):
    """League kicking volume (PAT or FG attempts) for a team with implied total imp, favored by spr."""
    a, b, g = L[c]
    return max(floor, a + b * (imp - IMP0) + g * spr)


# ----------------------------------------------------------------------------- team and kicker profiles
def _weights(seasons, S, w_prev):
    return np.power(w_prev, (S - np.asarray(seasons, int)).clip(min=0))


def profiles(TG, KG, L, S, P):
    """Shrunk team and kicker factors from the history rows given (already cut at the target week)."""
    P = {**DEFAULTS, **(P or {})}
    T = TG.copy()
    T["w"] = _weights(T.season, S, P["w_dprev"])
    T["wk"] = _weights(T.season, S, P["w_kprev"])
    # expected events at the league rate for the lines (league average where there was no line)
    oi, im = T.oimp.fillna(IMP0).values, T.imp.fillna(IMP0).values
    sp = im - oi
    for c in ("sk", "it", "fr"):
        T["e_" + c] = [lam(L, c, x, s_) for x, s_ in zip(oi, sp)]        # the defense, facing this offense
        T["eo_" + c] = [lam(L, c, x, -s_) for x, s_ in zip(im, sp)]      # this offense, facing that defense
    ya0, ya1 = L["ya"]
    T["e_ya"] = ya0 + ya1 * (oi - IMP0)
    T["eo_ya"] = ya0 + ya1 * (im - IMP0)
    T["e_pata"] = [vol(L, "pata", x, s_, 0.2) for x, s_ in zip(im, sp)]
    T["e_fga"] = [vol(L, "fga", x, s_, 0.3) for x, s_ in zip(im, sp)]
    D = {}
    for tm, d in T.groupby("team"):
        w, wk = d.w.values, d.wk.values
        f = {}
        for c in ("sk", "it", "fr"):
            kl = P["k_dst"] * float(np.mean(d["e_" + c]))
            f[c] = (float((w * d[c]).sum()) + kl) / (float((w * d["e_" + c]).sum()) + kl)
        for c in ("sttd", "blk"):
            kl = P["k_st"] * L[c]
            f[c] = (float((w * d[c]).sum()) + kl) / (float(w.sum() * L[c]) + kl)
        f["ya"] = float((w * (d.oyds - d.e_ya)).sum() / (w.sum() + P["k_ya"]))
        # the same team as an offense: what it gives up to defenses, and its yards
        for c, src in (("sk", "osk"), ("it", "oit"), ("fr", "ofr")):
            kl = P["k_off"] * float(np.mean(d["eo_" + c]))
            f["o_" + c] = (float((w * d[src]).sum()) + kl) / (float((w * d["eo_" + c]).sum()) + kl)
        f["o_ya"] = float((w * (d.yds - d.eo_ya)).sum() / (w.sum() + P["k_ya"]))
        f["pata"] = (float((wk * d.pata).sum()) + P["k_pvol"]) / (float((wk * d.e_pata).sum()) + P["k_pvol"])
        f["fga"] = (float((wk * d.fga).sum()) + P["k_kvol"]) / (float((wk * d.e_fga).sum()) + P["k_kvol"])
        D[tm] = f
    K = {}
    if len(KG):
        kw = _weights(KG.season, S, P["w_kprev"])
        G = KG.assign(w=kw)
        for pid, d in G.groupby("id"):
            w = d.w.values
            att = np.array([(w * (d[f"fg{b}"] + d[f"fx{b}"])).sum() for b in BUCKETS], float)
            made = np.array([(w * d[f"fg{b}"]).sum() for b in BUCKETS], float)
            mk = [(made[i] + P["k_fg"] * L["make"][i]) / (att[i] + P["k_fg"]) for i in range(4)]
            mix = (att + P["k_mix"] * np.array(L["mix"])) / (att.sum() + P["k_mix"])
            pm, pa = float((w * d.patM).sum()), float((w * (d.patM + d.patX)).sum())
            K[pid] = {"make": [float(x) for x in mk], "mix": [float(x) for x in mix],
                      "pat": (pm + P["k_pat"] * L["pat"]) / (pa + P["k_pat"]), "fga_hist": float(att.sum())}
    return D, K


def _neutral_team():
    return {"sk": 1.0, "it": 1.0, "fr": 1.0, "sttd": 1.0, "blk": 1.0, "ya": 0.0, "o_sk": 1.0, "o_it": 1.0, "o_fr": 1.0, "o_ya": 0.0,
            "pata": 1.0, "fga": 1.0}


# ----------------------------------------------------------------------------- weekly projections
def pa_probs(L, mean_imp, scale=1.0):
    """Points-allowed distribution for an opponent implied total: {points: probability} (integers, ≥ 0)."""
    res = L["pa_resid"]
    tot = float(sum(c for _, c in res))
    mu = sum(v * c for v, c in res) / tot
    out = {}
    for v, c in res:
        x = int(round(mean_imp + mu + (v - mu) * scale))
        x = max(0, x)
        out[x] = out.get(x, 0.0) + c / tot
    return out


def _num(x, default):
    return default if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def project_dst(L, D, team, opp, oimp, spr=0.0, P=None):
    """Expected D/ST components (D_COMP order) for one game against `opp` whose implied total is `oimp`, with
    the defense's team favored by `spr` points."""
    P = {**DEFAULTS, **(P or {})}
    f, o = D.get(team) or _neutral_team(), D.get(opp) or _neutral_team()
    x, sp = _num(oimp, IMP0), _num(spr, 0.0)
    sk = lam(L, "sk", x, sp) * f["sk"] * o["o_sk"]
    it = lam(L, "it", x, sp) * f["it"] * o["o_it"]
    fr = lam(L, "fr", x, sp) * f["fr"] * o["o_fr"]
    sf = L["sf"]
    blk = L["blk"] * f["blk"]
    sttd = L["sttd"] * f["sttd"]
    dtd = (it + fr) * L["td_per_take"]
    pp = pa_probs(L, x, P["pa_scale"])
    pa = sum(k * v for k, v in pp.items())
    pat = [0.0] * 9
    for k, v in pp.items():
        pat[pa_tier(k)] += v
    ya0, ya1 = L["ya"]
    ya = ya0 + ya1 * (x - IMP0) + f["ya"] + o["o_ya"]
    sd = max(1.0, L["ya_sd"])
    cdf = [0.0] + [0.5 * (1 + math.erf((e - ya) / (sd * math.sqrt(2)))) for e in YA_EDGES[1:]] + [1.0]
    yat = [cdf[i + 1] - cdf[i] for i in range(9)]
    return [sk, it, fr, sf, dtd, sttd, blk, pa, ya] + pat + yat


def project_k(L, D, K, kid, team, imp, spr=0.0):
    """Expected kicker components (K_COMP order) for one game of `team` with implied total `imp`, favored by `spr`."""
    f = D.get(team) or _neutral_team()
    x, sp = _num(imp, IMP0), _num(spr, 0.0)
    pat = vol(L, "pata", x, sp, 0.2) * f["pata"]
    fga = vol(L, "fga", x, sp, 0.3) * f["fga"]
    k = K.get(kid) or {"make": L["make"], "mix": L["mix"], "pat": L["pat"]}
    made = [fga * k["mix"][i] * k["make"][i] for i in range(4)]
    miss = [fga * k["mix"][i] * (1 - k["make"][i]) for i in range(4)]
    return [pat * k["pat"], pat * (1 - k["pat"]), made[0], made[1], made[2], made[3], miss[0], miss[1], miss[2] + miss[3]]


def history(stats_by_season, games):
    """(team-game table, kicker-game table) for the seasons given ({season: player-stats DataFrame})."""
    st = pd.concat([d for d in stats_by_season.values()], ignore_index=True)
    return team_games(st, games), kicker_games(st)


def cut(TG, KG, S, W):
    """History available before week W of season S (earlier seasons in full)."""
    m = (TG.season < S) | ((TG.season == S) & (TG.week < W))
    k = (KG.season < S) | ((KG.season == S) & (KG.week < W))
    return TG[m], KG[k]


def sim_params(L):
    """What the page's start/sit simulation needs: the points-allowed residuals as observed (added to each
    opponent's implied total; pa_scale tunes the point projection only, not the simulated spread) and the
    yards-allowed spread."""
    tot = float(sum(c for _, c in L["pa_resid"]))
    return {"paResid": [[int(v), round(c / tot, 5)] for v, c in L["pa_resid"]], "yaSd": round(L["ya_sd"], 1)}
