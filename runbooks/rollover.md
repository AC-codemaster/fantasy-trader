# Fantasy Trader — season rollover (each August, before Week 1)

The pipeline still names seasons in a few places. A scheduled task runs this each August; do it on a
branch, merge only when the tests pass.

1. `pipeline/build_db.py`: `SEASON = <new season>`; the files it reads are named by season
   (`s24/s25/s26`, `r26`, `inj26`, `snaps26`, `dc26`, `prior25`/`prior24`, `t24/t25/t26`, `team25/team24`,
   `g26/g25/g24`, `s25/s24` fields). Rename them to "this season / last season / the season before"
   (e.g. `s0/s1/s2`, fields `g0/g1/g2`) rather than shifting the years, so next year needs only `SEASON`.
   Keep the database fields the engine reads in step with step 2 (bump the db version `v`).
2. `engine/engine.js` and `page/ui.js`: the same field renames (`g26`→ this season's games, `g25`/`g24`,
   `s25`/`s24` track-record components, `TRACK_W24`), and any "2026" text.
2b. Kickers and defenses: `pipeline/kdst.py` is season-relative (it takes whatever seasons it's given); in the
   builder the `RAW` dict of player stats is keyed by season year and follows the file renames, and the kicker
   and D/ST records use `g26/g25/g24` and `s25/s24` like everyone (rename with the rest). ESPN's D/ST ids
   (−16000 − ESPN team id) don't change. `tests/fixtures/db-kdst-w06.json` is a 2026 build: keep it as it is
   (convert it once only if the engine stops reading the old field names).
3. `backtest/backtest_core.py`: already relative (S−2, S−1, S). `backtest/kdst_backtest.py` too. `backtest/evaluate.py`: the evaluation
   window moves on its own (two previous seasons + current). Check `fetch_history.py` downloads them.
4. `pipeline/scorecard.py`: already season-aware (keys are season + week). `FLAGS` uses `g26/g25/g24`:
   follow the renames.
5. Weekly runbook: the `fetch_history.py` seasons line.
6. Preseason data: `fp_preseason.csv` must be rebuilt for the new season (delete it before `--fetch`).
7. Run `python3 tests/run_tests.py`, a full `build_db.py --fetch`, `improve.py --dry-run`, assemble the page
   and open it. The Week 5 2026 fixtures in `tests/` keep working only if the engine still reads the old
   field names; if the rename breaks them, convert the fixture db once with a small script (keep the
   original under `data/inputs/2026/`).
8. The ledger and parameters carry over unchanged: they are the model's memory. Re-enable the weekly
   scheduled task for the new season (it pauses itself in the offseason), and arm the gameday task for the new
   season's first slot exactly as `runbooks/weekly.md` step 10b says.
