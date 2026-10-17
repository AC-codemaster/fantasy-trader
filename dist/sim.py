"""Weekly points distributions: a play-by-play-count simulation of each team's game, built on the projection's
own expected stat line. The page runs the same model (engine/engine.js, simWeek); this is the reference
implementation the parameters in params/dist.json are fitted with (dist/fit_dist.py).

One simulated game (every multiplier has mean 1):
  game    a passing-environment shock both teams share (shootouts, weather: pass volume and passing efficiency
          on both sides) and a script shock that splits them (the team that leads runs more, the trailer throws)
  team    its own pass-volume, rush-volume and efficiency shocks; touchdowns move td_el times as much as yards
  player  a role shock on his share of the team's carries and targets; shares are re-split inside the team, so
          when one back gets more work his teammate gets less; a small chance he leaves the game early (he
          plays a uniform fraction of it and his teammates absorb the rest); his own efficiency shock
  plays   carries and targets are Poisson around those shares; catches are binomial; yards are sums of plays
          (gamma with the per-play coefficient of variation); touchdowns, interceptions, fumbles and two-point
          plays are Poisson at their per-play rates
  QB      the passing line is the pass catchers' receiving line: team passing yards and touchdowns move with
          what the receivers did against their expectation (plus a pseudo-receiver for players not modeled),
          and each QB gets his share of the team's pass attempts. That is the QB-receiver correlation.
Means: the expected stat line is the projection's. mean[pos] multipliers calibrate it to what happened in
the backtest (the projection is tuned on average miss, so it sits between a player's median and his mean).
"""
import numpy as np

COMP = ["py", "ptd", "int", "ry", "rtd", "rec", "recy", "rectd", "fl", "two"]
PPR = np.array([0.04, 4, -2, 0.1, 6, 1.0, 0.1, 6, -2, 2])
POSL = ["QB", "RB", "WR", "TE"]
POS_I = {p: i for i, p in enumerate(POSL)}


def order(F):
    """Sort a frame so team-games are contiguous (prep() needs it)."""
    return F.sort_values(["season", "week", "team"], kind="stable").reset_index(drop=True)


def prep(F):
    """Per-row inputs from a frame sorted by order(), with season, week, team, opp, pos, car, tgt, att, qc and the
    expected components c_py ... c_two (as backtest_core.project and the engine produce them)."""
    pos = F.pos.map(POS_I).values.astype(np.int8)
    isqb = pos == 0
    car = np.where(isqb, F.qc.values, F.car.values).astype(float)
    tgt = np.where(isqb, 0.0, F.tgt.values).astype(float)
    att = np.where(isqb, F.att.values, 0.0).astype(float)
    dv = lambda a, b: np.where(b > 1e-9, a / np.maximum(b, 1e-9), 0.0)   # noqa: E731
    c = {k: F["c_" + k].values.astype(float) for k in COMP}
    X = dict(pos=pos, isqb=isqb, car=car, tgt=tgt, att=att,
             ypc=dv(c["ry"], car), rtd=dv(c["rtd"], car), cr=np.clip(dv(c["rec"], tgt), 0, 1),
             ypr=dv(c["recy"], c["rec"]), ctd=dv(c["rectd"], c["rec"]),
             py=c["py"], ptd=c["ptd"], ipa=dv(c["int"], att),
             fl=dv(c["fl"], car + tgt + att), two=dv(c["two"], car + tgt + att))
    tg = (F.season.astype(str) + "-" + F.week.astype(str) + "-" + F.team.astype(str)).values
    start = np.r_[0, np.flatnonzero(tg[1:] != tg[:-1]) + 1]
    X["tg_start"] = start
    X["tg_of_row"] = np.repeat(np.arange(len(start)), np.diff(np.r_[start, len(tg)]))
    teams, opp = F.team.values[start].astype(str), F.opp.values[start].astype(str)
    games = (F.season.astype(str) + "-" + F.week.astype(str)).values[start]
    gid, side, seen = np.zeros(len(start), int), np.zeros(len(start)), {}
    for i, (g, t, o) in enumerate(zip(games, teams, opp)):
        k = (g,) + tuple(sorted([t, o]))
        gid[i] = seen.setdefault(k, len(seen))
        side[i] = 1.0 if t <= o else -1.0
    X["game_of_tg"], X["side_of_tg"], X["n_games"] = gid, side, len(seen)
    return X


def _gamma_sum(rng, n_plays, mean_per_play, cv):
    """Sum of n_plays plays with this mean and coefficient of variation per play (gamma; 0 with no plays)."""
    n_plays = np.asarray(n_plays, float)
    shape = n_plays / (cv * cv)
    scale = np.broadcast_to(mean_per_play * cv * cv, shape.shape)
    out = np.zeros(shape.shape)
    m = (shape > 0) & (scale > 0)
    out[m] = rng.gamma(shape[m], scale[m])
    return out


def _seg(x, st):
    return np.add.reduceat(x, st, axis=-1)


def _split(E, g, f, st, tgr, other):
    """Expected counts after role shocks g and early exits f, within each team pool: shares are re-split so the
    pool keeps its size (one player's gain is a teammate's loss), and a player who leaves early hands what he
    would have had to the teammates still playing. other: pool share of players not modeled (keep theirs)."""
    a = E * g
    tot_e = _seg(E, st)                                   # (T,)
    gbar = (_seg(a, st) + other * tot_e) / np.maximum((1 + other) * tot_e, 1e-12)
    a = a / np.maximum(gbar[..., tgr], 1e-12)
    kept = a * f
    lost = _seg(a - kept, st)
    K = _seg(kept, st) + other * tot_e
    return kept + lost[..., tgr] * kept / np.maximum(K[..., tgr], 1e-12)


def simulate(X, P, n=200, seed=0):
    """Simulated stat lines: dict of component -> array (n, rows). P: the params/dist.json structure."""
    R = [np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(16)]
    N, T, G = len(X["pos"]), len(X["tg_start"]), X["n_games"]
    tm, gm, pl, pp = P["team"], P["game"], P["player"], P["play"]
    pos, isqb, st, tgr = X["pos"], X["isqb"], X["tg_start"], X["tg_of_row"]
    M = {k: np.array([P["mean"][p].get(k, 1.0) for p in POSL])[pos] for k in ("vr", "vt", "ypc", "rtd", "ypr", "ctd", "py", "ptd", "int")}
    # game and team shocks, (n, T)
    pace = R[0].standard_normal((n, G))[:, X["game_of_tg"]]
    script = R[0].standard_normal((n, G))[:, X["game_of_tg"]] * X["side_of_tg"][None, :]
    zp, zr, ze = R[1].standard_normal((n, T)), R[1].standard_normal((n, T)), R[1].standard_normal((n, T))
    # the pace shock is the game's passing environment (shootouts, weather): both teams' pass volume and passing
    # efficiency; rushing efficiency is the team's own
    lp = tm["sd_pass"] * zp + gm["pace_vol"] * pace - gm["script_pass"] * script
    lr = tm["sd_rush"] * zr + gm["script_rush"] * script
    lq = tm["sd_eff"] * ze + gm["pace_eff"] * pace
    lu = tm["sd_eff"] * ze
    var_p = tm["sd_pass"] ** 2 + gm["pace_vol"] ** 2 + gm["script_pass"] ** 2
    var_r = tm["sd_rush"] ** 2 + gm["script_rush"] ** 2
    var_q, var_u = tm["sd_eff"] ** 2 + gm["pace_eff"] ** 2, tm["sd_eff"] ** 2
    vp, vr = np.exp(lp - 0.5 * var_p), np.exp(lr - 0.5 * var_r)
    ve, vu = np.exp(lq - 0.5 * var_q), np.exp(lu - 0.5 * var_u)
    vtd = np.exp(tm["td_el"] * lq - 0.5 * tm["td_el"] ** 2 * var_q)
    vtu = np.exp(tm["td_el"] * lu - 0.5 * tm["td_el"] ** 2 * var_u)
    VP, VR, VE, VT, VU, VTU = vp[:, tgr], vr[:, tgr], ve[:, tgr], vtd[:, tgr], vu[:, tgr], vtu[:, tgr]
    # player role shocks, early exits, efficiency
    sd_s = np.where(isqb, pl["share_qb"], np.array([0, pl["share_rb"], pl["share_wr"], pl["share_te"]])[pos])
    k = 1.0 / np.maximum(sd_s ** 2, 1e-9)
    g = R[2].gamma(np.broadcast_to(k, (n, N)), np.broadcast_to(1.0 / k, (n, N)))
    f = np.where(R[3].random((n, N)) < np.where(isqb, pl["exit_qb"], pl["exit"])[None, :], R[3].random((n, N)), 1.0)
    sd_e = np.array([pl["eff"][p] for p in POSL])[pos][None, :]
    zq = R[4].standard_normal((n, N))
    eff = np.exp(sd_e * zq - 0.5 * sd_e ** 2)
    eff_td = np.exp(tm["td_el"] * sd_e * zq - 0.5 * (tm["td_el"] * sd_e) ** 2)
    # opportunities: QB attempts among the team's QBs; skill carries and targets among the skill players
    sk = ~isqb
    lam_car = _split(np.where(sk, X["car"] * M["vr"], 0.0), np.where(sk, g, 1.0), np.where(sk, f, 1.0), st, tgr, pp["other_car"]) * VR
    lam_tgt = _split(np.where(sk, X["tgt"] * M["vt"], 0.0), np.where(sk, g, 1.0), np.where(sk, f, 1.0), st, tgr, pp["other_tgt"]) * VP
    lam_att = _split(np.where(isqb, X["att"] * M["vt"], 0.0), np.where(isqb, g, 1.0), np.where(isqb, f, 1.0), st, tgr, 0.01) * VP
    qb_frac = np.where(isqb[None, :], lam_att / np.maximum((X["att"] * M["vt"])[None, :] * VP, 1e-12), 0.0)   # his part of the game
    lam_car = np.where(isqb[None, :], (X["car"] * M["vr"])[None, :] * VP * qb_frac, lam_car)
    n_car, n_tgt = R[5].poisson(lam_car), R[6].poisson(lam_tgt)
    n_att = R[7].poisson(lam_att)
    cv_r = np.where(isqb, pp["cv_qbrush"], pp["cv_rush"])[None, :]
    ry = _gamma_sum(R[8], n_car, (X["ypc"] * M["ypc"])[None, :] * VU * eff, cv_r)
    rtd = R[9].poisson(n_car * (X["rtd"] * M["rtd"])[None, :] * VTU * eff_td)
    rec = R[10].binomial(n_tgt, np.broadcast_to(X["cr"], (n, N)))
    cv_c = np.array([1.0, pp["cv_catch_rb"], pp["cv_catch_wr"], pp["cv_catch_te"]])[pos][None, :]
    recy = _gamma_sum(R[11], rec, (X["ypr"] * M["ypr"])[None, :] * VE * eff, cv_c)
    rectd = R[12].poisson(rec * (X["ctd"] * M["ctd"])[None, :] * VT * eff_td)
    # QB passing: the team's receiving production against its expectation, split by pass attempts
    e_y = np.where(sk, X["tgt"] * M["vt"] * X["cr"] * X["ypr"] * M["ypr"], 0.0)
    e_t = np.where(sk, X["tgt"] * M["vt"] * X["cr"] * X["ctd"] * M["ctd"], 0.0)
    E_y, E_t = _seg(e_y, st), _seg(e_t, st)
    Q_y = _seg(np.where(isqb, X["py"] * M["py"], 0.0), st)
    Q_t = _seg(np.where(isqb, X["ptd"] * M["ptd"], 0.0), st)
    O_y = np.maximum(pp["other_min"] * Q_y, Q_y - E_y)
    O_t = np.maximum(pp["other_min"] * Q_t, Q_t - E_t)
    o_y = _gamma_sum(R[13], (O_y / pp["other_ypt"])[None, :] * vp, pp["other_ypt"] * ve, pp["other_cv"])
    o_t = R[13].poisson(O_t[None, :] * vp * vtd)
    team_py = (_seg(recy, st) + o_y) / np.maximum(E_y + O_y, 1e-9)[None, :] * Q_y[None, :]
    team_pt = (_seg(rectd, st) + o_t) / np.maximum(E_t + O_t, 1e-9)[None, :] * Q_t[None, :]
    att_tot = _seg(np.where(isqb[None, :], n_att, 0), st)
    exp_share = np.where(isqb, X["py"] * M["py"], 0.0)[None, :] / np.maximum(Q_y[None, tgr], 1e-9)
    a_share = np.where(att_tot[:, tgr] > 0, n_att / np.maximum(att_tot[:, tgr], 1), exp_share)
    py = np.where(isqb[None, :], team_py[:, tgr] * a_share, 0.0)
    ptd = np.where(isqb[None, :], team_pt[:, tgr] * a_share, 0.0)
    ints = R[14].poisson(n_att * (X["ipa"] * M["int"])[None, :])
    opp = n_car + n_tgt + n_att
    fl = R[15].poisson(opp * X["fl"][None, :])
    two = R[15].poisson(opp * X["two"][None, :])
    return {"py": py, "ptd": ptd, "int": ints, "ry": ry, "rtd": rtd, "rec": rec, "recy": recy, "rectd": rectd, "fl": fl, "two": two}


def points(S, w=PPR):
    """Fantasy points from simulated components with scoring weights w (10 numbers, COMP order)."""
    return sum(S[c] * w[i] for i, c in enumerate(COMP))


def actual_points(F, w=PPR):
    return sum(F["a_" + c].values * w[i] for i, c in enumerate(COMP))


def expected_points(F, w=PPR):
    return sum(F["c_" + c].values * w[i] for i, c in enumerate(COMP))
