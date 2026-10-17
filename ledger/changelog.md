# Model changelog

Every change to the live model's parameters, newest last. Written by the weekly improvement loop
(improve/improve.py) when a change passes the gate or is reverted after probation; structural changes
made by the improvement agent are logged here too. The full record of every experiment, including the
rejected ones, is ledger/experiments.jsonl.

## 2026-10-09 — parameters v1: starting point

Constants as of Oct 9, 2026 (backtested Oct 5 and Oct 8): prior_games 3, prior_moved 1.5, vet_prior 0.6,
team_prior 3, decay 0.9, blend2 0.5, w1 0.8, w2 0.4, low_target 2, shrinkage K as before, damp 0.3,
ret_disc 0.85, env_scale 1, expertWeight 0.2, weeklyExpert 0.25. Backtest: average miss 5.200 on 7,931
player-games (2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–4).

## 2026-10-10 — parameters v2: damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25

Backtest: average miss 5.200 → 5.190 on 7,931 player-games (-0.0091 ± 0.0017, z -5.52; by season 2024 -0.005, 2025 -0.013, 2026 -0.012). Source: bundle of significant single steps. On probation: re-checked on the weeks played from 2026-w05 on.

## 2026-10-12 — structural: rookie_prior (not active until the gate adopts it)

Drafted rookies had no usage or efficiency prior (QBs: depth chart only). New rookie-prior model
(`docs/rookie-model.md`): share of team carries/targets and per-opportunity efficiency from draft slot, fitted on
earlier classes only (college production, combine, age and landing spot were tested and did not beat draft slot).
Holdout 2019–25: rookie PPR/G miss 3.02 (pick-only points curve 2.96). New builder parameter `rookie_prior`, value 0
(= the old model: neutral check OK, db.json identical), marked new. Dry run: 0 → 0.25 −0.0093 ± 0.0028 (z −3.31),
passes; the Tuesday loop decides. Also: constants moved to `params/annual.json` (version 1 = old values, identical
output), and improve.py now saves the live parameters' champion predictions after an adoption.

## 2026-10-13 — parameters v3: rookie_prior 0 → 0.25

Backtest: average miss 5.208 → 5.199 on 8,117 player-games (-0.0095 ± 0.0028, z -3.44; by season 2024 -0.009, 2025 -0.004, 2026 -0.034). Source: new parameter. On probation: re-checked on the weeks played from 2026-w06 on.

## 2026-10-17 — repo sync: the Oct 13 run's commit never reached GitHub

The Tuesday run of Oct 13 adopted v3, published the page (version 1791900897-3d9a) and the scorecard and mirrored the
changelog to the project, but its commit was never pushed, so main stayed on v2 and had no Week 6 freeze (the Saturday
run of Oct 17 stopped for that reason). Restored from the published page: params/params.json v3 (identical to the
page's embedded parameter file), the entry above, the probation entry in ledger/state.json, and one recovered row in
ledger/experiments.jsonl for the adoption (that run's other experiment rows are lost). The Week 6 Tuesday freeze was
rebuilt from the same published page with its original freeze time (`freeze --now`), which reproduces exactly what
that page showed; the FantasyPros snapshot is the one DynastyProcess had at that time. Runbooks now check that the
push landed.

## 2026-10-17 — structural (projections unchanged): start/sit distributions, NFL injury report, pre-kickoff refreshes

Asked for by the user: a start/sit tool on the weekly points model and a floor-vs-ceiling tool, refreshed with the
best injury news right before Thursday night and Sunday games.
- Weekly points distributions: a simulation of each game on the projection's own expected stat line (shared
  passing environment and script, team volume and efficiency, role shocks re-split inside the team, early exits,
  Poisson plays, gamma yards with per-play spread measured from box scores, a QB's passing = his receivers'
  receiving). `dist/` (reference simulation, fit, checks), `params/dist.json` v1, engine `simWeek` / `startSit` /
  `needCalc`, page tab Start/Sit, `docs/start-sit.md`. Holdout (fit 2024, test 2025-26): CRPS 3.654 vs 3.700 for a
  role-blind baseline, better at every position and in standard scoring (not fitted on); actual scores below the
  simulated 10/50/90th percentiles 9.4/52.4/90.2% of the time. Chance he plays from 2023-25 injury reports
  (Questionable: 94% full practice, 75% limited, 55% none; QBs far lower). Finding: at the same position and
  projection, usage style doesn't reliably change a player's real spread (under 5%), so the page shows floors and
  ceilings but no "high floor / high ceiling" labels. Projections unchanged: neutral check OK (13,701 player-weeks,
  max difference 0.00005); `data/backtest/champion.*` refreshed for parameters v3.
- Builder (db v6): this week's game status `gs`, last practice `pr`, game-day `gd` from a new `gameday.json`
  (inactives), `DB.opp`, `DB.kick`, `DB.gameday`. The NFL's own Out and Doubtful designations for the current week
  now count as missing the game even without a CBS row (news, not formula: the backtest takes availability from
  who played). Every existing field identical otherwise (checked on the Oct 17 build).
- Scorecard: several pre-kickoff snapshots per week (`freeze --tag late-thu|late-sun|...`); the "late" view uses,
  for each player, the latest snapshot frozen before his kickoff.
- Runbooks: `gameday.md` (Thursday ~6:52 pm and Sunday ~11:37 am ET, after inactives) replaces the Saturday run;
  `weekly.md` recalibrates the distribution means after the improvement loop (5b) and checks the push landed;
  `annual-refit.md` refits the distributions (7b).
- Scheduled pre-kickoff runs: Thursday 6:52 pm, Sunday 8:07 am (international weeks only), Sunday 11:37 am ET,
  plus one-time runs for this season's other game days (Wed Nov 25, Thanksgiving daytime, Fri Nov 27, Sat Dec 19,
  Christmas); `weekly.md` step 10b creates any that are missing (flexed Saturday games, later seasons). On Oct 17 the
  Sunday task was also fired once as a Saturday catch-up (`late-sat`) to publish the new page.
