# Start/sit: weekly points distributions (Oct 17, 2026)

The page's Start/Sit tab ranks lineups by the chance to win the week and shows every player's floor and
ceiling. Both come from a simulation of this week's games built on the projection's own expected stat line.
Reference implementation and fitting: `dist/sim.py`, `dist/fit_dist.py`, `dist/bt_frames.py`; the page runs the
same model (`engine/engine.js`: `simWeek`, `pPlay`, `startSit`, `needCalc`); fitted numbers in `params/dist.json`
(written into the engine's `DIST` line by `tools/ftlib.py`).

## The model (first principles)

For each team-game, a few thousand times:

- **Game**: a passing-environment shock both teams share (shootouts, weather: pass volume `pace_vol` and passing
  efficiency `pace_eff`) and a script shock that splits them (`script_pass`, `script_rush`: the leader runs more,
  the trailer throws more).
- **Team**: its own pass-volume (`sd_pass`), rush-volume (`sd_rush`) and efficiency (`sd_eff`) shocks;
  touchdowns move `td_el` times as much as yards.
- **Player**: a gamma role shock on his share of carries and targets (`share_rb/wr/te/qb`), re-split inside the
  team so the pool keeps its size (one back's big day is his teammate's small one); a chance `exit` he leaves
  early (plays a uniform fraction; teammates absorb the rest); a chance he doesn't play at all (`pplay`, below),
  handled the same way with fraction 0; his own efficiency shock (`eff[pos]`).
- **Plays**: carries and targets Poisson around those shares; catches binomial on targets; yards = sum of the
  plays (gamma with the per-play coefficient of variation `cv_rush`, `cv_qbrush`, `cv_catch_rb/wr/te`, measured
  directly from box scores given the plays that happened: E[(yards − plays·rate)²] = plays·s² + plays²·v);
  touchdowns, interceptions, fumbles and two-point plays Poisson at per-play rates.
- **QB**: his passing line *is* his receivers' receiving line: team passing yards and touchdowns move with what
  the pass catchers (plus a pseudo-receiver for unmodeled players, `other_*`) did against their expectation, and
  each QB gets his share of the team's simulated pass attempts.
- **Means**: the projection is tuned on average miss, so it sits between a player's median and his mean.
  `mean[pos]` multipliers (volume, yards per play, touchdowns, interceptions) calibrate the simulated mean to what
  happened in the backtest; `fit_dist.py means --write` refreshes them every Tuesday after the improvement loop.

## Fit and checks (backtest weeks 2024 wk 3–18, 2025 wk 3–18, 2026 wk 2–5; 13,701 player-games)

Holdout: fitted on 2024 only, tested on 2025–26 (players projected 3+ PPR points, n 4,541):

| | CRPS (PPR) | role-blind baseline | below P10 / P50 / P90 | P(score ≥ t) error |
|---|---|---|---|---|
| all | 3.654 | 3.700 | 9.4% / 52.4% / 90.2% | 1.7 pts |
| QB | 4.429 | 4.443 | | |
| RB | 3.708 | 3.760 | | |
| WR | 3.535 | 3.582 | | |
| TE | 3.289 | 3.344 | | |

Standard scoring (not fitted on): CRPS 3.011 vs baseline 3.042. Baseline = the actual scores of past players at
the same position with a projection within 10%, scaled. The P50 above 50% is the 2024 mean calibration carried
into 2025–26; the deployed fit pools every season.

Correlations of residuals, real vs simulated (all seasons): QB–WR1 same team .38 / .45, QB–WR2 .36 / .38,
QB–TE1 .31 / .37, QB–RB1 .07 / .07, WR1–WR2 .01 / .02, RB1–RB2 −.13 / −.14, opposing QBs .15 / .15, opposing RB1s
−.10 / −.05, opposing WR1s .18 / .05 (the one clear gap: something shared by opposing receivers beyond the
passing environment), opposing QB–WR1 .10 / .09.

Parity: the page's JavaScript simulation and `dist/sim.py` agree on the same inputs within simulation noise
(mean |difference| of player means 0.11 pts, of 90th percentiles 0.26; `tests/run_tests.py`).

## What does *not* predict a player's spread

At the same position and projection, players the simulation calls more volatile (by ±8%) were not more volatile
in real games, and usage-style features moved real spread by under 5% and not consistently across seasons: receivers
with a high catch rate about 4% steadier, deep threats (yards per target) about 4% wilder, touchdown-dependent
receivers about 4% wilder; for backs and tight ends nothing stable. Removing the simulation's own player-level spread
differences, or adding fitted style effects, barely moved the holdout CRPS (3.6526 and 3.6552 vs 3.6541), so the
page uses the simulation as is and doesn't label players "high floor" or "high ceiling". What moves a range is the
projection, the position (at the same projection backs had a slightly higher floor *and* ceiling than receivers),
the game and the chance he sits. In the user's framing, a high-volume back is not "capped": when you need 15,
compare the chances.

## Chance he plays (2023–25 injury reports, regulars with 35%+ of offensive snaps)

Questionable: 94% after a full final practice, 75% limited, 55% did not practice, 75% no practice report; odds
×0.57 if he missed his team's last game; quarterbacks ×0.30 (a QB listed Questionable sits far more often).
Doubtful 1.2%; on the practice report with no game status 97%; unlisted 99.5%; active after game-day inactives
99.5%. 587 Questionable, 83 Doubtful player-weeks.

## Lineups and decisions

- `startSit`: opponent = his highest-projection lineup, discounted by the chance each plays; your best lineup by
  local search over one-for-one swaps from the highest-projection lineup, maximizing P(your starters + noise >
  theirs). Noise: kickers and team defenses, unmodeled, with the kicker's week-to-week spread from box scores
  (4.7 pts) and a typical 6 for defenses, on both sides. Players whose game started are locked (ESPN lineup slot
  from a this-week import, else where the projection lineup puts them).
- `needCalc`: for each candidate, P(candidate + your other players still to play − theirs + noise > deficit);
  with nobody else, P(points > need). The page draws each candidate's P(points ≥ x).

## Data the builder adds (db v6)

`gs` (this week's game status: CBS "X for Week N", else the NFL report), `pr` (last practice), `gd` (game-day
active/inactive from `gameday.json`), `DB.opp` and `DB.kick` (this week's opponents and kickoffs), `DB.gameday`.
The NFL's own Out and Doubtful designations now count as missing this week's game even without a CBS row (on
Oct 17 the live page still had Lamar Jackson, Jalen Hurts and Saquon Barkley playing because the Saturday run
had stopped and the CBS pages weren't read).

## Refreshes

`runbooks/gameday.md`: Thursday about 6:52 pm ET (after the Thursday game's inactives) and Sunday about 11:37 am
ET (after the 1 pm inactives). Each folds in CBS pages, the NFL report, and game-day inactives posted so far,
republishes, and freezes a pre-kickoff snapshot (`late-thu`, `late-sun`, ...). The scorecard's "late" view takes,
for each player, the latest snapshot frozen before his kickoff.
