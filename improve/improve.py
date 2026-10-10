"""Weekly improvement loop: propose parameter changes, test them, adopt the ones that pass, undo the ones
that stop holding up. Runs every Tuesday after grading (runbooks/weekly.md), from the work folder that
holds the season files.

    python3 improve/improve.py                 # full run: probation review, experiments, at most one change
    python3 improve/improve.py --dry-run       # test and report, change nothing
    python3 improve/improve.py --only decay    # test just these parameters (both directions)
    python3 improve/improve.py --try decay=0.85 --try damp=0.35   # test exact values (one experiment each)

What it does, in order:
 1. Probation. Every adopted change is re-checked on the weeks played after it went in (data it never saw).
    After 4+ such weeks, if the old value would have done better (z ≤ -1.5) the change is reverted; after
    8 weeks it is kept for good.
 2. Experiments. Candidates come from the scorecard's flagged leans (the parameters that could explain
    each lean, in the hinted direction first) and from a rotation that walks every tunable parameter one
    step up and down over the weeks. Each is backtested on every week from week 3 of the two previous
    seasons through the last completed week, against the live parameters, on the same player-games.
    Single steps that each help significantly (z ≤ -2) are then also tested together as one bundle.
 3. Gate. A change passes only if it lowers the average miss by at least 0.002 pts with z ≤ -2.5 overall
    (team-week clustered), is not worse in any season (z < 1) or position (z < 2), keeps calibration and the
    backup-QB bias in line, and, for engine settings, is not worse on the archived live weeks replayed with
    hindsight. The expert-blend defaults are tuned on the graded live weeks instead (they need FantasyPros'
    rankings, which the backtest doesn't have): one step toward the best pair, 4+ graded weeks, z ≤ -2.
 4. At most one change per week (the passing change or bundle with the largest gain), so every change's effect can be read on its
    own. Every experiment, passed or not, goes in ledger/experiments.jsonl; adopted and reverted changes
    also in ledger/changelog.md. A value already rejected under the same live parameters isn't retried
    for 6 weeks.
"""
import argparse
import glob
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "backtest"))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import evaluate as ev  # noqa: E402
from ftlib import PARAMS_PATH, dump_params, engine_source, load_params_file, values  # noqa: E402

LEDGER = os.path.join(ROOT, "ledger")
EXP = os.path.join(LEDGER, "experiments.jsonl")
CHANGELOG = os.path.join(LEDGER, "changelog.md")
STATE = os.path.join(LEDGER, "state.json")
SCORECARD = os.path.join(ROOT, "data", "scorecard", "scorecard.json")
LAST_RUN = os.path.join(LEDGER, "last_run.md")

GATE_VERSION = 2   # v1 (Oct 9) required a 0.01-pt gain; the first full sweep showed single steps on the tuned
                   # model give 0.001-0.003 with z down to -3.5, so v2 asks for 0.002 and tests bundles
GATE = dict(z=-2.5, min_gain=0.002, combo_z=-2.0, combo_max=4, season_z=1.0, pos_z=2.0, slope_slack=0.03, bqb_slack=0.3,
            live_z=1.5, expert_z=-2.0, expert_weeks=4, probation_weeks=4, keep_weeks=8, revert_z=-1.5,
            retry_weeks=6, rotation_per_run=2, budget=8)


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(p, default):
    return json.load(open(p)) if os.path.exists(p) else default


def ledger_rows():
    return [json.loads(x) for x in open(EXP)] if os.path.exists(EXP) else []


def append_ledger(row):
    os.makedirs(LEDGER, exist_ok=True)
    with open(EXP, "a") as f:
        f.write(json.dumps(row, separators=(",", ":"), default=float) + "\n")


def week_index(label):
    """'2026-w06' -> comparable number."""
    S, w = label.split("-w")
    return int(S) * 100 + int(w)


# ----------------------------------------------------------------------------- parameter steps
def tunable(pj, kind="backtest"):
    return [k for k, v in pj["params"].items() if v.get("eval") == kind and v.get("tunable", True)]


def stepped(spec, cur, direction):
    """One step up (+1) or down (-1) from cur, inside the bounds; None if it can't move."""
    if "mult" in spec:
        new = cur * spec["mult"] if direction > 0 else cur / spec["mult"]
        new = float(round(new)) if new >= 10 else round(new, 3)
    else:
        new = round(cur + direction * spec["step"], 4)
    new = min(spec["max"], max(spec["min"], new))
    return None if abs(new - cur) < 1e-9 else new


def describe(change):
    return ", ".join(f"{k} {fmt_v(a)} → {fmt_v(b)}" for k, (a, b) in change.items())


def fmt_v(x):
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


# ----------------------------------------------------------------------------- candidates
def lean_direction(name, lean):
    """Map a lean (+ = projected too low) to the parameter direction worth trying first; 0 = both."""
    d = lean.get("direction")
    up = {"ret_disc": +1, "damp": -1, "env_scale": 0, "low_target": -1, "vet_prior": +1, "team_prior": 0,
          "prior_games": 0, "prior_moved": 0, "decay": 0}
    if d in ("up", "down") and name in up and up[name]:
        return up[name] * (1 if d == "up" else -1)
    if lean.get("area") == "calibration" and name.startswith("K_"):
        return +1 if d == "shrink" else -1
    return 0


def build_candidates(pj, sc, state, rows, label, only=None, exact=None):
    vals = values(pj)
    ver = pj.get("version")
    recent = {}
    for r in rows:
        if r.get("kind") == "backtest" and r.get("championVersion") == ver and r.get("decision") == "rejected" \
                and r.get("gateVersion") == GATE_VERSION:
            for k, (_, new) in (r.get("change") or {}).items():
                recent[(k, round(float(new), 6))] = r.get("week")
    tun = set(tunable(pj))

    def fresh(k, new):
        w = recent.get((k, round(float(new), 6)))
        return w is None or week_index(label) - week_index(w) > GATE["retry_weeks"]

    out, seen = [], set()

    def add(k, direction, source):
        new = stepped(pj["params"][k], vals[k], direction)
        if new is None or (k, new) in seen or not fresh(k, new):
            return
        seen.add((k, new))
        out.append({"change": {k: [vals[k], new]}, "source": source})

    if exact:
        for k, v in exact.items():
            if k in pj["params"] and abs(vals[k] - v) > 1e-9:
                out.append({"change": {k: [vals[k], v]}, "source": "requested"})
        return out
    if only:
        for k in only:
            if k in tun:
                add(k, +1, "requested")
                add(k, -1, "requested")
        return out
    # parameters the improvement agent just added (marked "new": true) are tried first, both directions
    for k in sorted(tun):
        if pj["params"][k].get("new"):
            add(k, +1, "new parameter")
            add(k, -1, "new parameter")
    for lean in (sc or {}).get("candidates", []):
        for k in lean.get("params", []):
            if k not in tun:
                continue
            d = lean_direction(k, lean)
            for direction in ([d] if d else [+1, -1]):
                add(k, direction, f"lean: {lean['area']}")
    order = sorted(tun)
    i = state.get("rotation", 0) % len(order)
    for j in range(GATE["rotation_per_run"]):
        k = order[(i + j) % len(order)]
        add(k, +1, "rotation")
        add(k, -1, "rotation")
    state["rotation"] = (i + GATE["rotation_per_run"]) % len(order)
    return out[:GATE["budget"]]


# ----------------------------------------------------------------------------- gate
def gate(r):
    """(passed, reasons) for a paired backtest result (evaluate.paired)."""
    why = []
    if r.get("z") is None or r["z"] > GATE["z"]:
        why.append(f"overall z {r.get('z')} (needs ≤ {GATE['z']})")
    if r["diff"] > -GATE["min_gain"]:
        why.append(f"gain {-r['diff']:.4f} pts (needs ≥ {GATE['min_gain']})")
    for S, s in r["seasons"].items():
        if s.get("z") is not None and s["z"] >= GATE["season_z"]:
            why.append(f"worse in {S} (z {s['z']})")
    for p, s in r["byPos"].items():
        if s.get("z") is not None and s["z"] >= GATE["pos_z"]:
            why.append(f"worse for {p} (z {s['z']})")
    a, b = r["champ"], r["chal"]
    if not math.isnan(a["slope"]) and abs(b["slope"] - 1) > abs(a["slope"] - 1) + GATE["slope_slack"]:
        why.append(f"calibration slope {a['slope']} → {b['slope']}")
    if a.get("backupQbBias") is not None and b.get("backupQbBias") is not None and \
            abs(b["backupQbBias"]) > abs(a["backupQbBias"]) + GATE["bqb_slack"]:
        why.append(f"backup-QB bias {a['backupQbBias']} → {b['backupQbBias']}")
    return not why, why


def trim(r):
    """The parts of a paired result worth keeping in the ledger."""
    return {k: r[k] for k in ("n", "diff", "se", "z", "seasons", "byPos")} | {
        "maeChamp": r["champ"]["mae"], "maeChal": r["chal"]["mae"], "slope": [r["champ"]["slope"], r["chal"]["slope"]],
        "backupQbBias": [r["champ"].get("backupQbBias"), r["chal"].get("backupQbBias")]}


# ----------------------------------------------------------------------------- live checks (archived weeks)
def graded_weeks(final_only=True):
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "graded", "*.csv"))):
        d = pd.read_csv(p, low_memory=False)
        if final_only and (d.status.iloc[0] != "final"):
            continue
        out.append(d)
    return out


def live_replay(vals_a, vals_b):
    """Hindsight replay of two engine parameter sets on every archived, fully graded week. Returns a paired
    result (b minus a absolute error) on fantasy-relevant players, or None if fewer than 4 weeks."""
    import scorecard as sc
    rows = []
    weeks = 0
    for G in graded_weeks():
        S, W = int(G.season.iloc[0]), int(G.week.iloc[0])
        dbp = os.path.join(ROOT, "data", "inputs", str(S), f"w{W:02d}", "db.json")
        if not os.path.exists(dbp):
            continue
        A, played, stat_teams = sc.actuals(S, W)
        games = pd.read_csv("games.csv", low_memory=False)
        done, _ = sc.done_teams(games, S, W, stat_teams)
        ids = {p["id"] for p in json.load(open(dbp))["players"]}
        avail = {"week": W, "played": sorted(played & ids), "teams": sorted(done)}
        _, Pa = sc.run_engine(engine_source(vals_a), dbp, avail=avail, lite=True)
        _, Pb = sc.run_engine(engine_source(vals_b), dbp, avail=avail, lite=True)
        D = sc.add_sw(G[(G.played == 1) & (G.game_done == 1)])
        D = D[sc.relevant(D)]
        D = D.assign(pa=D.id.map(Pa.set_index("id").page_ppr), pb=D.id.map(Pb.set_index("id").page_ppr)).dropna(subset=["pa", "pb"])
        rows.append(D[["cl", "pos", "act_ppr", "pa", "pb"]])
        weeks += 1
    if weeks < GATE["expert_weeks"]:
        return None
    D = pd.concat(rows)
    d = (D.pb - D.act_ppr).abs() - (D.pa - D.act_ppr).abs()
    m, se = ev._cluster(d, D.cl)
    return {"weeks": weeks, "n": int(len(D)), "diff": round(m, 4), "se": round(se, 4) if se else None, "z": round(m / se, 2) if se else None}


def expert_compare(G, a, b):
    """Paired miss of expert-blend settings b vs a on graded weeks G, rebuilt from the frozen parts."""
    import scorecard as sc
    D = pd.concat(G, ignore_index=True)
    D = D[(D.played == 1) & (D.game_done == 1)]
    D = sc.add_sw(D)
    D = D[sc.relevant(D)].dropna(subset=["model_ppr", "w0"])
    D = D[D.w0.astype(float) > 0]
    model, corr, wk = D.model_ppr.astype(float).values, D.corr_ppr.fillna(0).astype(float).values, D.wkexp_ppr.astype(float).values
    has = ~np.isnan(wk)
    w0 = D.w0.astype(float).values

    def predict(w, we):
        return np.maximum(0, model + corr * (w / w0) + np.where(has, we * (np.nan_to_num(wk) - model), 0))
    act = D.act_ppr.astype(float).values
    pa, pb = predict(a["expertWeight"], a["weeklyExpert"]), predict(b["expertWeight"], b["weeklyExpert"])
    m, se = ev._cluster(np.abs(pb - act) - np.abs(pa - act), D.cl)
    return {"weeks": int(D.sw.nunique()), "n": int(len(D)), "diff": round(m, 4), "se": round(se, 4) if se else None,
            "z": round(m / se, 2) if se else None}


def expert_experiment(pj, sc_json):
    """One step of the expert-blend defaults toward the best pair on the graded live weeks."""
    import scorecard as sc
    sw = (sc_json or {}).get("expertSweep")
    G = graded_weeks()
    if not sw or len(G) < GATE["expert_weeks"]:
        return None
    vals = values(pj)
    cur = {"expertWeight": vals["expertWeight"], "weeklyExpert": vals["weeklyExpert"]}
    best = sw["best"]
    change = {}
    for k in cur:
        if abs(best[k] - cur[k]) > 1e-9:
            new = stepped(pj["params"][k], cur[k], +1 if best[k] > cur[k] else -1)
            if new is not None:
                change[k] = [cur[k], new]
    if not change:
        return None
    nw = {k: change.get(k, [None, cur[k]])[1] for k in cur}
    r = expert_compare(G, cur, nw)
    ok = r["z"] is not None and r["z"] <= GATE["expert_z"] and r["diff"] <= -GATE["min_gain"]
    return {"change": change, "eval": r, "passed": ok,
            "why": [] if ok else [f"z {r['z']} (needs ≤ {GATE['expert_z']}) and gain {-r['diff']:.4f} (needs ≥ {GATE['min_gain']})"]}


# ----------------------------------------------------------------------------- adopt / revert
def write_params(pj, change, reason):
    for k, (_, new) in change.items():
        pj["params"][k]["value"] = new
    pj["version"] = int(pj.get("version", 0)) + 1
    pj["updated"] = today()
    dump_params(pj)
    with open(CHANGELOG, "a") as f:
        f.write(f"\n## {today()} — parameters v{pj['version']}: {describe(change)}\n\n{reason}\n")
    return pj["version"]


def probation_review(pj, state, label, current_season, last_done, dry):
    """Re-check adopted changes on weeks played after they went in."""
    decisions = []
    keep = []
    vals = values(pj)
    for e in state.get("probation", []):
        start = week_index(e["since"])
        post = [w for w in range(1, last_done + 1) if current_season * 100 + w >= start]
        if e.get("kind") == "live":
            G = [g for g in graded_weeks() if int(g.season.iloc[0]) * 100 + int(g.week.iloc[0]) >= start]
            if len(G) < GATE["probation_weeks"]:
                keep.append(e)
                continue
            cur = {k: vals[k] for k in ("expertWeight", "weeklyExpert")}
            old_v = dict(cur)
            for k, (prev, _) in e["change"].items():
                old_v[k] = prev
            r = expert_compare(G, cur, old_v)   # old minus current
            row = {"date": today(), "week": label, "kind": "probation", "change": e["change"], "source": "probation",
                   "championVersion": pj.get("version"), "eval": r}
            if r.get("z") is not None and r["z"] <= GATE["revert_z"]:
                row["decision"], row["reason"] = "reverted", f"old value better on {len(G)} later graded weeks (z {r['z']})"
                if not dry:
                    write_params(pj, {k: [nv, pv] for k, (pv, nv) in e["change"].items()},
                                 f"Reverted after probation on {len(G)} graded weeks (z {r['z']}).")
            elif len(G) >= GATE["keep_weeks"]:
                row["decision"], row["reason"] = "kept", f"held up over {len(G)} later graded weeks"
            else:
                row["decision"], row["reason"] = "on probation", f"{len(G)} later graded weeks so far (z {r['z']})"
                keep.append(e)
            row["summary"] = f"{row['decision']} {describe(e['change'])}: {row['reason']}"
            decisions.append(row)
            continue
        if len(post) < GATE["probation_weeks"]:
            keep.append(e)
            continue
        weeks = {current_season: post}
        old = dict(vals)
        for k, (prev, _) in e["change"].items():
            old[k] = prev
        if any(abs(old[k] - vals[k]) < 1e-9 for k in e["change"]):   # already moved on from this value
            continue
        cur_p = ev.predict(vals, weeks)
        old_p = ev.predict(old, weeks)
        r = ev.paired(cur_p, old_p)   # old minus current
        row = {"date": today(), "week": label, "kind": "probation", "change": e["change"], "source": "probation",
               "championVersion": pj.get("version"), "eval": trim(r)}
        if r.get("z") is not None and r["z"] <= GATE["revert_z"]:
            row["decision"], row["reason"] = "reverted", f"old value better on {len(post)} later weeks (z {r['z']})"
            row["summary"] = f"reverted {describe(e['change'])}: {row['reason']}"
            if not dry:
                back = {k: [nv, pv] for k, (pv, nv) in e["change"].items()}
                write_params(pj, back, f"Reverted after probation: on {len(post)} weeks played after the change, the old value "
                             f"would have missed {-r['diff']:.3f} pts less per player (z {r['z']}).")
            decisions.append(row)
        elif len(post) >= GATE["keep_weeks"]:
            row["decision"], row["reason"] = "kept", f"held up over {len(post)} later weeks (old − new {r['diff']:+.3f}, z {r['z']})"
            row["summary"] = f"kept {describe(e['change'])}"
            decisions.append(row)
        else:
            row["decision"], row["reason"] = "on probation", f"{len(post)} later weeks so far (old − new {r['diff']:+.3f}, z {r['z']})"
            row["summary"] = f"probation {describe(e['change'])}: {row['reason']}"
            decisions.append(row)
            keep.append(e)
    state["probation"] = keep   # kept and reverted changes leave probation
    return decisions


def parity_check(champ):
    """Does the backtest still describe the live model? Compare its projections with the engine's
    hindsight projections on the latest archived graded week of the current season."""
    for G in reversed(graded_weeks()):
        S, W = int(G.season.iloc[0]), int(G.week.iloc[0])
        if G.hind_model_ppr.notna().sum() < 50:
            continue
        b = champ[(champ.season == S) & (champ.week == W)][["id", "pred"]]
        if not len(b):
            continue
        M = G[(G.played == 1)][["id", "hind_model_ppr"]].merge(b, on="id").dropna()
        M = M[M.pred >= ev.MIN_PROJ]
        if len(M) < 50:
            continue
        r, mad = float(M.pred.corr(M.hind_model_ppr)), float((M.pred - M.hind_model_ppr).abs().mean())
        return {"week": f"{S}-w{W:02d}", "n": int(len(M)), "r": round(r, 3), "meanAbsDiff": round(mad, 2),
                "ok": r >= 0.85 and mad <= 2.0}
    return None


# ----------------------------------------------------------------------------- champion predictions
CHAMP = os.path.join(ROOT, "data", "backtest", "champion.csv.gz")
CHAMP_META = os.path.join(ROOT, "data", "backtest", "champion.json")


def save_champion(champ, vals, weeks, version):
    """Backtest predictions of the live parameters, for the neutral check after code changes."""
    os.makedirs(os.path.dirname(CHAMP), exist_ok=True)
    champ[["season", "week", "id", "pos", "pred", "actual"]].round(4).to_csv(CHAMP, index=False)
    json.dump({"date": today(), "paramsVersion": version, "paramsHash": ev.params_hash(vals), "codeHash": ev.code_hash(),
               "weeks": {str(k): v for k, v in weeks.items()}}, open(CHAMP_META, "w"), indent=1)


def neutral_check():
    """After a code change that adds a parameter at a neutral default: the backtest must give exactly the
    predictions saved by the last run (same weeks, same parameter values for the old parameters)."""
    if not os.path.exists(CHAMP):
        sys.exit("no saved champion predictions (data/backtest/champion.csv.gz); run improve.py once first")
    meta = json.load(open(CHAMP_META))
    weeks = {int(k): v for k, v in meta["weeks"].items()}
    old = pd.read_csv(CHAMP)
    new = ev.predict(values(load_params_file()), weeks)
    M = old.merge(new[["season", "week", "id", "pred"]], on=["season", "week", "id"], how="outer", suffixes=("_old", "_new"))
    missing = int(M.pred_old.isna().sum() + M.pred_new.isna().sum())
    diff = float((M.pred_old - M.pred_new).abs().max())
    ok = missing == 0 and diff < 1e-3
    print(f"neutral check: {len(M)} player-weeks, max difference {diff:.6f}, unmatched {missing} → {'OK' if ok else 'CHANGED'}")
    sys.exit(0 if ok else 1)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated parameters to test (both directions)")
    ap.add_argument("--try", dest="exact", action="append", default=[], help="name=value to test exactly")
    ap.add_argument("--combo", default="", help="name=value,name=value: test these together as one bundle")
    ap.add_argument("--budget", type=int, default=GATE["budget"])
    ap.add_argument("--procs", type=int, default=None)
    ap.add_argument("--neutral-check", action="store_true", help="verify a code change left the backtest unchanged")
    a = ap.parse_args()
    if a.neutral_check:
        neutral_check()
    GATE["budget"] = a.budget
    pj = load_params_file()
    state = load_json(STATE, {"rotation": 0, "probation": []})
    sc_json = load_json(SCORECARD, {})
    rows = ledger_rows()
    S, last_done = ev.current_season_and_week()
    label = f"{S}-w{last_done + 1:02d}"
    weeks = ev.eval_weeks(S, last_done)
    report = [f"# Improvement loop, {today()} ({label})", "",
              f"Live parameters v{pj.get('version')}. Backtest weeks: " + ", ".join(f"{s} wk {w[0]}–{w[-1]}" for s, w in weeks.items() if w) + "."]
    changed = None

    # 1. probation
    prob = probation_review(pj, state, label, S, last_done, a.dry_run)
    for row in prob:
        append_ledger(row) if not a.dry_run else None
        report.append(f"- Probation: {row['summary']}")
        if row["decision"] == "reverted":
            changed = row
    pj = load_params_file()   # may have been reverted

    # 2. backtest experiments
    exact = {kv.split("=")[0]: float(kv.split("=")[1]) for kv in a.exact} if a.exact else None
    cands = build_candidates(pj, sc_json, state, rows, label, only=[x for x in a.only.split(",") if x], exact=exact)
    vals = values(pj)
    champ = ev.predict(vals, weeks, a.procs)
    base = ev.summarize(champ[champ.pred >= ev.MIN_PROJ])
    report.append(f"- Live parameters on the backtest: average miss {base['mae']:.3f} over {base['n']:,} player-games (calibration slope {base['slope']}).")
    parity = parity_check(champ)
    if parity:
        report.append(f"- Backtest vs live engine ({parity['week']}, hindsight): r {parity['r']}, mean difference {parity['meanAbsDiff']} pts — {'OK' if parity['ok'] else 'OUT OF LINE: no changes adopted until fixed'}.")
    results = []
    for c in cands:
        chal_vals = dict(vals)
        for k, (_, new) in c["change"].items():
            chal_vals[k] = new
        r = ev.paired(champ, ev.predict(chal_vals, weeks, a.procs))
        ok, why = gate(r)
        live = None
        if ok and any(pj["params"][k]["layer"] == "engine" for k in c["change"]):
            live = live_replay(vals, chal_vals)
            if live and live.get("z") is not None and live["z"] >= GATE["live_z"]:
                ok, why = False, why + [f"worse on archived live weeks (z {live['z']})"]
        results.append((c, r, ok, why, live))
        report.append(f"- Tested {describe(c['change'])} ({c['source']}): {r['diff']:+.4f} ± {r['se']:.4f} pts (z {r['z']})"
                      f" → {'passes' if ok else 'rejected: ' + '; '.join(why)}")

    # 2b. bundle: single steps on different parameters that each help significantly, tested together
    combos = []
    if a.combo:
        combos.append({k: float(v) for k, v in (kv.split("=") for kv in a.combo.split(","))})
    else:
        best = {}
        for c, r, ok, why, live in results:
            if len(c["change"]) == 1 and r.get("z") is not None and r["z"] <= GATE["combo_z"] and r["diff"] < 0:
                k = next(iter(c["change"]))
                if k not in best or r["diff"] < best[k][1]["diff"]:
                    best[k] = (c, r)
        if len(best) >= 2:
            top = sorted(best.values(), key=lambda x: x[1]["diff"])[:GATE["combo_max"]]
            combos.append({next(iter(c["change"])): c["change"][next(iter(c["change"]))][1] for c, _ in top})
    for combo in combos:
        c = {"change": {k: [vals[k], v] for k, v in combo.items() if abs(vals[k] - v) > 1e-9},
             "source": "bundle of significant single steps" if not a.combo else "requested bundle"}
        if len(c["change"]) < 1:
            continue
        chal_vals = dict(vals)
        chal_vals.update({k: v for k, (_, v) in c["change"].items()})
        r = ev.paired(champ, ev.predict(chal_vals, weeks, a.procs))
        ok, why = gate(r)
        live = None
        if ok and any(pj["params"][k]["layer"] == "engine" for k in c["change"]):
            live = live_replay(vals, chal_vals)
            if live and live.get("z") is not None and live["z"] >= GATE["live_z"]:
                ok, why = False, why + [f"worse on archived live weeks (z {live['z']})"]
        results.append((c, r, ok, why, live))
        report.append(f"- Tested bundle {describe(c['change'])}: {r['diff']:+.4f} ± {r['se']:.4f} pts (z {r['z']})"
                      f" → {'passes' if ok else 'rejected: ' + '; '.join(why)}")

    # 3. expert-blend defaults on graded live weeks
    expx = expert_experiment(pj, sc_json)
    if expx:
        report.append(f"- Expert defaults {describe(expx['change'])} on {expx['eval']['weeks']} graded weeks: {expx['eval']['diff']:+.4f} ± {expx['eval']['se']} (z {expx['eval']['z']})"
                      f" → {'passes' if expx['passed'] else 'rejected'}")

    # 4. adopt at most one change
    winner = None
    blocked = (parity is not None and not parity["ok"]) or changed is not None or a.dry_run
    passing = sorted([x for x in results if x[2]], key=lambda x: x[1]["diff"])
    if passing and not blocked:
        winner = ("backtest",) + passing[0]
    elif expx and expx["passed"] and not blocked:
        winner = ("live", expx, None, True, [], None)
    for kind, c, r, ok, why, live in [("backtest",) + x for x in results]:
        decision = "promoted" if winner and winner[1] is c else ("passed, not adopted" if ok else "rejected")
        row = {"date": today(), "week": label, "kind": "backtest", "change": c["change"], "source": c["source"],
               "championVersion": pj.get("version"), "gateVersion": GATE_VERSION, "eval": trim(r), "live": live, "decision": decision,
               "reason": "; ".join(why) if why else ("largest passing gain" if decision == "promoted" else
                                                    ("another change was adopted this week" if not blocked else "adoption blocked this run")),
               "summary": f"{describe(c['change'])}: {r['diff']:+.4f} ± {r['se']:.4f} (z {r['z']})"}
        if not a.dry_run:
            append_ledger(row)
    if expx:
        decision = "promoted" if winner and winner[0] == "live" else ("passed, not adopted" if expx["passed"] else "rejected")
        if not a.dry_run:
            append_ledger({"date": today(), "week": label, "kind": "live", "change": expx["change"], "source": "expert sweep",
                           "championVersion": pj.get("version"), "eval": expx["eval"], "decision": decision,
                           "reason": "; ".join(expx["why"]), "summary": f"{describe(expx['change'])}: {expx['eval']['diff']:+.4f} (z {expx['eval']['z']})"})
    if winner and not a.dry_run:
        if winner[0] == "backtest":
            c, r = winner[1], winner[2]
            seas = ", ".join(f"{k} {v['diff']:+.3f}" for k, v in r["seasons"].items())
            reason = (f"Backtest: average miss {r['champ']['mae']:.3f} → {r['chal']['mae']:.3f} on {r['n']:,} player-games "
                      f"({r['diff']:+.4f} ± {r['se']:.4f}, z {r['z']}; by season {seas}). Source: {c['source']}. "
                      f"On probation: re-checked on the weeks played from {label} on.")
            ver = write_params(pj, c["change"], reason)
            # an earlier change to the same parameter is superseded: the new entry is checked against it
            state["probation"] = [e for e in state.get("probation", []) if not set(e["change"]) & set(c["change"])]
            state["probation"].append({"change": c["change"], "since": label, "kind": "backtest", "version": ver})
            report.append(f"\n**Adopted:** {describe(c['change'])} (parameters v{ver}).")
        else:
            x = winner[1]
            reason = f"Graded live weeks: {x['eval']['diff']:+.4f} ± {x['eval']['se']} pts (z {x['eval']['z']}, {x['eval']['weeks']} weeks). Leagues that follow the model's expert defaults pick this up."
            ver = write_params(pj, x["change"], reason)
            state["probation"] = [e for e in state.get("probation", []) if not set(e["change"]) & set(x["change"])]
            state["probation"].append({"change": x["change"], "since": label, "kind": "live", "version": ver})
            report.append(f"\n**Adopted:** {describe(x['change'])} (parameters v{ver}).")
    elif changed:
        report.append(f"\n**Reverted:** {describe(changed['change'])}.")
    else:
        report.append("\nNo change adopted this week." + (" (dry run)" if a.dry_run else ""))
    if not a.dry_run:
        pj_now = load_params_file()
        tested = {k for c, *_ in results for k in c["change"]}
        if any(pj_now["params"][k].pop("new", None) for k in tested if k in pj_now["params"]):
            dump_params(pj_now)
        save_champion(champ, vals, weeks, pj.get("version"))
    state["lastRun"] = {"date": today(), "week": label, "tested": len(results) + (1 if expx else 0),
                        "adopted": describe(winner[1]["change"]) if winner and not a.dry_run else None, "parity": parity}
    if not a.dry_run:
        json.dump(state, open(STATE, "w"), indent=1)
        open(LAST_RUN, "w").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
