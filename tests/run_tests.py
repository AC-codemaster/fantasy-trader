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
    pj = load_params_file()
    src_b = open(os.path.join(ROOT, "pipeline", "build_db.py")).read()
    for k, v in pj["params"].items():
        assert v["min"] <= v["value"] <= v["max"], f"{k} outside its bounds"
        assert ("step" in v) != ("mult" in v), f"{k} needs exactly one of step / mult"
        assert v["layer"] in ("builder", "engine") and v["eval"] in ("backtest", "live", "none"), k
        if v["layer"] == "builder":
            assert f'prm("{k}"' in src_b or (k.startswith("K_") and 'prm("K_" + k_' in src_b), f"builder doesn't read {k}"
        else:
            assert k in ENGINE_KEYS, f"engine doesn't read {k}"
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
    for ph in ("{{DB}}", "{{ENGINE}}", "{{UI}}", "{{BUILDER}}", "{{RUNBOOK}}", "{{PARAMS}}", "{{INJNEWS}}"):
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
    pj = load_params_file()
    assert improve.stepped(pj["params"]["decay"], 1.0, +1) is None          # at the bound
    assert improve.stepped(pj["params"]["K_cr"], 40, +1) == 50.0


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
