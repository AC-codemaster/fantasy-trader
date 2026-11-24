# Improvement loop, 2026-11-24 (2026-w12)

Live parameters v3. Backtest weeks: 2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–11.
- Probation: probation damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25: 7 later weeks so far (old − new +0.010, z 2.59)
- Probation: probation rookie_prior 0 → 0.25: 6 later weeks so far (old − new +0.009, z 1.05)
- Live parameters on the backtest: average miss 5.191 over 9,422 player-games (calibration slope 0.969).
- Backtest vs live engine (2026-w11, hindsight): r 0.987, mean difference 0.56 pts — OK.
- Tested K_ypc 100 → 125 (lean: RB level): +0.0001 ± 0.0002 pts (z 0.43) → rejected: overall z 0.43 (needs ≤ -2.5); gain -0.0001 pts (needs ≥ 0.002); worse in 2024 (z 2.33)
- Tested K_ypc 100 → 80 (lean: RB level): -0.0000 ± 0.0002 pts (z -0.02) → rejected: overall z -0.02 (needs ≤ -2.5); gain 0.0000 pts (needs ≥ 0.002); worse in 2026 (z 2.06); worse for TE (z 2.07)
- Tested K_rtd 150 → 188 (lean: RB level): +0.0000 ± 0.0003 pts (z 0.08) → rejected: overall z 0.08 (needs ≤ -2.5); gain -0.0000 pts (needs ≥ 0.002); worse in 2024 (z 1.73)
- Tested K_rtd 150 → 120 (lean: RB level): +0.0001 ± 0.0003 pts (z 0.37) → rejected: overall z 0.37 (needs ≤ -2.5); gain -0.0001 pts (needs ≥ 0.002); worse in 2026 (z 1.9); worse for TE (z 3.07); worse for WR (z 2.04)
- Tested K_two 400 → 500 (rotation): -0.0001 ± 0.0000 pts (z -1.6) → rejected: overall z -1.6 (needs ≤ -2.5); gain 0.0001 pts (needs ≥ 0.002)
- Tested K_two 400 → 320 (rotation): +0.0001 ± 0.0000 pts (z 1.59) → rejected: overall z 1.59 (needs ≤ -2.5); gain -0.0001 pts (needs ≥ 0.002); worse in 2026 (z 1.84)
- Expert defaults expertWeight 0.2 → 0.25, weeklyExpert 0.25 → 0.3 on 4 graded weeks: -0.0090 ± 0.0044 (z -2.03) → passes
- Kickers and D/ST on their replay: average miss 4.167 over 2,500 player-games (D/ST 4.564, K 3.768).
- Tested k_kvol 40 → 50 (kickers and D/ST, rotation): -0.0001 ± 0.0005 pts (z -0.11) → rejected: overall z -0.11 (needs ≤ -2.5); gain 0.0001 pts (needs ≥ 0.002)
- Tested k_kvol 40 → 32 (kickers and D/ST, rotation): +0.0002 ± 0.0005 pts (z 0.39) → rejected: overall z 0.39 (needs ≤ -2.5); gain -0.0002 pts (needs ≥ 0.002); worse in 2024 (z 1.56)

**Adopted:** expertWeight 0.2 → 0.25, weeklyExpert 0.25 → 0.3 (parameters v4).

**Withdrawn:** the adopted change failed `tests/run_tests.py` (`trade_engine_regressions`: trade finder sample league 6 "both" deals, needs ≥ 10; 0 lopsided when asked, needs ≥ 1). Live parameters stay at v3.
