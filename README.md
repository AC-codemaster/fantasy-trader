# Fantasy Trader

NFL fantasy projection model and trade engine for ESPN leagues, with a weekly scorecard and an
improvement loop that tunes the model on its own.

- Page: https://claude.ai/artifact/QYtsAKr3WaL59s1xWMcw1C (assembled from this repo every Tuesday)
- Scorecard: https://claude.ai/artifact/XzYv5c3LZNYyQVCUen71Rz
- Model notes: `docs/model.md` · Changelog: `ledger/changelog.md`

## Layout

| Path | What |
|---|---|
| `engine/engine.js` | valuation engine (projections, market view, trade evaluation); one `PARAMS` line holds its tuned constants |
| `page/template.html`, `page/ui.js` | the page shell and UI code; `tools/make_page.py` assembles the published page |
| `pipeline/build_db.py` | builds the weekly player database (usage shares, efficiency, injuries and this week's game status, game-day inactives, expert ranks) |
| `dist/`, `params/dist.json` | weekly points distributions behind the Start/Sit tab: the reference simulation (`sim.py`), its fit and checks (`fit_dist.py`, `bt_frames.py`), the fitted numbers; `docs/start-sit.md` |
| `pipeline/scorecard.py` | freezes each week's projections and grades them (incl. hindsight and rest of season) |
| `params/params.json` | every tuned constant, with bounds and step; the only file the improvement loop edits |
| `params/annual.json` | constants refitted once a year (aging curves, game-environment elasticities, low-volume cuts, FAAB thresholds), read by the builder, backtest and engine; `tools/annual_refit.py` |
| `rookie/`, `data/rookie/` | rookie-prior model (draft slot, college, combine, landing spot → rookie share and efficiency), its per-class predictions and evaluation; `docs/rookie-model.md` |
| `backtest/` | replay of the model at past weeks (`backtest_core.py`), evaluation harness, history download |
| `improve/improve.py` | the weekly improvement loop: probation, experiments, gate, ledger |
| `ledger/` | `experiments.jsonl` (every experiment), `changelog.md` (adopted/reverted), `state.json`, `last_run.md` |
| `data/inputs/<season>/w<week>/` | what the page ran on each week (db, injuries, params, engine): replayable |
| `data/freeze`, `data/ros`, `data/graded`, `data/scorecard` | frozen projections, grades, scorecard data |
| `tests/` | checks that must pass before publishing (page parity, trade-engine regressions, season grouping, gate) |
| `runbooks/` | `weekly.md` (the Tuesday scheduled task), `gameday.md` (pre-kickoff refreshes on every game day, with inactives; one self-scheduling task), `improve-agent.md` (structural changes), `rollover.md`, and the offseason tasks: `rookie-draft.md` (May), `annual-refit.md` (February, with the sealed holdout), `trade-autopsy.md` (January); `saturday.md` is retired |
| `tools/trade_autopsy.py` | every trade in a league: the model at the trade date vs what each side gained; acceptance re-graded |

## The weekly loop

Every Tuesday morning a scheduled task runs `runbooks/weekly.md`: download the week's data, gather
injuries, grade last week's frozen projections (also rerun with who actually played, so news after
Tuesday isn't blamed on the model), run the improvement loop, rebuild with the live parameters, test,
publish the page, freeze this week's projections and archive their inputs, publish the scorecard, commit.

More scheduled runs follow `runbooks/gameday.md` before games lock: one task that schedules itself from
`games.csv` (`tools/gameday_slots.py`) — Thursday about 6:52 pm ET (after the Thursday game's inactives), Sunday
about 8:07 am ET only in weeks with a morning international game, Sunday about 11:37 am ET (after the 1 pm
inactives), and every other game day (Thanksgiving, Christmas, late-season Saturdays) 83 minutes before its first
kickoff. They fold in the final injury reports and game-day inactives, republish the page and freeze a
pre-kickoff snapshot for the scorecard. The weekly run checks that the task is armed (`weekly.md` step 10b).

The improvement loop adopts at most one parameter change a week, only when it clearly lowers the
average miss over two-plus seasons of backtest weeks, and re-checks every adopted change on the weeks
played after it (reverting it if they don't back it up). See `runbooks/improve-agent.md`.

## Offseason

Scheduled tasks, each a one-time run that schedules next year's: trade autopsy (Jan 12), annual refit of
`params/annual.json` with the sealed holdout of the season just finished (Feb 20), rookie priors for the new
draft class (May 5), plus the August rollover (`runbooks/rollover.md`).

## Running locally

```
mkdir -p work && cd work
python3 ../pipeline/build_db.py --fetch          # inputs + db.json
python3 ../backtest/fetch_history.py 2024 2025 2026
python3 ../tests/run_tests.py
python3 ../backtest/evaluate.py --set decay=0.875   # one experiment by hand
python3 ../improve/improve.py --dry-run             # what this week's loop would do
python3 ../rookie/rookie_model.py all --cache rk    # rookie priors (downloads into rk/)
python3 ../tools/make_page.py --db db.json --injnews injury_news.json --out fantasy-trader.html
```
