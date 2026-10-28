# Fantasy Trader — projection scorecard

Updated 2026-10-28T15:26:13Z.
Model parameters: version 3; 58 changes tested, 2 adopted, 0 reverted.

## Where we stand

- Model goal (vs FantasyPros Tuesday, same information): 3 of 6 weeks; miss lead 2.6% vs 3.0% target — not met yet
- Product goal (our page right before kickoff vs FantasyPros final, all the week's news): 3 of 6 weeks; miss lead 2.3% vs 3.0% target (significant) — not met yet
- vs FantasyPros Tuesday: average miss 5.63 vs 5.79 (-0.15 ± 0.09, n=482) → even (not significant); start/sit 57.2% vs 54.9% (+2.3 ± 0.9) → ahead
- vs FantasyPros final, our page right before kickoff: average miss 5.56 vs 5.69 (-0.13 ± 0.06, n=496) → ahead; start/sit 56.6% vs 56.5% (+0.1 ± 0.8) → even (not significant)
- vs FantasyPros final, our model with hindsight availability: average miss 5.56 vs 5.69 (-0.13 ± 0.07, n=496) → ahead; start/sit 56.4% vs 56.5% (-0.1 ± 1.1) → even (not significant)
- News after Tuesday: knowing who played would have changed our miss by -0.07 pts (5.56 vs 5.63)

## Cumulative (fantasy-relevant players who played, PPR)

| Source | n | Avg miss | Actual − proj | RMSE | r | Rank corr | Start/sit % |
|---|---|---|---|---|---|---|---|
| Our page (Tuesday) | 497 | 5.63 | 1.00 | 7.04 | 0.52 | 0.438 | 56.5 |
| Our page right before kickoff | 497 | 5.56 | 0.77 | 6.92 | 0.54 | 0.451 | 56.6 |
| Our usage model (no expert blend) | 497 | 5.67 | 0.94 | 7.08 | 0.52 | 0.432 | 56.5 |
| Our page with hindsight availability | 497 | 5.56 | 0.69 | 6.90 | 0.54 | 0.434 | 56.4 |
| FantasyPros, Tuesday | 482 | 5.79 | -0.06 | 7.09 | 0.50 | 0.438 | 54.9 |
| FantasyPros, final | 496 | 5.69 | -0.13 | 6.89 | 0.53 | 0.446 | 56.5 |

## Kickers and defenses (ESPN standard scoring; not in the numbers above)

| Position | Weeks | n | Our miss | FP Tue | FP final | Rank corr ours vs FP final | Start/sit ours vs FP final |
|---|---|---|---|---|---|---|---|
| K | 1 | 16 | 3.19 | 3.33 | 3.18 | 0.431 vs 0.160 | 63.4 vs 57.3 |
| D/ST | 1 | 17 | 4.40 | 5.45 | 5.48 | 0.295 vs 0.063 | 61.0 vs 52.5 |

## By week

| Season-week | Status | Ours | Hindsight | FP Tue | FP final | Start/sit ours vs FP final |
|---|---|---|---|---|---|---|
| 2026-5 | final | 6.01 | 6.03 | 6.30 | 6.09 | 56.2 vs 56.1 |
| 2026-6 | final | 5.27 | 5.22 | 5.60 | 5.46 | 56.5 vs 56.7 |
| 2026-7 | final | 5.61 | 5.44 | 5.48 | 5.52 | 56.7 vs 56.7 |

## Rest of season (what trade values run on)

| Weeks ahead | n | Avg miss | Actual − proj | Rank corr ours | Rank corr FP ROS rank |
|---|---|---|---|---|---|
| 0 | 450 | 5.69 | 0.72 | 0.435 | 0.368 |
| 1 | 271 | 5.39 | 1.12 | 0.403 | 0.401 |
| 2 | 132 | 5.85 | 1.25 | 0.369 | 0.390 |

Rest-of-season average so far (91 player-freezes with 3+ games): miss 3.86, rank corr ours 0.574 vs FantasyPros 0.413

## Expert weights (rebuilt from the frozen parts, 497 players)

Current 0.20 / 0.25: miss 5.631. Best 0.30 / 0.70: 5.615 (-0.017 ± 0.027).

## Diagnostics (hindsight; actual − projection, + = projected too low)

- QB: 0.72 ± 0.80 (n=77; our miss 5.75 vs FP 5.89)
- RB: 1.19 ± 0.54 (n=152; our miss 5.44 vs FP 5.37)
- WR: 0.50 ± 0.45 (n=194; our miss 5.53 vs FP 5.85)
- TE: 0.13 ± 0.75 (n=74; our miss 5.65 vs FP 5.72)
- K: 0.01 ± 1.01 (n=16; our miss 3.01 vs FP 3.18)
- DST: -4.02 ± 0.88 (n=17; our miss 4.40 vs FP 5.48)
- first game back: 1.82 ± 1.28 (n=24; our miss 4.77 vs FP 5.44)
- teammate out: role up 1+ pt: 0.47 ± 0.54 (n=159; our miss 5.78 vs FP 6.01)
- injury tag (Q/limited/DNP): 0.49 ± 0.75 (n=64; our miss 5.15 vs FP 5.42)
- 0-1 games this season: 1.90 ± 2.04 (n=9; our miss 5.25 vs FP 4.52)
- rookie (no NFL history): 0.62 ± 1.11 (n=39; our miss 5.42 vs FP 5.83)
- backup QB (depth 2+): 0.10 ± 2.31 (n=5; our miss 3.27 vs FP 4.84)
- veteran (RB 28+, WR/TE 30+, QB 35+): 0.79 ± 0.66 (n=96; our miss 4.69 vs FP 4.92)
- team expected 8%+ above its usual score: 1.06 ± 0.52 (n=171; our miss 5.66 vs FP 5.92)
- team expected 8%+ below its usual score: -0.18 ± 0.78 (n=102; our miss 4.92 vs FP 4.92)
- favored by 6+: -0.18 ± 0.69 (n=69; our miss 4.91 vs FP 5.32)
- underdog by 6+: 0.63 ± 0.92 (n=61; our miss 4.84 vs FP 4.62)
- we're 3+ pts above FantasyPros final: -5.28 ± 0.89 (n=8; our miss 6.22 vs FP 4.67)
- we're 3+ pts below FantasyPros final: 1.95 ± 0.85 (n=64; our miss 5.51 vs FP 5.69)
- QB opportunities: actual − projected 0.86 ± 1.00; miss from volume 3.35 vs per-play 5.88 pts
- RB opportunities: actual − projected 1.27 ± 0.45; miss from volume 3.64 vs per-play 3.83 pts
- WR opportunities: actual − projected 0.50 ± 0.25; miss from volume 4.07 vs per-play 4.33 pts
- TE opportunities: actual − projected 0.24 ± 0.31; miss from volume 4.06 vs per-play 3.61 pts
- calibration: actual rises 0.88 per projected point (± 0.06; 1.00 = calibrated)

## Leans the improvement loop will test

- **RB opportunities**: actual − projected carries+targets +1.27 (±0.45) — parameters: team_prior, decay, damp, prior_games

## Recent improvement-loop decisions

- 2026-10-20 rejected: k_dst 10 → 8: +0.0004 ± 0.0006 (z 0.73)
- 2026-10-20 rejected: k_dst 10 → 12: -0.0003 ± 0.0005 (z -0.52)
- 2026-10-20 rejected: K_int 300 → 240: -0.0002 ± 0.0001 (z -1.43)
- 2026-10-20 rejected: K_int 300 → 375: +0.0002 ± 0.0001 (z 1.51)
- 2026-10-20 rejected: K_fl 250 → 200: +0.0000 ± 0.0001 (z 0.78)
- 2026-10-20 rejected: K_fl 250 → 312: -0.0000 ± 0.0001 (z -0.75)
- 2026-10-13 promoted: rookie_prior 0 → 0.25: -0.0095 ± 0.0028 (z -3.44)
- 2026-10-10 promoted: damp 0.3 → 0.35, env_scale 1 → 1.1, w1 0.8 → 0.7, low_target 2 → 2.25: -0.0091 ± 0.0017 (z -5.52)

## Biggest misses, 2026 week 7

| Player | Ours | Hindsight | FP final | Actual | Opps proj → actual | Notes |
|---|---|---|---|---|---|---|
| Tony Pollard (RB TEN) | 9.3 | 11.0 | 11.7 | 36.5 | 14.8 → 28 | veteran (RB 28+, WR/TE 30+, QB 35+) |
| Omar Cooper Jr. (WR NYJ) | 7.7 | 8.1 | 9.0 | 22.5 | 4.7 → 5 | rookie (no NFL history) |
| KC Concepcion (WR CLE) | 8.8 | 8.8 | 9.8 | 23.2 | 6.1 → 13 | rookie (no NFL history) |
| Caleb Douglas (WR MIA) | 6.8 | 6.6 | 6.8 | 21.0 | 4.6 → 3 | first game back, teammate out: role up 1+ pt, injury tag (Q/limited/DNP), rookie (no NFL history) |
| Jameson Williams (WR DET) | 12.1 | 11.9 | 11.2 | 26.1 | 6.1 → 9 |  |
| Tyler Huntley (QB BAL) | 1.2 | 14.5 | 13.1 | 15.1 | 2.5 → 34 | backup QB (depth 2+) |
| Makai Lemon (WR PHI) | 6.3 | 8.1 | 8.6 | 19.7 | 4.0 → 8 | rookie (no NFL history) |
| Braelon Allen (RB NYJ) | 6.1 | 8.7 | 13.5 | 19.4 | 8.2 → 24 |  |
| Bryce Young (QB CAR) | 18.4 | 18.5 | 18.4 | 5.4 | 36.9 → 27 |  |
| Quinshon Judkins (RB CLE) | 10.5 | 11.0 | 10.8 | 23.4 | 15.3 → 18 | first game back, injury tag (Q/limited/DNP) |
| Malik Willis (QB MIA) | 13.4 | 13.4 | 13.8 | 26.0 | 28.0 → 21 |  |
| Tee Higgins (WR CIN) | 14.3 | 14.1 | 13.7 | 26.8 | 7.6 → 7 | teammate out: role up 1+ pt |
| Tre Tucker (WR LV) | 9.5 | 9.8 | 10.3 | 21.3 | 5.8 → 12 |  |
| Luther Burden III (WR CHI) | 11.9 | 12.4 | 13.4 | 23.7 | 6.9 → 5 |  |
| Sam LaPorta (TE DET) | 14.5 | 14.2 | 13.0 | 2.8 | 7.1 → 2 |  |
