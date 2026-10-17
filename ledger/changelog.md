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
