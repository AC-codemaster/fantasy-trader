# Improvement loop, 2026-11-10 (2026-w10)

Live parameters v3. Backtest weeks: 2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–9.
- Probation: probation damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25: 5 later weeks so far (old − new +0.007, z 1.58)
- Probation: probation rookie_prior 0 → 0.25: 4 later weeks so far (old − new +0.004, z 0.4)
- Live parameters on the backtest: average miss 5.181 over 9,014 player-games (calibration slope 0.97).
- Backtest vs live engine (2026-w07, hindsight): r 0.993, mean difference 0.44 pts — OK.
- Tested team_prior 3 → 3.5 (lean: RB opportunities): -0.0012 ± 0.0005 pts (z -2.21) → rejected: overall z -2.21 (needs ≤ -2.5); gain 0.0012 pts (needs ≥ 0.002)
- Tested team_prior 3 → 2.5 (lean: RB opportunities): +0.0016 ± 0.0006 pts (z 2.55) → rejected: overall z 2.55 (needs ≤ -2.5); gain -0.0016 pts (needs ≥ 0.002); worse in 2024 (z 3.1); worse in 2025 (z 1.18)
- Tested decay 0.9 → 0.925 (lean: RB opportunities): +0.0005 ± 0.0009 pts (z 0.51) → rejected: overall z 0.51 (needs ≤ -2.5); gain -0.0005 pts (needs ≥ 0.002); worse in 2025 (z 1.4)
- Tested decay 0.9 → 0.875 (lean: RB opportunities): +0.0004 ± 0.0009 pts (z 0.42) → rejected: overall z 0.42 (needs ≤ -2.5); gain -0.0004 pts (needs ≥ 0.002); worse in 2026 (z 2.03)
- Tested damp 0.35 → 0.3 (lean: RB opportunities): +0.0022 ± 0.0008 pts (z 2.67) → rejected: overall z 2.67 (needs ≤ -2.5); gain -0.0022 pts (needs ≥ 0.002); worse in 2025 (z 2.8); worse in 2026 (z 1.96); worse for TE (z 2.13); worse for WR (z 3.21)
- Tested prior_games 3 → 3.5 (lean: RB opportunities): +0.0018 ± 0.0008 pts (z 2.15) → rejected: overall z 2.15 (needs ≤ -2.5); gain -0.0018 pts (needs ≥ 0.002); worse in 2024 (z 2.23); worse in 2025 (z 1.1); worse for RB (z 2.87)
- Tested prior_games 3 → 2.5 (lean: RB opportunities): -0.0010 ± 0.0009 pts (z -1.02) → rejected: overall z -1.02 (needs ≤ -2.5); gain 0.0010 pts (needs ≥ 0.002)
- Tested K_ptd 250 → 312 (rotation): -0.0002 ± 0.0003 pts (z -0.86) → rejected: overall z -0.86 (needs ≤ -2.5); gain 0.0002 pts (needs ≥ 0.002)
- Kickers and D/ST on their replay: average miss 4.179 over 2,392 player-games (D/ST 4.583, K 3.771).
- Tested k_fg 40 → 50 (kickers and D/ST, rotation): +0.0003 ± 0.0003 pts (z 1.09) → rejected: overall z 1.09 (needs ≤ -2.5); gain -0.0003 pts (needs ≥ 0.002); worse in 2026 (z 1.32)
- Tested k_fg 40 → 32 (kickers and D/ST, rotation): -0.0003 ± 0.0003 pts (z -1.01) → rejected: overall z -1.01 (needs ≤ -2.5); gain 0.0003 pts (needs ≥ 0.002)

No change adopted this week.
