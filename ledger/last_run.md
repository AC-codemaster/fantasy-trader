# Improvement loop, 2026-10-20 (2026-w07)

Live parameters v3. Backtest weeks: 2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–6.
- Live parameters on the backtest: average miss 5.183 over 8,376 player-games (calibration slope 0.983).
- Backtest vs live engine (2026-w06, hindsight): r 0.992, mean difference 0.46 pts — OK.
- Tested K_fl 250 → 312 (rotation): -0.0000 ± 0.0001 pts (z -0.75) → rejected: overall z -0.75 (needs ≤ -2.5); gain 0.0000 pts (needs ≥ 0.002)
- Tested K_fl 250 → 200 (rotation): +0.0000 ± 0.0001 pts (z 0.78) → rejected: overall z 0.78 (needs ≤ -2.5); gain -0.0000 pts (needs ≥ 0.002); worse in 2025 (z 2.24)
- Tested K_int 300 → 375 (rotation): +0.0002 ± 0.0001 pts (z 1.51) → rejected: overall z 1.51 (needs ≤ -2.5); gain -0.0002 pts (needs ≥ 0.002); worse in 2025 (z 1.81)
- Tested K_int 300 → 240 (rotation): -0.0002 ± 0.0001 pts (z -1.43) → rejected: overall z -1.43 (needs ≤ -2.5); gain 0.0002 pts (needs ≥ 0.002); worse in 2026 (z 1.19)
- Kickers and D/ST on their replay: average miss 4.195 over 2,220 player-games (D/ST 4.606, K 3.780).
- Tested k_dst 10 → 12 (kickers and D/ST, rotation): -0.0003 ± 0.0005 pts (z -0.52) → rejected: overall z -0.52 (needs ≤ -2.5); gain 0.0003 pts (needs ≥ 0.002)
- Tested k_dst 10 → 8 (kickers and D/ST, rotation): +0.0004 ± 0.0006 pts (z 0.73) → rejected: overall z 0.73 (needs ≤ -2.5); gain -0.0004 pts (needs ≥ 0.002); worse in 2025 (z 1.19)

No change adopted this week.
