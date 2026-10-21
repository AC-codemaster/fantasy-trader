# Kickers and team defenses (K, D/ST)

Added Oct 19, 2026. Before that, kickers and defenses weren't in the data: ESPN imports skipped them, lineups had no
K or D/ST slot, and start/sit added their typical week-to-week swing to both sides as noise.

## Where it lives

| Piece | What |
|---|---|
| `pipeline/kdst.py` | the model: history tables from nflverse box scores, league constants, team and kicker profiles, weekly expected stat lines, ESPN-standard points. One implementation for the builder, the backtest and the grading. |
| `pipeline/build_db.py` | builds one D/ST per team (`id` `DST-<team>`, ESPN id −16000 − ESPN team id) and each team's kicker, with `kw` = an expected stat line for every remaining week, `s`/`f`/`s25`/`s24` (per-game averages this season, last two games, the two seasons before), expert, draft, roster-% and weekly ranks from FantasyPros; `DB.kdst` holds the component names and what the simulation needs. |
| `engine/engine.js` | scores the weekly lines with the league's settings (`kScore`, `dScore`, `kdModel`), fills K and D/ST slots, prices them in trades, simulates them in start/sit (`simKd`), imports them from ESPN (`parseKdScoring`). |
| `backtest/kdst_backtest.py` | replays the model at every past week with only earlier data; the improvement loop tunes the K/DST settings on it. |
| `pipeline/scorecard.py` | grades frozen K/DST projections (ESPN standard) against box scores and FantasyPros, in their own section. |
| `params/params.json` | the twelve tunable settings, `eval: "kdst"`. |
| `params/dist.json` `kdst` | spreads and links for the start/sit simulation, fitted on box scores (`dist/fit_dist.py fit_kdst`). |

## The model, per game

**Kicker.** PAT tries = league line on the team's implied total and spread (about 0.14 per implied point) × the
team's own factor beyond its line (shrunk by `k_pvol` attempts). Field-goal tries = the same kind of line (nearly
flat in the total; favorites kick a few more) × the team's factor (`k_kvol`). Tries split by distance (0–39, 40–49,
50–59, 60+) with the kicker's own mix shrunk to the league's (`k_mix` attempts); made at his rate per distance shrunk
to the league's rate there (`k_fg`), PATs at his PAT rate (`k_pat`). Kicker history: this season 1, last `w_kprev`,
the one before `w_kprev²`. Component order: PAT made, PAT missed, FG made 0–39, 40–49, 50–59, 60+, FG missed 0–39,
40–49, 50+.

**D/ST.** Sacks, interceptions, fumble recoveries: a Poisson log-linear league rate on the opponent's implied total
and the spread (both fitted on every game in the history window with a line), × the defense's factor (`k_dst` games of
league average) × the opposing offense's factor for what it gives up (`k_off`). Safeties at the league rate; return
TDs and blocked kicks at the league rate × a heavily shrunk team factor (`k_st`); defensive TDs = takeaways × the
league's TD share of takeaways. Points allowed: the opponent's implied total + the empirical spread of real points
allowed around it (ESPN's definition: the opponent's points minus 7 per defensive TD it scored), scaled by `pa_scale`,
giving a probability for each ESPN tier (0, 1–6, 7–13, 14–17, 18–21, 22–27, 28–34, 35–45, 46+). Yards allowed: a
line on the opponent's implied total + each side's yardage tendency beyond its line (`k_ya`), normal with the
residual spread, giving tier chances (<100 … 550+). Team history: this season 1, last `w_dprev`, before that squared.
Component order: sacks, INT, fumble recoveries, safeties, defensive TDs, return TDs, blocked kicks, points allowed,
yards allowed, the nine points-allowed tier chances, the nine yards-allowed tier chances.

**Weeks without a line** use the market-rating projection of the implied totals, shrunk exactly like the offense's
game environment (`env_shrink`).

**Scoring.** ESPN standard (support.espn.com "Scoring Formats", plus the yards-allowed tiers of ESPN's default leagues):
PAT 1, FG 0–39 3, 40–49 4, 50–59 5, 60+ 6, any miss −1; sack 1, INT 2, fumble recovery 2, safety 2, blocked kick 2,
defensive or return TD 6, points allowed 5/4/3/1/0/0/−1/−3/−5, yards allowed 5/3/2/0/−1/−3/−5/−6/−7. `kdst.STANDARD`
and the engine's `DEFAULT_SETTINGS.scoring` must agree (tested). An ESPN import reads each league's own rules
(`parseKdScoring`). ESPN keeps most D/ST rules (sacks, takeaways, safeties, blocks, return TDs, points- and
yards-allowed tiers) as an override on the D/ST lineup slot (`pointsOverrides["16"]`) with `points` 0, and
kicker rules may sit on slot 17, so the slot's override comes first. Field goals 50–59 are stat 198 and 60+ 201 in
current leagues (74 "50+" in older ones); points-allowed tiers are 89–92/121–125 or the D/ST versions 188–196;
overlapping rules add up. Until Oct 20, 2026 the import read `points` only, so imported leagues scored D/ST on
touchdowns alone and 50–59-yard field goals at 0 (re-import such a league; tests now use ESPN's real shape).

## How good it is (backtest, Oct 19, 2026)

Every week from week 3 of 2024 and 2025 and week 2 of 2026 through week 5, projected with only earlier data and the
week's actual line, every D/ST and every kicker who kicked (2,163 player-games), ESPN standard:

| | Our miss | Season-to-date average | League average |
|---|---|---|---|
| D/ST | 4.62 | 5.10 | 5.10 |
| K | 3.76 | 3.90 | 3.81 |

Defenses are about 9% better than their own averages, mostly from the line (points allowed and pressure follow the
opponent). Kickers are close to noise week to week; the line and his leg are all there is. The live comparison with
FantasyPros starts with the Week 7 freeze (scorecard section "Kickers and defenses").

## Start/sit simulation

From each weekly line, with spreads and links fitted on 2022–25 box scores (`params/dist.json` `kdst`): a kicker's
PATs follow his own offense's simulated touchdowns (box-score correlation 0.87), his field-goal tries are steadier
than Poisson (variance/mean 0.85) and slightly fewer when there are more PATs (−0.21); a D/ST's points allowed follow
the opposing offense's simulated touchdowns (0.91), yards allowed follow points allowed (0.68), and sacks and
takeaways rise on a good defensive day (each with a game shock sized from its over-dispersion). Simulated means equal
the page's projections; simulated spreads match box scores (K ≈ 4.7, D/ST ≈ 5.9 points). A D/ST facing your own
quarterback moves against him (≈ −0.45 in the simulation). The old noise term only applies to data without kickers or
defenses (archived weeks before Oct 19).

## Trades and the market

Managers' market view uses the same signals as for everyone (season, form, PRK, track record, ADP, roster %, expert
rank, ESPN projection); FantasyPros covers kickers and defenses in its rest-of-season, weekly, overall and preseason
rankings (defenses matched by team). Trade value uses the QB/TE rank ladder: the overall rankings list only a handful
of kickers and defenses, far down, so their trade value is near zero even when they help a lineup — the lineup-need
half of acceptance still counts them. The trade finder leaves them out of its search; the Trade tab values them like
anyone else. Sample leagues draft one kicker and one defense per team, last.

## Grading and tuning

The freeze holds K/DST rows like any other (`page_ppr` = ESPN standard). `scorecard.py grade` scores them from box
scores (`a_kd`), keeps them out of the headline metrics and the goal lines (which stay QB/RB/WR/TE, continuous with
the weeks graded before), and reports them in their own section with FantasyPros' numbers (note: FantasyPros' D/ST
points may use scoring without yards allowed, so compare rank correlation and start/sit calls more than misses). A
lean of 0.75+ pts at K or D/ST (2.5 SE, 60+ players) becomes a lean the improvement loop tests ("K level", "DST
level"). The loop tests up to three K/DST settings a week on `backtest/kdst_backtest.py` with the same gate, and at
most one change is adopted per week across offense and K/DST (the larger gain relative to its replay's average miss).

## Limits

No weather (wind and cold matter for long kicks; the data has no forecasts), no defensive injuries, no kick-return
specialists, no IDP. A kicker newly signed after the build appears at the next refresh. Points allowed approximate
ESPN's rule (7 per defensive touchdown, PATs included).
