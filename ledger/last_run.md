# Improvement loop, 2026-10-28 (2026-w08)

Live parameters v3. Backtest weeks: 2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–7.
- Live parameters on the backtest: average miss 5.181 over 8,584 player-games (calibration slope 0.98).
- Backtest vs live engine (2026-w07, hindsight): r 0.993, mean difference 0.44 pts — OK.
- Tested team_prior 3 → 3.5 (lean: RB opportunities): -0.0012 ± 0.0005 pts (z -2.31) → rejected: overall z -2.31 (needs ≤ -2.5); gain 0.0012 pts (needs ≥ 0.002)
- Tested team_prior 3 → 2.5 (lean: RB opportunities): +0.0016 ± 0.0006 pts (z 2.65) → rejected: overall z 2.65 (needs ≤ -2.5); gain -0.0016 pts (needs ≥ 0.002); worse in 2024 (z 3.1); worse in 2025 (z 1.18); worse for QB (z 2.1)
- Tested decay 0.9 → 0.925 (lean: RB opportunities): +0.0008 ± 0.0009 pts (z 0.84) → rejected: overall z 0.84 (needs ≤ -2.5); gain -0.0008 pts (needs ≥ 0.002); worse in 2025 (z 1.4)
- Tested decay 0.9 → 0.875 (lean: RB opportunities): -0.0000 ± 0.0009 pts (z -0.01) → rejected: overall z -0.01 (needs ≤ -2.5); gain 0.0000 pts (needs ≥ 0.002)
- Tested damp 0.35 → 0.3 (lean: RB opportunities): +0.0021 ± 0.0008 pts (z 2.46) → rejected: overall z 2.46 (needs ≤ -2.5); gain -0.0021 pts (needs ≥ 0.002); worse in 2025 (z 2.8); worse in 2026 (z 1.58); worse for WR (z 3.38)
- Tested prior_games 3 → 3.5 (lean: RB opportunities): +0.0017 ± 0.0008 pts (z 2.01) → rejected: overall z 2.01 (needs ≤ -2.5); gain -0.0017 pts (needs ≥ 0.002); worse in 2024 (z 2.23); worse in 2025 (z 1.1); worse for RB (z 2.77)
- Tested prior_games 3 → 2.5 (lean: RB opportunities): -0.0009 ± 0.0010 pts (z -0.97) → rejected: overall z -0.97 (needs ≤ -2.5); gain 0.0009 pts (needs ≥ 0.002)
- Tested K_ptd 250 → 312 (rotation): -0.0002 ± 0.0003 pts (z -0.77) → rejected: overall z -0.77 (needs ≤ -2.5); gain 0.0002 pts (needs ≥ 0.002)
- Kickers and D/ST on their replay: average miss 4.189 over 2,276 player-games (D/ST 4.609, K 3.766).
- Tested k_fg 40 → 50 (kickers and D/ST, rotation): +0.0002 ± 0.0003 pts (z 0.83) → rejected: overall z 0.83 (needs ≤ -2.5); gain -0.0002 pts (needs ≥ 0.002)
- Tested k_fg 40 → 32 (kickers and D/ST, rotation): -0.0002 ± 0.0003 pts (z -0.75) → rejected: overall z -0.75 (needs ≤ -2.5); gain 0.0002 pts (needs ≥ 0.002)

No change adopted this week.
