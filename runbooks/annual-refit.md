# Fantasy Trader — yearly refit of the fixed constants, then the sealed holdout (each February)

Purpose: the weekly loop tunes `params/params.json`; a few constants are fitted from history once a year
instead and live in `params/annual.json`: aging curves (`yoy`, used by `pipeline/build_db.py` and
`backtest/backtest_core.py`), game-environment elasticities (`env_k`, written into the engine's `ENV_K` line by
`tools/ftlib.py` and used by the backtest), low-volume cuts (`low_volume`) and the FAAB breakout-pool
thresholds (`faab`). `tools/annual_refit.py` refits them from all completed seasons (recent ones weighted
more) and adopts new values only if they pass the improvement loop's backtest gate (`improve.gate`). Then the
most recent completed season, which nothing was fitted or gated on, is evaluated once.

Repo: github.com/AC-codemaster/fantasy-trader (private). Work on a branch; merge only when tests pass and the
neutral check is OK. Never edit `data/freeze`, `data/inputs`, the gate thresholds or the tests' thresholds.

H = the most recent completed regular season (e.g. 2026 in February 2027).

1. `add_repo` owner `AC-codemaster`, repo `fantasy-trader`, access `push`; clone it (generous timeout), `cd`
   into it, `git checkout -b annual-refit-<year>`, `mkdir -p work && cd work`.
2. Data: `python3 ../pipeline/build_db.py --fetch` (games, ids; the build itself may fail out of season:
   that's fine as long as games.csv and db_playerids.csv downloaded), then
   `python3 ../backtest/fetch_history.py <H−2> <H−1> <H>`. If parquet fails: `pip install --break-system-packages "pyarrow<21"`.
3. Baseline for the neutral check: `python3 ../improve/improve.py --neutral-check` (it checks both replays, the
   offense and the kickers and D/ST). If either says CHANGED because its saved champion is stale (the note says so),
   delete that one's files (`../data/backtest/champion.*` or `kdst_champion.*`), run
   `python3 ../improve/improve.py --dry-run --budget 1` (a dry run recreates them), and run the neutral check
   again: it must print OK before you go on.
4. Refit: `python3 ../tools/annual_refit.py --cache rk` (10–20 minutes). It prints and writes
   `../ledger/annual_last_run.md`: the refitted values, each candidate through the gate, what was adopted
   (`params/annual.json` version + 1 and a changelog entry "annual constants vN"), and the sealed holdout.
   `--dry-run` first if you want to look without writing; the holdout only runs in the real run.
5. **Sealed holdout (last, once).** The refit fits on seasons up to H−1 and gates on H−2 and H−1 only.
   After any adoption, the script evaluates the final constants on season H (weeks 2–18) exactly once and
   appends the result to `../ledger/holdout.jsonl` (season, average miss, by position, calibration, and the
   refit vs the constants before). It refuses to evaluate the same H again: never delete or edit that line,
   never rerun the holdout by hand, and never tune anything after looking at it. If the holdout says the refit
   made season H worse (refitVsBefore z ≥ 2), do not revert it here: report it prominently; the user decides.
6. Checks, from the repo root: `python3 tests/run_tests.py` must pass (the annual test checks that the
   builder, backtest and engine read the same `annual.json`, and that a new version has its changelog entry).
   If something was adopted, the backtest legitimately changes, so instead of the neutral check run
   `python3 ../improve/improve.py --dry-run --budget 1` from work/ and confirm it runs and the parity line is OK.
   Then refresh the champion on the new constants: delete `data/backtest/champion.*` and rerun that dry run
   (it recreates them), and `python3 ../improve/improve.py --neutral-check` must print OK. (The kickers' and
   defenses' replay doesn't use `annual.json`: its champion stays.)
7. FAAB thresholds are not refitted automatically (no backtest can grade them); the report lists them. If the
   user wants a change, they say so.
7b. Start/sit distributions (`params/dist.json`): from `work/`, `python3 ../dist/bt_frames.py` then
   `python3 ../dist/fit_dist.py fit --write --start ../params/dist.json` (15–20 minutes). It refits the spreads and
   correlations with a holdout check (fit on the earliest backtest season, test on the later ones: CRPS vs the
   role-blind baseline, percentile coverage, chance-of-reaching-t calibration, teammate and opponent
   correlations), then on every season, and refits the chance-he-plays table from the last three seasons'
   injury reports, and the kicker and D/ST spreads and links (`kdst`: fit_kdst, the last four seasons' box scores).
   Keep the new file only if the holdout CRPS beats the baseline and the coverage stays within
   two points of 10/50/90%; otherwise `git checkout -- ../params/dist.json` and report. Tests must pass either way
   (they check the simulated kicker and D/ST spreads stay near the box scores). The kicker and D/ST league
   constants themselves (rates, lines, distance mix) are refitted at every build from the history window, so
   nothing else is annual for them.
7c. Waiver upside bank (`params/stash.json`, `docs/waivers.md`): from `work/`,
   `python3 ../backtest/fetch_history.py <H−3> <H−2> <H−1> <H>` (brings two seasons more), then
   `python3 ../waivers/stash_study.py frames --seasons <H−3>,<H−2>,<H−1>,<H>` (a minute a season; a season's frames
   replay with the live parameters) and `python3 ../waivers/stash_study.py fit --write`. It prints the held-out checks;
   keep the new bank only if the thinned bank's stash-zone rank correlation still beats the projection-only line and
   the calibration holds (the test `stash_bank_is_sane` checks both); otherwise `git checkout -- ../params/stash.json`
   and report.
8. Commit on the branch ("Annual refit <year>: <what changed or 'no change'>"), merge into main
   (`git checkout main && git pull && git merge --no-ff annual-refit-<year>`), rerun the tests on main, push.
   On failure push the branch unmerged and report.
9. Mirror `ledger/changelog.md` to project doc `claude/model-changelog.md`.
10. Next year: create a one-time scheduled task for <year+1>-02-20 ~10:00 America/New_York with the same
    prompt (list scheduled tasks first; don't duplicate).
11. Report: what was refitted and adopted (with the gate numbers), what was rejected and why, the sealed
    holdout line for H, and anything that failed.
