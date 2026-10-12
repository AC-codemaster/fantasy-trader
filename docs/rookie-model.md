# Rookie-prior model

Built Oct 12, 2026 (branch `rookie-offseason`). Code: `rookie/rookie_model.py` (data, features, fit),
`rookie/college.py` (college production), `rookie/evaluate_rookies.py` (every table below). Data:
`data/rookie/` (`players.csv` features and outcomes, `predictions.csv` per-class predictions, `model.json`
latest fit, `eval/` tables). Refreshed every May by the scheduled task in `runbooks/rookie-draft.md`.

## What it is for

The projection model learns a player's share of his team's carries, targets and pass attempts from games
played, with last season's share as a prior. Drafted rookies had no prior at all: until they had played a few
games, their share came only from those few games (QBs had the depth-chart prior), and their efficiency
shrank toward the low-volume rate. The rookie model gives every drafted QB/RB/WR/TE a prior from what is
known right after the draft: share of team carries and targets in a game he plays (the same Luce terms as
`build_db.py`), and per-opportunity efficiency.

It enters the projections through one new parameter, `rookie_prior` (0 = the old model exactly): shares count
like `rookie_prior × prior_games` games of data, efficiency gets `rookie_prior × (150 QB attempts, 60 RB
carries + 20 targets, 40 WR targets, 30 TE targets)` pseudo-opportunities at the predicted rates. QB pass
attempts keep the depth-chart prior. It is live only if the Tuesday improvement loop's gate adopts it.

## In plain language

- **Draft slot is almost everything.** College production (market share, dominator rating, breakout age),
  combine numbers, age and landing spot (vacated carries/targets/attempts, team volume, same-position picks
  ahead) were all tried. None beat draft slot alone reliably: each class is predicted with the feature set
  that had the lowest miss on all earlier classes, and that was the draft-slot-only set every year
  (2017–2026). The richer sets come close (the full set was slightly better on 2019–25, 2.99 vs 3.02, but
  worse on 2015–18, 3.13 vs 3.04), so the selection keeps re-checking them every May.
- **Past classes (2019–2025, each predicted from earlier classes only):** rookie PPR per game missed by
  3.02 on average (rank correlation 0.54), versus 2.96 (0.56) for a straight draft-pick curve fitted to points.
  The model is built from shares × team volume × efficiency, which the builder can use; that costs a little
  against a curve fitted to points directly, but the shares themselves are as good as a pick-only fit.
- **Against the current model:** once a rookie has played a few games, the current model already beats a
  draft-day prior by a lot (weeks 3–8: 3.64 vs 4.77 average miss for every rookie who played). Adding the
  prior on top makes the miss slightly worse on *all* rookie player-weeks (3.71 at 0.25, 3.86 at 1): it lifts
  barely-used rookies off zero and pulls breakout stars down. On the player-games the improvement loop scores
  (projection ≥ 3 points) it helps instead: the gate's dry run for `rookie_prior` 0 → 0.25 gives **−0.0093 ±
  0.0028 pts (z −3.31), passes** (2024 −0.009, 2025 −0.004, 2026 −0.039; WR −0.012 z −2.8, TE −0.011, RB −0.008,
  QB 0.000). 0.5 also passes (−0.0107, z −2.81); 1.0 doesn't (−0.0110, z −2.17). Not adopted here: the Tuesday
  loop tests it first (it's marked new) and decides.
- **Year 2:** the rookie prior still helps once the rookie season is known: second-season PPR/G miss 2.85 →
  2.73 (rank correlation 0.73 → 0.75), most for TEs and QBs; the fitted weight on the prior is about half the
  weight on the rookie season. (Not used by the model yet: the builder's prior for second-year players is
  their rookie season.)
- **Mock draft 1 (no draft slot):** college production, age and combine alone put a player in the right round
  27% of the time and within one round 58% (rank correlation with the actual pick 0.48). Biggest misses: productive
  college QBs who went on day 3 (Pratt, Ewers, Duggan, Purdy, McCord, Howard predicted round 1) and
  receivers/backs from talent-dense programs, whose market shares look small (Waddle, Najee Harris, Egbuka
  predicted round 6).
- **Mock draft 2 (fantasy rookie draft):** ranking each class by projected rookie-season points matches draft
  order (rank correlation with actual points 0.60 vs 0.59; 36 vs 37 of the actual top-12 rookies, 22 vs 22
  top-24 RB/WR or top-12 QB/TE finishes among each list's top 12). Biases by round: first-round WRs
  (+1.2 PPR/G, 25 players) and TEs (+3.9, 5) did better than predicted, second-round RBs too (+1.4, 9);
  third-round RBs (−1.3, 12) and QBs (−3.3, 6) did worse. Where the model disagrees with draft order, it ranks
  day-3 RBs higher (Kyren Williams, Tyler Badie, Kevin Harris, Ty Chandler...) — mostly misses: the RB
  position's higher points baseline outweighs their draft slot. The model never predicts a hit (it projects
  averages, which stay below the top-24 line); hit rates are by round below.

## Data sources

- nflverse releases (GitHub): `draft_picks` (round, pick, team, college, age; 2012–2026 used), `combine`
  (height, weight, 40, vertical; 73% of drafted players have a 40), `players` (birth dates, gsis ids, undrafted
  rookies), weekly player stats 2011–2026 (outcomes, team volume, vacated opportunity), weekly rosters
  (week-1 rosters: who left).
- College: sportsdataverse `cfbfastR-data` play-level player stats (`player_stats/csv`, raw.githubusercontent),
  seasons 2014–2025, FBS and some FCS, aggregated per player-season with team totals. Matched to 94% of drafted
  players from 2015 on (classes 2012–14 have no college data). Targets aren't usable there (recorded on ~20% of
  incompletions), so receiving market share uses yards and TDs. Some completions have passer and receiver
  swapped; the passer is the name with more incompletions/interceptions thrown for that team.
- Didn't work: the sportsdataverse release assets and other GitHub repos' API (403 from this environment);
  the committed tree via raw.githubusercontent and `git clone` worked. No Pro Football Focus, recruiting
  rankings or ADP history (not on GitHub).

## Method

- Targets (rookie season, regular season, games with a stat): share of team RB/WR/TE carries and targets and
  of team QB pass attempts in the games he played; efficiency per carry/target/attempt; PPR per game.
- Shares: ridge regression per position (λ = 4 on standardized features, chosen on classes 2015–18), every
  rookie who played counting alike; log(pick) may only lower the share as the pick gets later.
- Efficiency: each rate on log(pick), every rookie's opportunities capped at 30 (each counts about alike),
  slope shrunk toward zero.
- Points: shares × last season's team volume per game × efficiency.
- Time-respecting: class Y is predicted by models fitted on classes before Y only (`trained_thru` in
  `predictions.csv`); the feature set for class Y is chosen on earlier classes only. The backtest uses the
  same file, so a 2024 replay never sees the 2024 rookies' outcomes.

## Tables (generated by `rookie/evaluate_rookies.py`, Oct 12, 2026)

## Holdout: rookie PPR per game, classes 2019–2025 (each fitted on earlier classes only)

| pos | n | actual PPR/G | MAE model | MAE pick curve | rank corr model | rank corr pick curve | bias model |
|---|---|---|---|---|---|---|---|
| QB | 56 | 9.85 | 4.42 | 4.35 | 0.49 | 0.51 | -0.48 |
| RB | 132 | 5.87 | 3.22 | 3.09 | 0.51 | 0.54 | -0.11 |
| WR | 198 | 5.73 | 2.80 | 2.78 | 0.58 | 0.58 | 0.39 |
| TE | 86 | 4.44 | 2.32 | 2.24 | 0.32 | 0.40 | 0.39 |
| All | 472 | 6.02 | 3.02 | 2.96 | 0.54 | 0.56 | 0.15 |

By class:

| class | n | MAE model | MAE pick curve | rank corr model | rank corr pick curve |
|---|---|---|---|---|---|
| 2019 | 64 | 3.25 | 3.10 | 0.36 | 0.46 |
| 2020 | 66 | 2.75 | 2.52 | 0.73 | 0.77 |
| 2021 | 68 | 3.12 | 2.90 | 0.58 | 0.61 |
| 2022 | 70 | 3.00 | 2.97 | 0.50 | 0.48 |
| 2023 | 68 | 3.02 | 3.02 | 0.52 | 0.57 |
| 2024 | 66 | 3.23 | 3.35 | 0.52 | 0.53 |
| 2025 | 70 | 2.81 | 2.84 | 0.56 | 0.54 |

Competing feature sets (out of sample; the model picks, for each class, the set with the lowest miss on all earlier classes):

| features | MAE 2015–18 | MAE 2019–25 | QB | RB | WR | TE | rank corr 2019–25 |
|---|---|---|---|---|---|---|---|
| pick | 3.04 | 3.02 | 4.42 | 3.22 | 2.80 | 2.32 | 0.54 |
| pick+age | 3.08 | 3.03 | 4.50 | 3.24 | 2.78 | 2.30 | 0.54 |
| pick+landing | 3.14 | 2.99 | 4.49 | 3.15 | 2.80 | 2.22 | 0.56 |
| pick+college | 3.15 | 3.06 | 4.32 | 3.35 | 2.84 | 2.28 | 0.53 |
| pick+combine | 3.10 | 3.01 | 4.51 | 3.25 | 2.75 | 2.27 | 0.54 |
| full | 3.13 | 2.99 | 4.33 | 3.21 | 2.81 | 2.17 | 0.55 |

The usage shares themselves (share of team carries / targets / QB attempts in games played):

| pos | share | n | actual mean | MAE model | MAE pick only | rank corr model | rank corr pick only |
|---|---|---|---|---|---|---|---|
| QB | pass attempts | 56 | 0.696 | 0.249 | 0.255 | 0.369 | 0.368 |
| RB | carries | 132 | 0.267 | 0.138 | 0.137 | 0.568 | 0.569 |
| RB | targets | 132 | 0.046 | 0.027 | 0.027 | 0.480 | 0.480 |
| WR | targets | 198 | 0.103 | 0.043 | 0.043 | 0.622 | 0.622 |
| TE | targets | 86 | 0.081 | 0.036 | 0.035 | 0.456 | 0.452 |

## Rookies in the current model (backtest replay, weeks 2024 wk 3–8, 2025 wk 3–8, 2026 wk 3–5, every rookie who played)

| pos | player-weeks | actual | MAE current model | MAE rookie model (static) | rank corr current | rank corr rookie | MAE with rookie_prior 0.25 | MAE with rookie_prior 0.5 | MAE with rookie_prior 1 |
|---|---|---|---|---|---|---|---|---|---|
| QB | 50 | 12.53 | 5.51 | 7.29 | 0.64 | 0.39 | 5.51 | 5.51 | 5.52 |
| RB | 187 | 6.00 | 4.00 | 5.18 | 0.65 | 0.36 | 4.05 | 4.12 | 4.23 |
| WR | 319 | 5.09 | 3.43 | 4.48 | 0.65 | 0.41 | 3.53 | 3.61 | 3.71 |
| TE | 147 | 4.72 | 2.99 | 4.01 | 0.67 | 0.30 | 3.04 | 3.08 | 3.16 |
| All | 703 | 5.78 | 3.64 | 4.77 | 0.69 | 0.42 | 3.71 | 3.77 | 3.86 |

## Year 2: second-season PPR/G (classes 2019–2024, played both seasons)

| pos | n | year-2 PPR/G | MAE rookie season only | MAE + rookie prior | MAE prior alone | rank corr rookie season | rank corr + prior | weight on prior (2024 fit) |
|---|---|---|---|---|---|---|---|---|
| QB | 39 | 12.37 | 3.88 | 3.64 | 4.38 | 0.60 | 0.62 | 0.33 |
| RB | 90 | 7.66 | 3.45 | 3.32 | 3.84 | 0.65 | 0.65 | 0.41 |
| WR | 149 | 7.10 | 2.52 | 2.50 | 3.37 | 0.76 | 0.77 | 0.36 |
| TE | 65 | 4.48 | 2.16 | 1.89 | 2.08 | 0.57 | 0.67 | 0.98 |
| All | 343 | 7.35 | 2.85 | 2.73 | 3.37 | 0.73 | 0.75 | 0.48 |

## Mock draft 1: NFL round from pre-draft information only (classes 2021–2025)

Each class is ordered by predicted pick and each round gets as many of these players as it actually took (a mock draft fills fixed slots). Confusion table (rows: actual round, columns: predicted round):

| actual round | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| 1 | 25 | 11 | 11 | 1 | 3 | 3 | 0 |
| 2 | 8 | 12 | 8 | 11 | 3 | 3 | 2 |
| 3 | 5 | 7 | 15 | 11 | 6 | 7 | 6 |
| 4 | 3 | 9 | 7 | 14 | 9 | 13 | 9 |
| 5 | 3 | 5 | 7 | 9 | 10 | 14 | 8 |
| 6 | 6 | 0 | 7 | 7 | 16 | 14 | 14 |
| 7 | 4 | 3 | 2 | 11 | 9 | 10 | 16 |

| class | n | exact round | within one round | rank corr (pick) | within one round, unordered |
|---|---|---|---|---|---|
| 2021 | 75 | 0.28 | 0.60 | 0.57 | 0.61 |
| 2022 | 79 | 0.24 | 0.57 | 0.47 | 0.59 |
| 2023 | 80 | 0.25 | 0.53 | 0.35 | 0.49 |
| 2024 | 77 | 0.32 | 0.68 | 0.61 | 0.66 |
| 2025 | 86 | 0.24 | 0.53 | 0.40 | 0.53 |
| 2021–25 | 397 | 0.27 | 0.58 | 0.48 | 0.58 |

| pos | n | exact round | within one round | rank corr (pick) | mean predicted − actual round |
|---|---|---|---|---|---|
| QB | 58 | 0.29 | 0.45 | 0.41 | -0.48 |
| RB | 104 | 0.24 | 0.56 | 0.37 | 0.09 |
| TE | 73 | 0.23 | 0.58 | 0.49 | 0.27 |
| WR | 162 | 0.29 | 0.64 | 0.61 | -0.01 |

Biggest misses:

| season | name | pos | college | actual round | predicted round | pick |
|---|---|---|---|---|---|---|
| 2024 | Michael Pratt | QB | Tulane | 7 | 1 | 245 |
| 2025 | Quinn Ewers | QB | Texas | 7 | 1 | 231 |
| 2023 | Max Duggan | QB | TCU | 7 | 1 | 239 |
| 2022 | Brock Purdy | QB | Iowa St. | 7 | 1 | 262 |
| 2025 | Will Howard | QB | Ohio St. | 6 | 1 | 185 |
| 2025 | Tyler Shough | QB | Louisville | 2 | 7 | 40 |
| 2021 | Jaylen Waddle | WR | Alabama | 1 | 6 | 6 |
| 2025 | Tommy Mellott | QB | Montana St. | 6 | 1 | 213 |
| 2025 | Kyle McCord | QB | Syracuse | 6 | 1 | 181 |
| 2021 | Najee Harris | RB | Alabama | 1 | 6 | 24 |
| 2023 | Zack Kuntz | TE | Old Dominion | 7 | 2 | 220 |
| 2025 | Emeka Egbuka | WR | Ohio St. | 1 | 6 | 19 |

## Mock draft 2: fantasy rookie draft (classes 2021–2025)

By actual NFL round:

| round | pos | drafted | played | predicted PPR/G | actual PPR/G | actual − predicted | hit rate | predicted hit rate |
|---|---|---|---|---|---|---|---|---|
| 1 | QB | 17 | 16 | 14.15 | 13.82 | -0.33 | 0.18 | 0.06 |
| 1 | RB | 6 | 5 | 14.85 | 15.56 | 0.72 | 0.67 | 0.50 |
| 1 | WR | 26 | 25 | 9.71 | 10.91 | 1.20 | 0.31 | 0.12 |
| 1 | TE | 5 | 5 | 7.44 | 11.33 | 3.89 | 1.00 | 0.20 |
| 1 | All | 54 | 51 | 11.38 | 12.32 | 0.94 | 0.37 | 0.15 |
| 2 | QB | 3 | 2 | 8.66 | 12.85 | 4.19 | 0.00 | 0.00 |
| 2 | RB | 9 | 9 | 9.02 | 10.46 | 1.44 | 0.44 | 0.00 |
| 2 | WR | 24 | 23 | 6.78 | 7.06 | 0.28 | 0.04 | 0.00 |
| 2 | TE | 11 | 11 | 5.33 | 5.61 | 0.27 | 0.09 | 0.00 |
| 2 | All | 47 | 45 | 6.96 | 7.64 | 0.68 | 0.13 | 0.00 |
| 3 | QB | 8 | 6 | 8.45 | 5.20 | -3.25 | 0.00 | 0.00 |
| 3 | RB | 12 | 12 | 7.07 | 5.72 | -1.34 | 0.08 | 0.00 |
| 3 | WR | 26 | 25 | 5.27 | 4.48 | -0.78 | 0.00 | 0.00 |
| 3 | TE | 11 | 10 | 4.20 | 4.17 | -0.04 | 0.09 | 0.00 |
| 3 | All | 57 | 53 | 5.83 | 4.79 | -1.05 | 0.04 | 0.00 |
| 4–7 | QB | 30 | 16 | 7.06 | 7.24 | 0.18 | 0.00 | 0.00 |
| 4–7 | RB | 77 | 69 | 4.52 | 4.47 | -0.05 | 0.01 | 0.00 |
| 4–7 | WR | 85 | 72 | 3.51 | 3.27 | -0.24 | 0.02 | 0.00 |
| 4–7 | TE | 46 | 36 | 3.20 | 3.82 | 0.63 | 0.00 | 0.00 |
| 4–7 | All | 238 | 193 | 4.11 | 4.13 | 0.03 | 0.01 | 0.00 |
| undrafted | QB | 36 | 5 |  | 6.03 |  | 0.00 |  |
| undrafted | RB | 107 | 45 |  | 2.48 |  | 0.00 |  |
| undrafted | WR | 222 | 54 |  | 1.86 |  | 0.00 |  |
| undrafted | TE | 113 | 31 |  | 1.15 |  | 0.00 |  |
| undrafted | All | 478 | 135 |  | 2.06 |  | 0.00 |  |

Ranking each class (projected rookie-season points vs draft order):

| class | n | rank corr model | rank corr draft order | model top 12 in actual top 12 | draft-order top 12 in actual top 12 | hits in model top 12 | hits in draft-order top 12 |
|---|---|---|---|---|---|---|---|
| 2021 | 75 | 0.62 | 0.58 | 7 | 7 | 5 | 4 |
| 2022 | 79 | 0.51 | 0.52 | 8 | 7 | 2 | 2 |
| 2023 | 80 | 0.65 | 0.65 | 5 | 6 | 5 | 6 |
| 2024 | 77 | 0.57 | 0.59 | 8 | 9 | 4 | 5 |
| 2025 | 85 | 0.62 | 0.60 | 8 | 8 | 6 | 5 |
| 2021–25 | 396 | 0.60 | 0.59 | 36 | 37 | 22 | 22 |

Biggest disagreements with draft order (model rank much higher, then much lower):

| season | name | pos | round | pick | model_rank | draft_rank | actual_rank | ppg | r1_ppg |
|---|---|---|---|---|---|---|---|---|---|
| 2023 | Lew Nichols | RB | 7 | 235 | 50 | 74 | 74 | 3.5 |  |
| 2022 | Kevin Harris | RB | 6 | 183 | 35 | 59 | 52 | 4.6 | 2.2 |
| 2022 | Ty Chandler | RB | 5 | 169 | 32 | 56 | 66 | 4.9 | 1.0 |
| 2022 | Kyren Williams | RB | 5 | 164 | 30 | 55 | 37 | 4.9 | 3.8 |
| 2023 | Deuce Vaughn | RB | 6 | 212 | 42 | 68 | 54 | 4.2 | 2.5 |
| 2023 | DeWayne McBride | RB | 7 | 222 | 45 | 72 | 74 | 3.6 |  |
| 2021 | Ian Book | QB | 4 | 133 | 71 | 43 | 57.5 | 5.5 | 2.0 |
| 2023 | Josh Whyle | TE | 5 | 147 | 71 | 46 | 49 | 2.6 | 2.7 |
| 2021 | Zach Davidson | TE | 5 | 168 | 74 | 50 | 69.5 | 2.7 |  |
| 2022 | Malik Willis | QB | 3 | 86 | 46 | 23 | 43 | 7.4 | 2.8 |
| 2024 | Theo Johnson | TE | 4 | 107 | 55 | 32 | 24 | 3.4 | 6.2 |
| 2021 | Brevin Jordan | TE | 5 | 147 | 68 | 46 | 27 | 3.2 | 7.0 |

Biases flagged (|actual − predicted| ≥ 1 PPR/G, 8+ players):

- round 1 WR: actual 10.9 vs predicted 9.7 PPR/G (underrated by 1.2, 25 players)
- round 2 RB: actual 10.5 vs predicted 9.0 PPR/G (underrated by 1.4, 9 players)
- round 3 RB: actual 5.7 vs predicted 7.1 PPR/G (overrated by 1.3, 12 players)
