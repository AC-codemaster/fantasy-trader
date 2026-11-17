# Improvement loop, 2026-11-17 (2026-w11)

Live parameters v3. Backtest weeks: 2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–10.
- Probation: probation damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25: 6 later weeks so far (old − new +0.009, z 2.15)
- Probation: probation rookie_prior 0 → 0.25: 5 later weeks so far (old − new +0.009, z 1.02)
- Live parameters on the backtest: average miss 5.196 over 9,224 player-games (calibration slope 0.972).
- Backtest vs live engine (2026-w07, hindsight): r 0.993, mean difference 0.44 pts — OK.
- Tested team_prior 3 → 3.5 (lean: RB opportunities): -0.0013 ± 0.0005 pts (z -2.41) → rejected: overall z -2.41 (needs ≤ -2.5); gain 0.0013 pts (needs ≥ 0.002)
- Tested team_prior 3 → 2.5 (lean: RB opportunities): +0.0017 ± 0.0006 pts (z 2.79) → rejected: overall z 2.79 (needs ≤ -2.5); gain -0.0017 pts (needs ≥ 0.002); worse in 2024 (z 3.1); worse in 2025 (z 1.18); worse for QB (z 2.07); worse for TE (z 2.19)
- Tested decay 0.9 → 0.925 (lean: RB opportunities): +0.0002 ± 0.0009 pts (z 0.2) → rejected: overall z 0.2 (needs ≤ -2.5); gain -0.0002 pts (needs ≥ 0.002); worse in 2025 (z 1.4)
- Tested decay 0.9 → 0.875 (lean: RB opportunities): +0.0007 ± 0.0009 pts (z 0.8) → rejected: overall z 0.8 (needs ≤ -2.5); gain -0.0007 pts (needs ≥ 0.002); worse in 2026 (z 2.96)
- Tested damp 0.35 → 0.3 (lean: RB opportunities): +0.0023 ± 0.0008 pts (z 2.8) → rejected: overall z 2.8 (needs ≤ -2.5); gain -0.0023 pts (needs ≥ 0.002); worse in 2025 (z 2.8); worse in 2026 (z 2.22); worse for TE (z 2.22); worse for WR (z 3.4)
- Tested prior_games 3 → 3.5 (lean: RB opportunities): +0.0017 ± 0.0008 pts (z 2.1) → rejected: overall z 2.1 (needs ≤ -2.5); gain -0.0017 pts (needs ≥ 0.002); worse in 2024 (z 2.23); worse in 2025 (z 1.1); worse for RB (z 2.71)
- Tested prior_games 3 → 2.5 (lean: RB opportunities): -0.0008 ± 0.0009 pts (z -0.89) → rejected: overall z -0.89 (needs ≤ -2.5); gain 0.0008 pts (needs ≥ 0.002)
- Tested K_ptd 250 → 312 (rotation): -0.0002 ± 0.0003 pts (z -0.68) → rejected: overall z -0.68 (needs ≤ -2.5); gain 0.0002 pts (needs ≥ 0.002)
- Kickers and D/ST on their replay: average miss 4.176 over 2,448 player-games (D/ST 4.587, K 3.762).
- Tested k_fg 40 → 50 (kickers and D/ST, rotation): +0.0004 ± 0.0003 pts (z 1.22) → rejected: overall z 1.22 (needs ≤ -2.5); gain -0.0004 pts (needs ≥ 0.002); worse in 2026 (z 1.62)
- Tested k_fg 40 → 32 (kickers and D/ST, rotation): -0.0004 ± 0.0003 pts (z -1.14) → rejected: overall z -1.14 (needs ≤ -2.5); gain 0.0004 pts (needs ≥ 0.002)

No change adopted this week.
