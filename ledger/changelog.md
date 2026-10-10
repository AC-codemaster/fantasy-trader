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
