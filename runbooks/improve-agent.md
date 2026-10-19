# Fantasy Trader — improvement agent

The model improves itself in two ways, both judged by the same evidence and the same gate. No human
suggestion is needed for either; the user can still ask for an experiment (`improve.py --try name=value`).

## 1. Parameter tuning (automatic, every Tuesday)
Two replays: the offense backtest (`backtest/backtest_core.py`, params with `"eval": "backtest"`) and the kicker and
D/ST replay (`backtest/kdst_backtest.py`, params with `"eval": "kdst"`; the model is `pipeline/kdst.py`, notes in
`docs/kdst.md`). Each run tests up to 8 offense changes and up to 3 K/DST settings, all against the same gate, and
adopts at most one change in total.

`improve/improve.py` does it all: probation review, experiments from the scorecard's leans and from a
rotation through every tunable parameter, the gate, at most one adopted change, the ledger. Nothing to
decide by hand. Read `ledger/last_run.md` afterwards for the report.

The gate (see the docstring of improve.py): backtest average miss lower by ≥ 0.002 pts with z ≤ −2.5 over
every week from week 3 of the two previous seasons to the latest week, not worse in any season (z < 1)
or position (z < 2), calibration and backup-QB bias not worse; engine settings also not worse on the
archived live weeks with hindsight. Expert-blend defaults move one step toward the best pair on graded
live weeks (4+ weeks, z ≤ −2). Probation: re-checked on the weeks played after adoption; reverted if the
old value would have been better (z ≤ −1.5 after 4+ weeks), kept after 8.

## 2. Structural changes (the agent, at most one every two weeks)
Parameters can only fix what the formula can express. When a lean persists that no parameter explains,
the agent may add one new adjustment to the model. Conditions — all of them:
- The same lean is flagged ("Leans the improvement loop will test" in `data/scorecard/scorecard.md`) in
  each of the last 3 graded weeks, on the hindsight basis (model error, not news), and
- the improvement loop has tested that lean's mapped parameters in both directions without adopting
  anything (check `ledger/experiments.jsonl`), and
- no structural change was made in the last 14 days (check `ledger/changelog.md` for "structural").

If so, design ONE new adjustment that addresses the lean, written as a new tunable parameter whose
neutral value reproduces the current model exactly (for example a multiplier at 1.0, or an additive term
at 0). Implement it in all places that compute projections:
- `pipeline/build_db.py` (read it with `prm("name", neutral)`) and/or `engine/engine.js` (add it to the
  `PARAMS` line and `ENGINE_KEYS` in `tools/ftlib.py`),
- `backtest/backtest_core.py` (add it to `BASE` at the neutral value and use it in `project`), and the
  mapping in `tools/ftlib.py` `backtest_params`,
- `params/params.json`: the entry with value = neutral, sensible min/max and step, `"layer"`, `"eval": "backtest"`,
  `"desc"`, and `"new": true` so the next improvement run tries it first.
- For a lean on kickers or defenses ("K level", "DST level"): the adjustment goes in `pipeline/kdst.py` only (a new
  key in `kdst.DEFAULTS` at its neutral value, used in `profiles`/`project_k`/`project_dst`; the builder and the
  K/DST replay both read it from there) and in `params/params.json` with `"eval": "kdst"`.
Then verify, in this order, and undo the whole change (`git checkout -- .`) if any check fails:
1. `python3 tests/run_tests.py` passes (from the repo root).
2. `python3 ../improve/improve.py --neutral-check` from `work/` prints OK for both replays (the backtests are
   unchanged at the neutral value).
3. If you touched build_db.py: build db.json before and after the change (`cp db.json db_before.json`
   first) and confirm every player's `m`, `a`, `s`, `f` values are identical.
4. `python3 ../improve/improve.py --only <name> --dry-run` runs without errors.
Commit with a message starting "Structural: " that names the lean and the new parameter, and add a
`## <date> — structural: <name>` entry to `ledger/changelog.md` explaining the lean (with its numbers)
and the idea. The regular improvement run in step 5 of the weekly runbook then tests it like any other
parameter: it is only used if it passes the gate.

Never: change the gate thresholds, the evaluation weeks, the tests' thresholds, or the scorecard's
grading to make a change pass; edit frozen weeks or archived inputs; adopt more than one change in a
run; touch the trade/market side (perceived values, acceptance) through this loop — it has no ground
truth to test against yet. Anything else that looks like a bug: describe it in the weekly report instead
of fixing it unasked.
