"""Checks that must pass before anything is published or a parameter change is kept.

    python3 tests/run_tests.py

No test framework needed. Uses the archived Week 5 inputs as a fixed fixture, so results don't move with
the weekly data. Exits non-zero on any failure.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "backtest"))
from ftlib import ENGINE_KEYS, backtest_params, engine_source, load_params_file, values  # noqa: E402

W5 = os.path.join(ROOT, "data", "inputs", "2026", "w05")
FIX = os.path.join(ROOT, "tests", "fixtures", "user-league-w05.json")
KD_DB = os.path.join(ROOT, "tests", "fixtures", "db-kdst-w06.json")   # a build with kickers and defenses (Oct 19, 2026)
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def node(*args):
    r = subprocess.run(["node", *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


@test
def params_file_is_consistent():
    import kdst
    pj = load_params_file()
    src_b = open(os.path.join(ROOT, "pipeline", "build_db.py")).read()
    for k, v in pj["params"].items():
        assert v["min"] <= v["value"] <= v["max"], f"{k} outside its bounds"
        assert ("step" in v) != ("mult" in v), f"{k} needs exactly one of step / mult"
        assert v["layer"] in ("builder", "engine") and v["eval"] in ("backtest", "live", "none", "kdst"), k
        if v["eval"] == "kdst":   # kickers and D/ST: kdst.py settings, read by the builder and the K/DST replay
            assert k in kdst.DEFAULTS and "prm(k_, v_) for k_, v_ in kdst.DEFAULTS" in src_b, f"builder doesn't read {k}"
        elif v["layer"] == "builder":
            assert f'prm("{k}"' in src_b or (k.startswith("K_") and 'prm("K_" + k_' in src_b), f"builder doesn't read {k}"
        else:
            assert k in ENGINE_KEYS, f"engine doesn't read {k}"
    assert set(kdst.DEFAULTS) == {k for k, v in pj["params"].items() if v["eval"] == "kdst"}, "kdst.DEFAULTS and params.json disagree"
    bp = backtest_params(values(pj))
    import backtest_core as bc
    for k in bp:
        assert k in bc.BASE, f"backtest has no setting {k}"


@test
def page_assembles_and_matches_archived_engine():
    """The page built from the repo runs exactly the archived Week 5 engine (the live page's numbers)."""
    import make_page
    from scorecard import engine_from_page
    html = make_page.build(open(os.path.join(W5, "db.json")).read(), open(os.path.join(W5, "injury_news.json")).read())
    for ph in ("{{DB}}", "{{ENGINE}}", "{{UI}}", "{{BUILDER}}", "{{KDST}}", "{{RUNBOOK}}", "{{PARAMS}}", "{{INJNEWS}}"):
        assert ph not in html
    assert html.count("<script") == html.count("</script>"), "unbalanced script elements"
    eng, db_text, _ = engine_from_page(html)
    pj_vals = values(load_params_file())
    assert eng == engine_source(pj_vals), "engine in the page differs from engine.js + params"
    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "e.js"), "w").write(eng)
        open(os.path.join(td, "db.json"), "w").write(db_text)
        a = node(os.path.join(ROOT, "tools", "engine_runner.js"), "--engine", os.path.join(td, "e.js"), "--db", os.path.join(td, "db.json"), "--lite")
        b = node(os.path.join(ROOT, "tools", "engine_runner.js"), "--engine", os.path.join(W5, "engine.js"), "--db", os.path.join(W5, "db.json"), "--lite")
    A = pd.DataFrame(a["players"]).set_index("id").page_ppr
    B = pd.DataFrame(b["players"]).set_index("id").page_ppr
    archived = json.load(open(os.path.join(W5, "params.json")))
    if values(archived) == pj_vals:
        assert (A - B).abs().max() < 1e-9, "assembled page computes different numbers than the archived engine"


@test
def runner_reproduces_week5_freeze():
    f = json.load(open(os.path.join(ROOT, "data", "freeze", "2026-w05.json")))
    F = pd.DataFrame(f["rows"], columns=f["cols"]).set_index("id")
    r = node(os.path.join(ROOT, "tools", "engine_runner.js"), "--engine", os.path.join(W5, "engine.js"), "--db", os.path.join(W5, "db.json"))
    P = pd.DataFrame(r["players"]).set_index("id")
    ids = F.index.intersection(P.index)
    assert len(ids) == len(F)
    for c in ("page_ppr", "model_ppr", "corr_ppr", "o_tgt", "o_car", "o_att"):
        assert (F.loc[ids, c].astype(float) - P.loc[ids, c].astype(float)).abs().max() < 1e-9, c


@test
def trade_engine_regressions():
    """Past bugs stay fixed: Allen for two starters (Oct 2) and Shough for the two Warrens (Oct 6)."""
    with tempfile.TemporaryDirectory() as td:
        ep = os.path.join(td, "e.js")
        open(ep, "w").write(engine_source())
        r = node(os.path.join(ROOT, "tests", "engine_checks.js"), ep, os.path.join(W5, "db.json"), FIX)
    assert r["allen"]["n"] >= 100
    assert r["allen"]["median"] < 0.10, f"Allen-for-two-starters median acceptance {r['allen']['median']:.2f} (was 0.37 before the fix)"
    assert r["allen"]["share50"] < 0.35, f"{r['allen']['share50']:.0%} of Allen two-for-ones at 50%+"
    assert r["shough"]["accept"] < 0.20, f"Shough for the Warrens at {r['shough']['accept']:.0%} (was 43% before the fix)"


@test
def scorecard_groups_by_season():
    """Week 1 of one season never mixes with week 1 of another (relevance cutoffs, start/sit pairs)."""
    import scorecard as sc
    rng = np.random.default_rng(0)
    rows = []
    for S in (2026, 2027):
        for i in range(60):
            rows.append({"season": S, "week": 1, "id": f"{S}-{i}", "team": f"T{i % 8}", "pos": "RB", "avail": 1,
                         "page_ppr": rng.uniform(2, 20), "fpf_ecr": i + 1, "act_ppr": rng.uniform(0, 30)})
    D = sc.add_sw(pd.DataFrame(rows))
    rel = sc.relevant(D)
    for S in (2026, 2027):
        assert rel[D.season == S].sum() >= sc.REL_N["RB"], "relevance cutoff shared across seasons"
    _, _, cl = sc.pairs(D.assign(fpe_ecr=np.nan), "page")
    assert all(c.startswith(("2026-01", "2027-01")) for c in cl)
    seasons_in_pairs = {c[:4] for c in cl}
    assert seasons_in_pairs == {"2026", "2027"}
    assert len(D.cl.unique()) == 16


@test
def improvement_gate_behaves():
    import improve
    good = {"n": 8000, "diff": -0.03, "se": 0.01, "z": -3.0, "seasons": {"2024": {"z": -2}, "2025": {"z": -1.5}, "2026": {"z": 0.2}},
            "byPos": {"QB": {"z": -1}, "RB": {"z": -2}}, "champ": {"slope": 0.97, "backupQbBias": 1.2}, "chal": {"slope": 0.98, "backupQbBias": 1.1}}
    assert improve.gate(good)[0]
    bad = json.loads(json.dumps(good))
    bad["seasons"]["2026"]["z"] = 1.4
    assert not improve.gate(bad)[0]
    weak = json.loads(json.dumps(good))
    weak["z"] = -2.0
    assert not improve.gate(weak)[0]
    tiny = json.loads(json.dumps(good))
    tiny["diff"] = -0.001
    assert not improve.gate(tiny)[0]                                            # below the minimum gain
    pj = load_params_file()
    assert improve.stepped(pj["params"]["decay"], 1.0, +1) is None          # at the bound
    assert improve.stepped(pj["params"]["K_cr"], 40, +1) == 50.0


@test
def rookie_lookup_covers_current_class():
    """Every drafted QB/RB/WR/TE of the current season has a rookie-model prediction (fitted on earlier classes)."""
    src = open(os.path.join(ROOT, "pipeline", "build_db.py")).read()
    season = int(re.search(r"^SEASON = (\d{4})", src, re.M).group(1))
    D = pd.read_csv(os.path.join(ROOT, "data", "rookie", "players.csv"), low_memory=False)
    R = pd.read_csv(os.path.join(ROOT, "data", "rookie", "predictions.csv"), low_memory=False)
    cls = D[(D.season == season) & D.pos.isin(["QB", "RB", "WR", "TE"])]
    assert len(cls) >= 60, f"only {len(cls)} drafted QB/RB/WR/TE in the {season} class"
    have = set(R[R.season == season].gsis_id)
    missing = cls[cls.gsis_id.notna() & ~cls.gsis_id.isin(have)]
    assert not len(missing), f"no rookie prediction for {list(missing.name)[:5]}"
    assert cls.gsis_id.notna().mean() >= 0.95, "too many drafted players without a gsis id"
    rr = R[R.season == season]
    assert (rr.trained_thru < season).all(), "predictions must come from earlier classes only"
    for c in ("sh_r", "sh_t", "sh_p"):
        assert rr[c].between(0, 1).all(), c


@test
def rookie_prior_zero_changes_nothing():
    """rookie_prior = 0 is the old model: no pseudo-counts, same backtest settings, same projections."""
    import backtest_core as bc
    pj = load_params_file()
    vals = values(pj)
    lg = pd.DataFrame({c: [1000.0] for c in ("attempts", "carries", "targets", "fl", "two")}, index=["RB"])
    rk = {"sh_r": .3, "sh_t": .05, "sh_p": 0, "ypc": 4.2, "rtd": .03, "cr": .75, "ypt": 6.5, "rctd": .03, "ypa": 0, "ptd": 0, "ipa": 0, "cpa": 0}
    assert bc.rookie_pseudo(rk, "RB", 0.0, lg) == {}
    assert bc.rookie_pseudo(rk, "RB", 1.0, lg)["carries"] > 0
    v0 = {k: v for k, v in vals.items() if k != "rookie_prior"}
    assert backtest_params(dict(v0, rookie_prior=0.0)) == dict(backtest_params(v0), rookie_prior=0.0)
    src = open(os.path.join(ROOT, "pipeline", "build_db.py")).read()
    assert src.count("ROOKIE_PRIOR > 0") >= 2 and "if ROOKIE_PRIOR <= 0 or rk is None" in src, "builder rookie code must be gated"
    # functional check on the season files when a work folder has them (skipped otherwise)
    work = os.path.join(ROOT, "work")
    need = ["s24.csv", "s25.csv", "s26.csv", "r24.csv", "r25.csv", "r26.csv", "snaps26.csv", "dc26.csv", "games.csv", "db_playerids.csv"]
    if not all(os.path.exists(os.path.join(work, f)) for f in need):
        print("      (rookie_prior backtest check skipped: no season files in work/)")
        return
    cwd = os.getcwd()
    os.chdir(work)
    try:
        S = bc.Season(2026)
        P = backtest_params(dict(vals, rookie_prior=0.0))
        a = S.project(3, P)
        b = S.project(3, {k: v for k, v in P.items() if k != "rookie_prior"})
        c = S.project(3, dict(P, rookie_prior=1.0))
    finally:
        os.chdir(cwd)
    assert len(a) == len(b) and (a.pred.values == b.pred.values).all(), "rookie_prior 0 changed the backtest"
    assert (a.pred.values != c.pred.values).any(), "rookie_prior 1 had no effect (lookup broken?)"


LEGACY_ANNUAL = {   # the constants hardcoded before Oct 12, 2026 (= params/annual.json version 1)
    "yoy": {"RB": [[24, 1.04], [25, 1.01], [26, 0.98], [27, 0.95], [28, 0.91], [29, 0.88], [99, 0.85]],
            "WR": [[23, 1.08], [24, 1.05], [25, 1.03], [26, 1.01], [27, 1.00], [28, 0.98], [29, 0.96], [30, 0.93], [31, 0.90], [99, 0.87]],
            "TE": [[24, 1.10], [25, 1.06], [26, 1.03], [27, 1.01], [28, 1.00], [29, 0.97], [30, 0.94], [31, 0.91], [99, 0.88]],
            "QB": [[25, 1.05], [26, 1.03], [27, 1.01], [32, 1.00], [33, 0.98], [34, 0.96], [35, 0.94], [36, 0.92], [99, 0.89]]},
    "env_k": {"att": [0.2378, -0.00353], "pyd": [0.5709, -0.0025], "ptd": [0.6785, -0.00071], "car": [-0.0775, 0.00735],
              "ryd": [0.1785, 0.00615], "rtd": [0.4132, 0.00569]},
    "low_volume": {"lowcut": {"QB": ["attempts", 150], "RB": ["carries", 40], "WR": ["targets", 25], "TE": ["targets", 20], "RB_rec": ["targets", 15]},
                   "afull": {"QB": 300, "RB": 100, "WR": 60, "TE": 45, "RB_rec": 40}},
    "faab": {"cut": {"QB": 20, "RB": 50, "WR": 70, "TE": 20}, "n_start": {"QB": 12, "RB": 30, "WR": 40, "TE": 12},
             "n_waiver": {"QB": 18, "RB": 48, "WR": 64, "TE": 18}},
}


@test
def annual_constants_shared_and_reproduced():
    """params/annual.json is what the builder, the backtest and the engine use; version 1 is exactly the old
    hardcoded numbers, and every later version was adopted by the annual refit (logged in the changelog)."""
    import backtest_core as bc
    import ftlib
    A = json.load(open(os.path.join(ROOT, "params", "annual.json")))
    for k in LEGACY_ANNUAL:
        assert k in A, f"annual.json has no {k}"
    assert bc.YOY == {k: [tuple(x) for x in v] for k, v in A["yoy"].items()}, "backtest YOY differs from annual.json"
    assert bc.LOWCUT == {k: tuple(v) for k, v in A["low_volume"]["lowcut"].items()} and bc.AFULL == A["low_volume"]["afull"]
    assert ftlib.ENV_K == {k: tuple(v) for k, v in A["env_k"].items()}, "ftlib ENV_K differs from annual.json"
    eng = engine_source()
    m = re.search(r"^const ENV_K = (\{.*\});$", eng, re.M)
    assert m and json.loads(m.group(1)) == A["env_k"], "the page's engine doesn't carry annual.json's ENV_K"
    src = open(os.path.join(ROOT, "pipeline", "build_db.py")).read()
    for k in ('ANNUAL["yoy"]', 'ANNUAL["low_volume"]', 'ANNUAL["faab"]'):
        assert k in src, f"builder doesn't read {k}"
    # the fallbacks in the code are version 1
    m = re.search(r"^const ENV_K = (\{.*\});$", open(os.path.join(ROOT, "engine", "engine.js")).read(), re.M)
    assert m, "engine.js lost its ENV_K line"
    if A["version"] == 1:
        for k, v in LEGACY_ANNUAL.items():
            assert A[k] == v, f"annual.json version 1 must equal the old constants ({k})"
    else:
        log = open(os.path.join(ROOT, "ledger", "changelog.md")).read()
        assert f"annual constants v{A['version']}" in log, "annual.json changed without an annual-refit changelog entry"


@test
def distribution_params_are_sane():
    """params/dist.json (start/sit distributions) has every part the page needs, within sensible ranges."""
    import ftlib
    D = ftlib.load_dist()
    assert D, "params/dist.json missing (dist/fit_dist.py fit --write)"
    for k in ftlib.DIST_KEYS:
        assert k in D, f"dist.json has no {k}"
    for part in ("team", "game", "player", "play"):
        for k, v in D[part].items():
            vals = v.values() if isinstance(v, dict) else [v]
            hi = 20 if k == "other_ypt" else 5          # yards per target; everything else is a spread or share
            assert all(0 <= float(x) < hi for x in vals), f"{part}.{k} out of range"
    for pos, m in D["mean"].items():
        assert all(0.6 <= float(x) <= 1.6 for x in m.values()), f"mean multipliers for {pos} out of range"
    pp = D["pplay"]
    assert all(0 <= x <= 1 for x in pp["base"].values()) and 0 <= pp["doubtful"] <= 0.2 and 0.9 <= pp["unlisted"] <= 1
    assert pp["base"]["Full"] > pp["base"]["Limited"] > pp["base"]["DNP"], "practice report order"
    eng = engine_source()
    m = re.search(r"^const DIST = (\{.*\});$", eng, re.M)
    assert m and json.loads(m.group(1))["version"] == D["version"], "the page's engine doesn't carry params/dist.json"


def _startsit_run(dump=None):
    with tempfile.TemporaryDirectory() as td:
        ep = os.path.join(td, "e.js")
        open(ep, "w").write(engine_source())
        args = [os.path.join(ROOT, "tests", "startsit_checks.js"), ep, os.path.join(W5, "db.json"), FIX]
        if dump:
            args += ["--dump", dump]
        return node(*args)


@test
def startsit_engine_behaves():
    """Start/sit on the archived Week 5 data and the user's league: deterministic, legal lineups, the best lineup's
    chance to win at least the projection lineup's, targets harder to reach as they rise, QB and receiver move
    together, two backs on one team move apart, calibrated means near the projections, fast enough for the page."""
    r = _startsit_run()
    assert r["deterministic"], "same seed gave different simulated games"
    ss = r["startSit"]
    assert ss["legal"] and ss["n"] == ss["slots"], "best lineup doesn't fill the slots legally"
    assert ss["best"] >= ss["proj"] - 0.005, f"best lineup {ss['best']:.3f} below the projection lineup {ss['proj']:.3f}"
    assert r["need"]["falls"], "chance of reaching a target went up with the target"
    assert r["corr"]["qbwr"] > 0.2 and r["corr"]["rbrb"] < 0.05, f"correlations off: {r['corr']}"
    mr = r["meanRatio"]
    assert 0.95 <= mr["median"] <= 1.2 and mr["min"] > 0.8 and mr["max"] < 1.5, f"simulated means vs projections: {mr}"
    assert r["ms"] < 8000, f"simulation too slow for the page: {r['ms']} ms"


@test
def startsit_matches_reference_simulation():
    """The page's simulation (engine.js) and the reference one the parameters were fitted with (dist/sim.py) give
    the same distributions on the same inputs (uncalibrated, nobody injured), up to simulation noise."""
    sys.path.insert(0, os.path.join(ROOT, "dist"))
    import sim
    with tempfile.TemporaryDirectory() as td:
        fp = os.path.join(td, "frame.json")
        _startsit_run(fp)
        rows = json.load(open(fp))
    F = sim.order(pd.DataFrame(rows))
    import ftlib
    P = ftlib.load_dist()
    for pos in P["mean"]:
        P["mean"][pos] = {k: 1.0 for k in P["mean"][pos]}
    lg = json.load(open(FIX))["settings"]["scoring"]
    keys = ["passYd", "passTd", "int", "rushYd", "rushTd", "rec", "recYd", "recTd", "fumble", "twoPt"]
    w = np.array([float(lg.get(k, 0) or 0) for k in keys])
    pts = sim.points(sim.simulate(sim.prep(F), P, n=4000, seed=3), w)
    q = np.quantile(pts, [0.1, 0.5, 0.9], axis=0)
    m = F.pred.values >= 3
    js = np.array(F.js_q.tolist())
    d_mean = np.abs(pts.mean(0) - F.js_mean.values)[m]
    d_q = np.abs(q.T - js)[m]
    assert d_mean.mean() < 0.3 and d_q[:, 1].mean() < 0.35 and d_q[:, 2].mean() < 0.6, \
        f"engine vs reference: mean {d_mean.mean():.2f}, P50 {d_q[:, 1].mean():.2f}, P90 {d_q[:, 2].mean():.2f}"
    ratio = (F.js_mean.values / F.pred.values)[m]
    assert 0.95 < np.median(ratio) < 1.05, f"uncalibrated simulation doesn't reproduce the projections ({np.median(ratio):.3f})"


@test
def kdst_engine_behaves():
    """Kickers and defenses in the engine, on a fixed build that has them: scoring the same as pipeline/kdst.py
    (ESPN standard), K and D/ST slots that only they fill, one of each drafted per team, near-zero trade prices,
    none in the trade finder, a simulation whose means are the projections and whose spreads and links match box
    scores, and an ESPN import that brings them and their scoring in."""
    import kdst
    with tempfile.TemporaryDirectory() as td:
        ep = os.path.join(td, "e.js")
        open(ep, "w").write(engine_source())
        r = node(os.path.join(ROOT, "tests", "kdst_checks.js"), ep, KD_DB)
    sc = r["scoring"]
    for k, v in sc["defaults"].items():
        assert kdst.STANDARD[k] == v, f"engine default {k} = {v}, kdst.py {kdst.STANDARD[k]}"
    assert abs(sc["k"] - kdst.k_points(sc["kv"])) < 1e-9 and abs(sc["d"] - kdst.d_points(sc["dv"])) < 1e-9, "engine and kdst.py score differently"
    assert r["lineup"]["k"] == 7, "a kicker or defense took a FLEX or superflex slot"
    lg = r["league"]
    assert all(x == "11" for x in lg["kd"]), f"sample draft: kickers/defenses per team {lg['kd']}"
    assert "K" in lg["slots"] and "DST" in lg["slots"] and all(x == 2 for x in lg["lineupKd"]) and lg["flexKd"]
    assert lg["mu"]["max"] < 1.0 < lg["mu"]["top"], f"kicker/defense trade prices {lg['mu']}"
    assert lg["finderKd"] == 0, "the trade finder suggested kickers or defenses"
    assert 8 <= lg["ppg"]["K"][0] <= 12 and 5 <= lg["ppg"]["DST"][0] <= 10, f"top kicker/defense projections {lg['ppg']}"
    for pos, (lo, hi) in (("K", (3.8, 5.8)), ("DST", (4.6, 7.2))):
        x = r["sim"][pos]
        assert x["n"] >= 20 and 0.93 <= x["ratioMin"] and x["ratioMax"] <= 1.07, f"{pos} simulated means vs projections: {x}"
        assert lo <= x["sd"] <= hi, f"{pos} simulated spread {x['sd']:.2f} (box scores: K 4.6, D/ST 5.9)"
    assert r["sim"]["corr"]["qbOppDst"] < -0.2, f"a D/ST doesn't move against the QB it faces: {r['sim']['corr']}"
    ss = r["sim"]["startSit"]
    assert ss["kd"] == 0 and ss["best"] == ss["slots"] and ss["bestKd"] == 2, f"start/sit with kickers and defenses: {ss}"
    e = r["espn"]
    assert e["roster"] == e["want"] and e["slots"]["K"] == 1 and e["slots"]["DST"] == 1 and not e["report"]["unmatched"]
    assert e["report"]["kdst"] == 0 and e["report"]["ignoredScoring"] == 0
    s_ = e["scoring"]
    assert s_["fg60"] == s_["fg50"] == 5 and s_["dTd"] == 6 and s_["stTd"] == 6 and s_["fgMiss"] == -1
    assert s_["paTier"] == [10, 7, 0, 0, 0, 0, 0, 0, -4] and s_["yaTier"] == [5, 0, 0, 0, 0, 0, 0, 0, -7]


@test
def kdst_builder_output_is_sane():
    """The fixed build's kickers and defenses: one D/ST per team with ESPN's id, kickers matched to teams, weekly
    stat lines of the right length with tier chances that add up."""
    import kdst
    DB = json.load(open(KD_DB))
    d = [p for p in DB["players"] if p["p"] == "DST"]
    k = [p for p in DB["players"] if p["p"] == "K"]
    assert len(d) == 32 and len({p["t"] for p in d}) == 32 and all(p["id"] == "DST-" + p["t"] and p["espn"] < -16000 for p in d)
    assert len(k) >= 28 and len({p["t"] for p in k}) >= 28
    assert DB["kdst"]["kComp"] == kdst.K_COMP and DB["kdst"]["dComp"] == kdst.D_COMP
    assert abs(sum(p for _, p in DB["kdst"]["sim"]["paResid"]) - 1) < 1e-3
    for p in d + k:
        n = len(kdst.D_COMP if p["p"] == "DST" else kdst.K_COMP)
        assert len(p["s"]) == n and len(p["f"]) == n and p["kw"], p["n"]
        for w, v in p["kw"].items():
            assert len(v) == n and min(v[:9 if p["p"] == "DST" else n]) >= 0, (p["n"], w)
            if p["p"] == "DST":
                assert abs(sum(v[9:18]) - 1) < 0.01 and abs(sum(v[18:27]) - 1) < 0.01, (p["n"], w, "tier chances")


@test
def kdst_backtest_beats_naive_references():
    """The kicker and D/ST replay beats each unit's season-to-date average (needs the season files in work/)."""
    work = os.path.join(ROOT, "work")
    need = ["s23.csv", "s24.csv", "s25.csv", "games.csv"]
    if not all(os.path.exists(os.path.join(work, f)) for f in need):
        print("      (kicker/D-ST backtest check skipped: no season files in work/)")
        return
    import kdst_backtest as kb
    cwd = os.getcwd()
    os.chdir(work)
    try:
        weeks = {2025: list(range(3, 13))}
        A = kb.predict(values(load_params_file()), weeks)
        B = kb.baselines(A, weeks)
    finally:
        os.chdir(cwd)
    assert B["DST"]["model"] < B["DST"]["seasonAvg"] - 0.2, f"D/ST: {B['DST']}"
    assert B["K"]["model"] < B["K"]["seasonAvg"], f"K: {B['K']}"


@test
def gameday_slots_cover_every_game_day():
    from datetime import datetime
    import gameday_slots as gs
    S = gs.slots(gs.load_games(os.path.join(ROOT, "tests", "fixtures", "games-2026-slots.csv")))
    got = {(f"{s['at']:%m-%d %H:%M}", s["tag"], len(s["games"])) for s in S}
    want = {("10-22 18:52", "late-thu", 1), ("10-25 08:07", "late-sun-am", 1), ("10-25 11:37", "late-sun", 11),
            ("11-25 18:37", "late-wed", 1), ("11-26 11:37", "late-thu-am", 2), ("11-26 18:57", "late-thu", 1),
            ("11-27 13:37", "late-fri", 1), ("12-19 15:37", "late-sat", 2), ("12-25 11:37", "late-fri", 3),
            ("01-07 18:52", "late-thu", 0)}
    assert want <= got, f"missing slots: {sorted(want - got)}"
    assert not any(s["at"].weekday() == 0 for s in S), "Monday games get no slot of their own"
    assert len(S) == 16, f"{len(S)} slots for weeks 7, 12, 15, 16, 18 (expected 16)"
    p = gs.plan(S, datetime.fromisoformat("2026-11-26T11:41-05:00"))
    assert p["current"]["tag"] == "late-thu-am" and p["next"]["cron"] == "CRON_TZ=America/New_York 57 18 26 11 *", p
    p = gs.plan(S, datetime.fromisoformat("2027-01-10T11:40-05:00"))
    assert p["current"]["tag"] == "late-sun" and p["next"] is None, p


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(ROOT, "improve"))
    fails = 0
    for t in TESTS:
        try:
            t()
            print(f"ok    {t.__name__}")
        except Exception:
            fails += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"{len(TESTS) - fails}/{len(TESTS)} passed")
    sys.exit(1 if fails else 0)
