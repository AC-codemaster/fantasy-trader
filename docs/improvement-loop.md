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
- Two goals: model (Tuesday page vs FantasyPros Tuesday, same information) and product (our page after
  the Saturday refresh vs FantasyPros final, all the week's news).
- Saturday refresh (scheduled task, Saturdays 9:47 ET, `runbooks/saturday.md`): Friday's final injury
  reports go into the page, which is republished and frozen as the week's "late" projections
  (`freeze --tag late`; teams that already played keep their Tuesday numbers). No grading or model changes.
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
4. Gate: gain ≥ 0.002 pts, z ≤ −2.5, no season z ≥ 1, no position z ≥ 2, calibration slope and backup-QB bias
   not worse; engine settings also not worse on archived live weeks with hindsight (z < 1.5, once 4+ weeks).
   Expert defaults: one step toward the sweep's best pair on graded live weeks (4+ weeks, z ≤ −2).
   Single steps on different parameters that each help with z ≤ −2 are also tested together as a bundle
   (up to 4).
5. Adopt at most one change or bundle (largest passing gain); write params.json (version + 1), changelog, probation entry; log
   every experiment in `ledger/experiments.jsonl`. Save the champion's backtest predictions for the neutral
   check.
6. Parity: the backtest is compared with the engine's hindsight projections on the latest graded week; if
   they drift apart (r < 0.85 or mean difference > 2 pts) nothing is adopted until it's fixed.
7. Kickers and D/ST (since Oct 19, 2026): their twelve settings (`"eval": "kdst"`) are tested on their own replay,
   `backtest/kdst_backtest.py` (every D/ST and every kicker who kicked, same evaluation weeks, ESPN standard; ≈ 2,200
   player-games, clustered by week), with the same gate. Up to 3 a run: the scorecard's "K level" / "DST level"
   leans, then a rotation of one setting a week up and down. When both replays have a passing change, the one with
   the larger gain relative to its own champion's average miss is adopted (still one change a week). Probation re-checks
   K/DST changes on their replay; the neutral check covers both replays (`data/backtest/kdst_champion.*`).
- Structural changes: the scheduled agent may add one new parameter (neutral default reproduces the old
  model, verified by the neutral check and tests) when a lean persists 3 weeks that no parameter fixes;
  the loop then tests it like any other. Rules in `runbooks/improve-agent.md`.
- Scope: projections only. The market/acceptance side has no ground truth to tune against yet.

First full sweep (Oct 10, gate v1 with a 0.01-pt minimum): all 46 single steps rejected. The model sits
near a local optimum; the best steps were damp 0.30→0.35 (−0.0029, z −3.3), env_scale 1.0→1.1 (−0.0028,
z −3.4), w1 0.8→0.7 (−0.0020, z −3.2), low_target 2→2.25 (−0.0013, z −3.5). Gate v2 lowers the minimum
gain to 0.002 (the z bar is unchanged) and adds bundles; constants alone won't move the miss much
further, which is why the structural-change path exists.

## Tests (`tests/run_tests.py`)
Parameter file consistency; assembled page = archived Week 5 engine; runner reproduces the Week 5 freeze;
trade-engine regressions on Week 5 data (Allen for two genuine starters: median acceptance < 10% and < 35%
of pairs at 50%+; Shough for T. Warren + J. Warren in the user's league < 20%, fixture anonymized);
scorecard season grouping; gate behaviour; kickers and defenses on a fixed build
(`tests/fixtures/db-kdst-w06.json`): engine scoring = `pipeline/kdst.py`, K/D-ST slots never used as flex, one of
each drafted per team, near-zero trade prices, none in the finder, simulated means = projections and spreads near
box scores, the ESPN import of their players and scoring; the builder's K/DST records; the K/DST replay beats each
unit's season average (when season files are in `work/`).

## Rookie prior, yearly constants and offseason tasks (Oct 12, 2026)
- Rookie-prior model (`rookie/`, `data/rookie/`, `docs/rookie-model.md`): drafted rookies had no usage prior
  (only the depth-chart prior for QBs). The model predicts a drafted rookie's share of team carries/targets
  and per-opportunity efficiency from information available after the draft; per class it is fitted on
  earlier classes only, and the feature set (draft slot alone won every year so far over college production,
  combine, age and landing spot) is chosen on earlier classes too. New builder parameter `rookie_prior`
  (0 = old model exactly; neutral check OK, db.json identical, tests): shares count like
  `rookie_prior × prior_games` games, efficiency gets pseudo-opportunities at the predicted rates. Marked
  `new`, so the next Tuesday run tests it first. Dry run on Oct 12: 0 → 0.25 −0.0093 ± 0.0028 pts (z −3.31,
  passes the gate); 0.5 passes (z −2.81); 1.0 doesn't (z −2.17). Not adopted outside the loop.
- `params/annual.json`: the constants that were hardcoded in three places (aging YOY curves, game-environment
  ENV_K, low-volume cuts, FAAB thresholds) now live in one file read by `build_db.py`, `backtest_core.py` and
  the engine (`ftlib.engine_source` writes its `ENV_K` line, like `PARAMS`; archived engines keep theirs).
  Version 1 = the old numbers (test `annual_constants_shared_and_reproduced`). `tools/annual_refit.py`
  refits them each February from all completed seasons, gated by `improve.gate`, then evaluates the most
  recent season once (sealed holdout, `ledger/holdout.jsonl`). Preview run on Oct 12 (holdout 2025, nothing
  written): aging −0.0023 (z −2.25, rejected), ENV_K +0.0018 (worse), low-volume cuts ×0.75 −0.0032 (z −2.58,
  would pass), ×1.25 worse.
- Fix in `improve.py`: after an adoption the saved champion predictions were those of the parameters the run
  started with (the Oct 10 file held v1 predictions under a v2 label, so the neutral check reported CHANGED on
  untouched code). It now saves the live parameters' predictions, a dry run creates a missing champion file,
  and the neutral check says when the saved champion was made with other parameter values. The champion file
  was refreshed on Oct 12 (v2, main code).
- Trade autopsy (`tools/trade_autopsy.py`, `tools/autopsy_runner.js`): for each trade, the archived engine at
  the trade week with rosters rolled back to the trade vs the players' points afterwards; acceptance re-graded.
- Offseason scheduled tasks: trade autopsy 2027-01-12, annual refit 2027-02-20, rookie priors 2027-05-05
  (each schedules next year's), alongside the August rollover.
