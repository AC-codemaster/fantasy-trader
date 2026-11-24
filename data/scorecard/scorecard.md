# Fantasy Trader — projection scorecard

Updated 2026-11-24T12:47:53Z.
Frozen, waiting for games: 2026 week 12 (509 players, frozen 2026-11-24T12:47:50Z).
Model parameters: version 3; 81 changes tested, 3 adopted, 0 reverted.

## Where we stand

- Model goal (vs FantasyPros Tuesday, same information): 4 of 6 weeks; miss lead 3.1% vs 3.0% target (significant) — not met yet
- Product goal (our page right before kickoff vs FantasyPros final, all the week's news): 4 of 6 weeks; miss lead 2.4% vs 3.0% target (significant) — not met yet
- vs FantasyPros Tuesday: average miss 5.44 vs 5.62 (-0.18 ± 0.08, n=642) → ahead; start/sit 56.6% vs 55.4% (+1.2 ± 1.0) → even (not significant)
- vs FantasyPros final, our page right before kickoff: average miss 5.40 vs 5.54 (-0.13 ± 0.06, n=658) → ahead; start/sit 56.0% vs 56.7% (-0.8 ± 0.8) → even (not significant)
- vs FantasyPros final, our model with hindsight availability: average miss 5.39 vs 5.54 (-0.15 ± 0.06, n=658) → ahead; start/sit 56.4% vs 56.7% (-0.4 ± 0.9) → even (not significant)
- News after Tuesday: knowing who played would have changed our miss by -0.05 pts (5.39 vs 5.44)

## Cumulative (fantasy-relevant players who played, PPR)

| Source | n | Avg miss | Actual − proj | RMSE | r | Rank corr | Start/sit % |
|---|---|---|---|---|---|---|---|
| Our page (Tuesday) | 659 | 5.44 | 0.92 | 6.87 | 0.53 | 0.443 | 56.1 |
| Our page right before kickoff | 659 | 5.41 | 0.70 | 6.78 | 0.55 | 0.451 | 56.0 |
| Our usage model (no expert blend) | 659 | 5.50 | 0.87 | 6.94 | 0.52 | 0.430 | 55.8 |
| Our page with hindsight availability | 659 | 5.39 | 0.58 | 6.75 | 0.55 | 0.442 | 56.4 |
| FantasyPros, Tuesday | 642 | 5.62 | -0.29 | 6.91 | 0.52 | 0.448 | 55.4 |
| FantasyPros, final | 658 | 5.54 | -0.35 | 6.71 | 0.55 | 0.459 | 56.7 |

## Kickers and defenses (ESPN standard scoring; not in the numbers above)

| Position | Weeks | n | Our miss | FP Tue | FP final | Rank corr ours vs FP final | Start/sit ours vs FP final |
|---|---|---|---|---|---|---|---|
| K | 2 | 32 | 3.19 | 3.21 | 3.10 | 0.314 vs 0.134 | 60.5 vs 55.1 |
| D/ST | 2 | 32 | 4.07 | 4.64 | 4.83 | 0.410 vs 0.184 | 65.4 vs 56.7 |

## By week

| Season-week | Status | Ours | Hindsight | FP Tue | FP final | Start/sit ours vs FP final |
|---|---|---|---|---|---|---|
| 2026-5 | final | 6.01 | 6.03 | 6.30 | 6.09 | 56.2 vs 56.1 |
| 2026-6 | final | 5.27 | 5.22 | 5.60 | 5.46 | 56.5 vs 56.7 |
| 2026-7 | final | 5.61 | 5.44 | 5.48 | 5.52 | 56.7 vs 56.7 |
| 2026-11 | final | 4.86 | 4.88 | 5.12 | 5.06 | 54.9 vs 57.4 |

## Rest of season (what trade values run on)

| Weeks ahead | n | Avg miss | Actual − proj | Rank corr ours | Rank corr FP ROS rank |
|---|---|---|---|---|---|
| 0 | 557 | 5.58 | 0.58 | 0.440 | 0.384 |
| 1 | 392 | 5.88 | 1.09 | 0.369 | 0.388 |
| 2 | 395 | 5.92 | 1.06 | 0.345 | 0.370 |
| 3 | 394 | 6.15 | 1.16 | 0.356 | 0.389 |
| 4 | 383 | 5.53 | 1.01 | 0.431 | 0.425 |
| 5 | 244 | 5.82 | 1.12 | 0.398 | 0.437 |
| 6 | 125 | 5.03 | 0.42 | 0.414 | 0.466 |

Rest-of-season average so far (454 player-freezes with 3+ games): miss 3.30, rank corr ours 0.593 vs FantasyPros 0.637

## Expert weights (rebuilt from the frozen parts, 659 players)

Current 0.20 / 0.25: miss 5.442. Best 0.50 / 0.55: 5.419 (-0.023 ± 0.029).

## Diagnostics (hindsight; actual − projection, + = projected too low)

- QB: 0.63 ± 0.69 (n=102; our miss 5.67 vs FP 5.77)
- RB: 1.16 ± 0.46 (n=201; our miss 5.34 vs FP 5.29)  ← flag
- WR: 0.38 ± 0.38 (n=256; our miss 5.39 vs FP 5.73)
- TE: -0.10 ± 0.62 (n=100; our miss 5.20 vs FP 5.29)
- K: 0.04 ± 0.69 (n=32; our miss 3.10 vs FP 3.10)
- DST: -2.29 ± 0.77 (n=32; our miss 4.07 vs FP 4.83)
- first game back: 2.64 ± 1.18 (n=32; our miss 5.40 vs FP 5.59)
- teammate out: role up 1+ pt: 0.35 ± 0.48 (n=194; our miss 5.61 vs FP 5.93)
- injury tag (Q/limited/DNP): 0.77 ± 0.71 (n=74; our miss 5.10 vs FP 5.32)
- 0-1 games this season: 0.49 ± 1.72 (n=12; our miss 4.87 vs FP 4.96)
- rookie (no NFL history): 0.83 ± 1.03 (n=56; our miss 5.81 vs FP 6.00)
- backup QB (depth 2+): 0.10 ± 2.31 (n=5; our miss 3.27 vs FP 4.84)
- veteran (RB 28+, WR/TE 30+, QB 35+): 0.92 ± 0.56 (n=127; our miss 4.76 vs FP 4.92)
- team expected 8%+ above its usual score: 0.97 ± 0.48 (n=232; our miss 5.62 vs FP 5.78)
- team expected 8%+ below its usual score: -0.31 ± 0.64 (n=145; our miss 4.91 vs FP 5.06)
- favored by 6+: 0.25 ± 0.64 (n=130; our miss 5.15 vs FP 5.35)
- underdog by 6+: 0.04 ± 0.66 (n=112; our miss 4.81 vs FP 4.86)
- we're 3+ pts above FantasyPros final: -4.77 ± 0.92 (n=9; our miss 5.61 vs FP 4.16)
- we're 3+ pts below FantasyPros final: 1.94 ± 0.82 (n=86; our miss 5.78 vs FP 5.89)
- QB opportunities: actual − projected 0.93 ± 0.86; miss from volume 3.45 vs per-play 6.13 pts
- RB opportunities: actual − projected 1.22 ± 0.38; miss from volume 3.54 vs per-play 3.68 pts
- WR opportunities: actual − projected 0.48 ± 0.21; miss from volume 4.19 vs per-play 4.23 pts
- TE opportunities: actual − projected 0.01 ± 0.27; miss from volume 3.95 vs per-play 3.56 pts
- calibration: actual rises 0.90 per projected point (± 0.05; 1.00 = calibrated)

## Leans the improvement loop will test

- **RB level**: actual − projection +1.16 pts/player (±0.46, n=201) — parameters: team_prior, prior_games, K_ypc, K_rtd
- **RB opportunities**: actual − projected carries+targets +1.22 (±0.38) — parameters: team_prior, decay, damp, prior_games

## Recent improvement-loop decisions

- 2026-11-24 promoted: expertWeight 0.2 → 0.25, weeklyExpert 0.25 → 0.3: -0.0090 (z -2.03)
- 2026-11-24 rejected: k_kvol 40 → 32: +0.0002 ± 0.0005 (z 0.39)
- 2026-11-24 rejected: k_kvol 40 → 50: -0.0001 ± 0.0005 (z -0.11)
- 2026-11-24 rejected: K_two 400 → 320: +0.0001 ± 0.0000 (z 1.59)
- 2026-11-24 rejected: K_two 400 → 500: -0.0001 ± 0.0000 (z -1.6)
- 2026-11-24 rejected: K_rtd 150 → 120: +0.0001 ± 0.0003 (z 0.37)
- 2026-11-24 rejected: K_rtd 150 → 188: +0.0000 ± 0.0003 (z 0.08)
- 2026-11-24 rejected: K_ypc 100 → 80: -0.0000 ± 0.0002 (z -0.02)

## Biggest misses, 2026 week 11

| Player | Ours | Hindsight | FP final | Actual | Opps proj → actual | Notes |
|---|---|---|---|---|---|---|
| Jonah Coleman (RB DEN) | 11.6 | 10.8 | 18.4 | 34.9 | 14.0 → 29 | teammate out: role up 1+ pt, rookie (no NFL history) |
| Ashton Jeanty (RB LV) | 11.4 | 12.6 | 11.7 | 27.9 | 16.0 → 19 |  |
| Travis Kelce (TE KC) | 9.0 | 9.3 | 12.2 | 25.4 | 4.1 → 7 | veteran (RB 28+, WR/TE 30+, QB 35+) |
| Emmett Johnson (RB KC) | 8.1 | 9.8 | 21.1 | 24.3 | 6.6 → 27 | rookie (no NFL history) |
| Ladd McConkey (WR LAC) | 5.5 | 5.8 | 7.8 | 20.7 | 2.5 → 8 | first game back, injury tag (Q/limited/DNP) |
| Dak Prescott (QB DAL) | 20.8 | 20.9 | 23.0 | 35.9 | 37.9 → 33 |  |
| Mike Evans (WR SF) | 8.2 | 7.8 | 10.4 | 22.9 | 4.4 → 7 | first game back, teammate out: role up 1+ pt, injury tag (Q/limited/DNP), veteran (RB 28+, WR/TE 30+, QB 35+) |
| Antonio Williams (WR WAS) | 7.8 | 7.5 | 9.4 | 21.2 | 4.6 → 11 | teammate out: role up 1+ pt, rookie (no NFL history) |
| Fernando Mendoza (QB LV) | 10.1 | 9.1 | 12.4 | 22.9 | 32.4 → 37 | rookie (no NFL history) |
| DJ Moore (WR BUF) | 11.2 | 12.2 | 13.6 | 23.1 | 6.1 → 10 |  |
| Ja'Marr Chase (WR CIN) | 19.8 | 21.1 | 23.3 | 8.1 | 9.6 → 9 | teammate out: role up 1+ pt |
| Justice Hill (RB BAL) | 6.3 | 6.4 | 7.8 | 17.6 | 7.0 → 11 | veteran (RB 28+, WR/TE 30+, QB 35+) |
| Chuba Hubbard (RB CAR) | 14.7 | 16.9 | 18.7 | 26.0 | 16.4 → 27 |  |
| Luther Burden III (WR CHI) | 13.8 | 13.8 | 15.0 | 3.3 | 7.2 → 4 | teammate out: role up 1+ pt |
| CeeDee Lamb (WR DAL) | 19.8 | 21.1 | 23.2 | 30.2 | 10.8 → 12 |  |
