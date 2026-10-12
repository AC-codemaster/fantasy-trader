# Fantasy Trader — rookie priors after the NFL draft (each May)

Purpose: add the new draft class to the rookie-prior model, refit it on every completed class, regrade last
year's class on its real rookie season, and update `data/rookie/` so the builder and the backtest have priors
for the new rookies. Model and method: `docs/rookie-model.md`. Nothing here changes the live projections by
itself: `rookie_prior` in `params/params.json` decides how much the prior counts, and only the weekly
improvement loop moves it.

Repo: github.com/AC-codemaster/fantasy-trader (private). Work on a branch, merge only when tests pass. The
Tuesday task runs from the same repo: never leave main broken, never edit `data/freeze` or `data/inputs`,
never change gates, tests' thresholds or `params/params.json` values here.

Y = this year's draft class (the year of this run).

1. `add_repo` owner `AC-codemaster`, repo `fantasy-trader`, access `push`; clone it (generous timeout),
   `cd` into it, `git checkout -b rookie-draft-<Y>`, `mkdir -p work && cd work`.
2. Check the class is out: `curl -sSLf https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv | grep -c "^<Y>,"`
   should be about 257. If it's 0, the release isn't updated yet: stop, create a one-time scheduled task for
   a week later with the same prompt, and report.
3. `python3 ../rookie/rookie_model.py all --cache rk --last <Y>` — downloads (nflverse draft picks, combine,
   players, weekly stats and rosters; cfbfastR-data college stats through season Y−1), rebuilds
   `data/rookie/players.csv`, refits and rewrites `predictions.csv` and `model.json`. Check the printed
   college match rate for the new class (≥ 85%; lower means college names changed: look at
   `rookie/college.py` ALIAS and say so) and that the variant line names a feature set for <Y>.
   If a college file failed to download, the model still runs on the other features: say so in the report.
4. `python3 ../backtest/fetch_history.py <Y−3> <Y−2> <Y−1>` (season files for the replays), then
   `python3 ../rookie/evaluate_rookies.py --cache rk --backtest-dir . --rookie-prior 0.25,0.5,1`.
   Note `HOLD` (holdout classes) and `MOCK` (mock-draft classes) at the top of `rookie/evaluate_rookies.py`:
   extend each by the class whose rookie season just finished (Y−1) before running.
5. Update `docs/rookie-model.md`: keep the narrative, refresh the numbers in "In plain language" from the new
   `data/rookie/eval/summary.md`, replace the tables section with it, and add a dated paragraph "Regrade of
   the <Y−1> class": how last year's rookies did against their priors (from `data/rookie/eval/holdout_players.csv`,
   season Y−1: miss, bias, biggest hits and misses).
6. From the repo root: `python3 tests/run_tests.py` (must pass; the rookie test checks the class the builder's
   SEASON names). From `work/`: `python3 ../improve/improve.py --neutral-check` must print OK if
   `rookie_prior` is 0 (with a nonzero `rookie_prior` the backtest legitimately changes when priors change:
   then run `python3 ../improve/improve.py --only rookie_prior --dry-run` instead and report it).
7. Changelog: append to `ledger/changelog.md`
   `## <date> — rookie priors: <Y> class added` with the class size, the feature set chosen, the holdout
   numbers vs the pick curve and the regrade in one line each.
8. Commit on the branch, merge into main (`git checkout main && git pull && git merge --no-ff rookie-draft-<Y>`),
   rerun the tests on main, push. On a conflict, merge (never rebase main), rerun tests, push. If anything
   fails, push the branch unmerged and report.
9. Mirror `docs/rookie-model.md` to project doc `claude/rookie-model.md` (Projects tool, `project_write`
   with `local_path`).
10. Next year: create a one-time scheduled task for <Y+1>-05-05 ~10:00 America/New_York with the same prompt
    (list scheduled tasks first; don't duplicate one that exists).
11. Report: class size and the top projected rookies (name, team, pick, projected PPR/G), the regrade of last
    year's class, the holdout and mock-draft headline numbers, anything that failed.
