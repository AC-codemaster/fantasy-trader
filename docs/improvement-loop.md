# Fantasy Trader — repo, scorecard and improvement loop (since Oct 9, 2026)

Model design notes (Oct 1–8) are in the project doc `claude/fantasy-trader-model.md`; this covers what
changed when the project moved into the repo github.com/AC-codemaster/fantasy-trader.

## One source of truth
- Before: the engine lived in the page (what ran), in `engine.js` (project doc) and re-written in Python
  inside `backtest_core.py`; the builder in the project doc and inside the page (the page copy had fallen
  behind: no `SEASON2_BLEND`); `scorecard.py` in two places.
- Now: the repo holds one copy of each. `tools/make_page.py` assembles the page from `page/template.html`,
  `engine/engine.js`, `page/ui.js`, the week's data, and embeds the builder, runbook and parameters as
  fallbacks. Checked on Oct 9: the assembled page computes exactly what the live page did (max difference 0
  over 10,348 player-weeks). Project docs are one-way mirrors written by the weekly run.

## Parameters
- `params/params.json` holds every tuned constant: builder (prior_games, prior_moved, vet_prior, team_prior,
  decay, blend2, w1, w2, low_target, shrinkage K_*, env_shrink) and engine (damp, ret_disc, env_scale,
  expertWeight, weeklyExpert), each with bounds, a step (or multiplier), a layer and how it's evaluated.
- `build_db.py` reads it (`prm("name", default)`), the engine gets a `const PARAMS = {...}` line written by
  make_page, and `tools/ftlib.backtest_params` maps it onto `backtest_core` settings. Check: the backtest
  reproduces the Oct 5 numbers (base 5.277 → live 5.093 on 4,458 player-games; notes said 5.279 → 5.098).
- Expert weights: leagues follow the model's defaults (`settings.expertAuto`) until the user moves either
  slider; leagues saved on the old defaults (20% / 25%) count as following. The user's league (85%) keeps
  its own setting.

## Scorecard additions
- Freeze archives the inputs (`data/inputs/<S>/w<WW>/`: db.json, injury_news.json, cbs_injuries.tsv,
  params.json, engine.js) and the rest-of-season vectors (`data/ros/`). Week 5 2026 was archived from the
  live page on Oct 9 before Tuesday's refresh would have replaced it.
- Hindsight: grading reruns the archived week with who actually played (the league's manual "out" field:
  played → healthy, didn't → out). Diagnostics and the improvement loop use it, so news after Tuesday is
  not blamed on the model.
- Rest of season: each frozen week's projections for later weeks are graded by horizon, and ordering is
  compared with FantasyPros' rest-of-season rank at the freeze.
- Season-aware grouping (season + week keys everywhere), fixing a bug that would have mixed 2026 and 2027.
- Two goals: model (vs FantasyPros Tuesday, same information) and product (vs final, all the news).
- Expert-weight sweep: page = max(0, model + corr·w/w0 + we·(weekly expert − model)) rebuilt exactly from
  frozen parts for every pair of weights.

## Improvement loop (`improve/improve.py`, every Tuesday after grading)
1. Probation review of adopted changes on weeks played after adoption (revert at z ≤ −1.5 after 4+ weeks,
   keep after 8).
2. Candidates: parameters marked new, then parameters mapped to the scorecard's flagged leans (hinted
   direction first), then a rotation of 2 parameters per week up and down. Budget 8. Values rejected under
   the same live parameters aren't retried for 6 weeks.
3. Backtest every candidate on weeks 3–18 of the two previous seasons + week 2 to the latest week of this
   season (≈ 8,000 player-games; champion projection ≥ 3 PPR), paired with the live parameters, standard
   errors clustered by team-week.
4. Gate: gain ≥ 0.01 pts, z ≤ −2.5, no season z ≥ 1, no position z ≥ 2, calibration slope and backup-QB bias
   not worse; engine settings also not worse on archived live weeks with hindsight (z < 1.5, once 4+ weeks).
   Expert defaults: one step toward the sweep's best pair on graded live weeks (4+ weeks, z ≤ −2).
5. Adopt at most one change (lowest z); write params.json (version + 1), changelog, probation entry; log
   every experiment in `ledger/experiments.jsonl`. Save the champion's backtest predictions for the neutral
   check.
6. Parity: the backtest is compared with the engine's hindsight projections on the latest graded week; if
   they drift apart (r < 0.85 or mean difference > 2 pts) nothing is adopted until it's fixed.
- Structural changes: the scheduled agent may add one new parameter (neutral default reproduces the old
  model, verified by the neutral check and tests) when a lean persists 3 weeks that no parameter fixes;
  the loop then tests it like any other. Rules in `runbooks/improve-agent.md`.
- Scope: projections only. The market/acceptance side has no ground truth to tune against yet.

## Tests (`tests/run_tests.py`)
Parameter file consistency; assembled page = archived Week 5 engine; runner reproduces the Week 5 freeze;
trade-engine regressions on Week 5 data (Allen for two genuine starters: median acceptance < 10% and < 35%
of pairs at 50%+; Shough for T. Warren + J. Warren in the user's league < 20%, fixture anonymized);
scorecard season grouping; gate behaviour.
