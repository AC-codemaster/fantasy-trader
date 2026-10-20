# Fantasy Trader — projection scorecard

Updated 2026-10-20T14:26:48Z.
Frozen, waiting for games: 2026 week 7 (414 players, frozen 2026-10-20T14:26:44Z).
Model parameters: version 3; 58 changes tested, 2 adopted, 0 reverted.

## Where we stand

- Model goal (vs FantasyPros Tuesday, same information): 2 of 6 weeks; miss lead 4.9% vs 3.0% target (significant) — not met yet
- Product goal (our page right before kickoff vs FantasyPros final, all the week's news): 2 of 6 weeks; miss lead 2.9% vs 3.0% target (significant) — not met yet
- vs FantasyPros Tuesday: average miss 5.65 vs 5.94 (-0.29 ± 0.09, n=317) → ahead; start/sit 57.2% vs 54.3% (+2.9 ± 1.3) → ahead
- vs FantasyPros final, our page right before kickoff: average miss 5.61 vs 5.78 (-0.17 ± 0.08, n=327) → ahead; start/sit 56.3% vs 56.5% (-0.1 ± 1.2) → even (not significant)
- vs FantasyPros final, our model with hindsight availability: average miss 5.62 vs 5.78 (-0.16 ± 0.08, n=327) → ahead; start/sit 55.7% vs 56.5% (-0.8 ± 1.2) → even (not significant)
- News after Tuesday: knowing who played would have changed our miss by -0.02 pts (5.62 vs 5.64)

## Cumulative (fantasy-relevant players who played, PPR)

| Source | n | Avg miss | Actual − proj | RMSE | r | Rank corr | Start/sit % |
|---|---|---|---|---|---|---|---|
| Our page (Tuesday) | 328 | 5.64 | 0.94 | 7.05 | 0.53 | 0.423 | 56.4 |
| Our page right before kickoff | 328 | 5.61 | 0.80 | 6.99 | 0.54 | 0.433 | 56.3 |
| Our usage model (no expert blend) | 328 | 5.68 | 0.87 | 7.09 | 0.52 | 0.418 | 56.2 |
| Our page with hindsight availability | 328 | 5.62 | 0.65 | 6.98 | 0.54 | 0.413 | 55.7 |
| FantasyPros, Tuesday | 317 | 5.94 | -0.12 | 7.20 | 0.50 | 0.427 | 54.3 |
| FantasyPros, final | 327 | 5.78 | -0.17 | 6.98 | 0.53 | 0.430 | 56.5 |

## By week

| Season-week | Status | Ours | Hindsight | FP Tue | FP final | Start/sit ours vs FP final |
|---|---|---|---|---|---|---|
| 2026-5 | final | 6.01 | 6.03 | 6.30 | 6.09 | 56.2 vs 56.2 |
| 2026-6 | final | 5.27 | 5.22 | 5.60 | 5.46 | 56.5 vs 56.7 |

## Rest of season (what trade values run on)

| Weeks ahead | n | Avg miss | Actual − proj | Rank corr ours | Rank corr FP ROS rank |
|---|---|---|---|---|---|
| 0 | 316 | 5.65 | 0.73 | 0.480 | 0.380 |
| 1 | 140 | 5.05 | 0.26 | 0.434 | 0.355 |

## Expert weights (rebuilt from the frozen parts, 328 players)

Current 0.20 / 0.25: miss 5.640. Best 0.30 / 0.70: 5.620 (-0.020 ± 0.041).

## Diagnostics (hindsight; actual − projection, + = projected too low)

- QB: 0.75 ± 1.01 (n=51; our miss 5.76 vs FP 6.11)
- RB: 0.48 ± 0.61 (n=101; our miss 5.34 vs FP 5.36)
- WR: 0.83 ± 0.56 (n=127; our miss 5.64 vs FP 5.80)
- TE: 0.40 ± 0.97 (n=49; our miss 5.98 vs FP 6.23)
- first game back: 1.75 ± 1.07 (n=13; our miss 3.48 vs FP 4.77)
- teammate out: role up 1+ pt: 0.65 ± 0.67 (n=105; our miss 6.07 vs FP 6.22)
- injury tag (Q/limited/DNP): 0.65 ± 0.88 (n=41; our miss 4.70 vs FP 5.15)
- rookie (no NFL history): -0.90 ± 1.30 (n=24; our miss 4.70 vs FP 5.19)
- veteran (RB 28+, WR/TE 30+, QB 35+): 0.44 ± 0.72 (n=65; our miss 4.35 vs FP 4.80)
- team expected 8%+ above its usual score: 1.62 ± 0.69 (n=115; our miss 6.28 vs FP 6.43)
- team expected 8%+ below its usual score: -0.66 ± 0.64 (n=75; our miss 4.42 vs FP 4.55)
- favored by 6+: 0.27 ± 0.81 (n=54; our miss 5.26 vs FP 5.46)
- underdog by 6+: 0.55 ± 0.86 (n=50; our miss 4.43 vs FP 4.29)
- we're 3+ pts below FantasyPros final: 2.21 ± 1.10 (n=42; our miss 5.94 vs FP 6.12)
- QB opportunities: actual − projected 1.87 ± 1.19; miss from volume 3.29 vs per-play 6.10 pts
- RB opportunities: actual − projected 0.85 ± 0.52; miss from volume 3.44 vs per-play 3.54 pts
- WR opportunities: actual − projected 0.85 ± 0.34; miss from volume 4.61 vs per-play 4.55 pts
- TE opportunities: actual − projected 0.33 ± 0.37; miss from volume 3.89 vs per-play 3.82 pts
- calibration: actual rises 0.90 per projected point (± 0.08; 1.00 = calibrated)

## Leans the improvement loop will test

- none yet: not enough evidence (needs several graded weeks)

## Recent improvement-loop decisions

- 2026-10-20 rejected: k_dst 10 → 8: +0.0004 ± 0.0006 (z 0.73)
- 2026-10-20 rejected: k_dst 10 → 12: -0.0003 ± 0.0005 (z -0.52)
- 2026-10-20 rejected: K_int 300 → 240: -0.0002 ± 0.0001 (z -1.43)
- 2026-10-20 rejected: K_int 300 → 375: +0.0002 ± 0.0001 (z 1.51)
- 2026-10-20 rejected: K_fl 250 → 200: +0.0000 ± 0.0001 (z 0.78)
- 2026-10-20 rejected: K_fl 250 → 312: -0.0000 ± 0.0001 (z -0.75)
- 2026-10-13 promoted: rookie_prior 0 → 0.25: -0.0095 ± 0.0028 (z -3.44)
- 2026-10-10 promoted: damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25: -0.0091 ± 0.0017 (z -5.52)

## Biggest misses, 2026 week 6

| Player | Ours | Hindsight | FP final | Actual | Opps proj → actual | Notes |
|---|---|---|---|---|---|---|
| Germie Bernard (WR PIT) | 7.0 | 6.8 | 10.6 | 25.7 | 4.9 → 12 | teammate out: role up 1+ pt, rookie (no NFL history) |
| Tre Tucker (WR LV) | 9.1 | 9.2 | 10.6 | 26.7 | 5.7 → 7 |  |
| Jaylin Noel (WR HOU) | 4.8 | 5.2 | 7.0 | 20.7 | 3.2 → 4 |  |
| Kyle Pitts (TE ATL) | 7.7 | 7.7 | 8.1 | 23.0 | 4.2 → 7 |  |
| Tyrone Tracy Jr. (RB NYG) | 3.2 | 3.5 | 4.5 | 18.5 | 4.0 → 9 |  |
| Bijan Robinson (RB ATL) | 21.5 | 21.5 | 23.2 | 7.3 | 22.8 → 11 |  |
| Bhayshul Tuten (RB JAX) | 10.8 | 10.8 | 12.2 | 24.7 | 15.9 → 16 |  |
| Malik Nabers (WR NYG) | 14.7 | 16.1 | 17.1 | 28.5 | 8.7 → 15 |  |
| Jahan Dotson (WR ATL) | 4.9 | 4.9 | 6.6 | 17.7 | 3.3 → 5 |  |
| Christian McCaffrey (RB SF) | 18.3 | 18.3 | 20.5 | 30.7 | 19.2 → 26 | teammate out: role up 1+ pt, veteran (RB 28+, WR/TE 30+, QB 35+) |
| Tyler Huntley (QB BAL) | 1.0 | 12.2 | 14.4 | 13.4 | 2.4 → 31 | backup QB (depth 2+) |
| Puka Nacua (WR LA) | 25.9 | 26.0 | 24.0 | 14.0 | 13.2 → 7 | teammate out: role up 1+ pt |
| Derrick Henry (RB BAL) | 16.9 | 17.1 | 17.7 | 5.0 | 23.2 → 18 | veteran (RB 28+, WR/TE 30+, QB 35+) |
| Roschon Johnson (RB CHI) | 2.7 | 3.0 | 7.3 | 14.5 | 3.6 → 15 |  |
| Cam Skattebo (RB NYG) | 11.2 | 11.6 | 13.2 | 0.0 | 14.8 → 0 |  |
