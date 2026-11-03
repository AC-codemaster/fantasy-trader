# Improvement loop, 2026-11-03 (2026-w09)

Live parameters v3. Backtest weeks: 2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–8.
- Probation: probation damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25: 4 later weeks so far (old − new +0.003, z 0.61)
- Live parameters on the backtest: average miss 5.188 over 8,794 player-games (calibration slope 0.975).
- Backtest vs live engine (2026-w07, hindsight): r 0.993, mean difference 0.44 pts — OK.
- Tested team_prior 3 → 3.5 (lean: RB opportunities): -0.0014 ± 0.0005 pts (z -2.59) → rejected: gain 0.0014 pts (needs ≥ 0.002)
- Tested team_prior 3 → 2.5 (lean: RB opportunities): +0.0018 ± 0.0006 pts (z 2.92) → rejected: overall z 2.92 (needs ≤ -2.5); gain -0.0018 pts (needs ≥ 0.002); worse in 2024 (z 3.1); worse in 2025 (z 1.18); worse for QB (z 2.34); worse for TE (z 2.0)
- Tested decay 0.9 → 0.925 (lean: RB opportunities): +0.0006 ± 0.0009 pts (z 0.66) → rejected: overall z 0.66 (needs ≤ -2.5); gain -0.0006 pts (needs ≥ 0.002); worse in 2025 (z 1.4)
- Tested decay 0.9 → 0.875 (lean: RB opportunities): +0.0002 ± 0.0009 pts (z 0.22) → rejected: overall z 0.22 (needs ≤ -2.5); gain -0.0002 pts (needs ≥ 0.002); worse in 2026 (z 1.6)
- Tested damp 0.35 → 0.3 (lean: RB opportunities): +0.0021 ± 0.0008 pts (z 2.5) → rejected: overall z 2.5 (needs ≤ -2.5); gain -0.0021 pts (needs ≥ 0.002); worse in 2025 (z 2.8); worse in 2026 (z 1.61); worse for TE (z 2.07); worse for WR (z 3.31)
- Tested prior_games 3 → 3.5 (lean: RB opportunities): +0.0016 ± 0.0008 pts (z 1.97) → rejected: overall z 1.97 (needs ≤ -2.5); gain -0.0016 pts (needs ≥ 0.002); worse in 2024 (z 2.23); worse in 2025 (z 1.1); worse for RB (z 2.92)
- Tested prior_games 3 → 2.5 (lean: RB opportunities): -0.0008 ± 0.0010 pts (z -0.87) → rejected: overall z -0.87 (needs ≤ -2.5); gain 0.0008 pts (needs ≥ 0.002)
- Tested K_ptd 250 → 312 (rotation): -0.0002 ± 0.0003 pts (z -0.75) → rejected: overall z -0.75 (needs ≤ -2.5); gain 0.0002 pts (needs ≥ 0.002)
- Kickers and D/ST on their replay: average miss 4.183 over 2,332 player-games (D/ST 4.595, K 3.768).
- Tested k_fg 40 → 50 (kickers and D/ST, rotation): +0.0002 ± 0.0003 pts (z 0.81) → rejected: overall z 0.81 (needs ≤ -2.5); gain -0.0002 pts (needs ≥ 0.002)
- Tested k_fg 40 → 32 (kickers and D/ST, rotation): -0.0002 ± 0.0003 pts (z -0.73) → rejected: overall z -0.73 (needs ≤ -2.5); gain 0.0002 pts (needs ≥ 0.002)

No change adopted this week.
