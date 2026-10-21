# Waivers: the best pickups for your team, with their upside (Oct 20, 2026)

The page's Waivers tab ranks free agents by what each is worth to one team: what he adds to its starting lineups this
week and for the rest of the season, against the player it would drop for him, plus his upside. Upside counts for
more when the team can afford to wait for it. Engine: `engine/engine.js` (`waiverBoard`, `stashScenarios`,
`contingent`, `seasonOdds`, `waiverWeights`); the upside bank: `params/stash.json`, built by
`waivers/stash_study.py`; page: `page/ui.js` (`renderWaivers`); checks: `tests/waiver_checks.js`.

## Value on projection (first principles)

For roster R, drop d and pickup x, week by week:

    gain_t = lineupEV_t(R - d + x) - lineupEV_t(R)          value = sum_t w_t * gain_t

`lineupEV` is the trade tool's weekly lineup math (best legal lineup, injury cushion). Two choices make it a waiver
tool rather than a trade tool:

- **This week has no free streamer.** This week's pickup is the decision being made, so x is measured against the
  lineup you have (a bye or injury hole makes any healthy player at that position worth his full projection). Later
  weeks keep the streamer at each position (the moves you'll make then).
- **He comes off the wire.** He's one of the free agents the streamer stands for, so with him rostered the streamer at
  his position is the next one (same depth and interpolation as `streamLevels`). Without this, adding the best free
  agent in a shallow league was worth nothing (he was already "streamed").

The drop is whichever of your four least valuable players (by what each adds to your lineups the rest of the
season, `dropCost`) gives the highest value; an open roster spot means no drop. IR-slotted players (ESPN slot 21
when imported, otherwise players on a reserve list, up to the league's IR slots) don't use a bench spot and aren't
dropped. Check: with every week weighted evenly and a streamer this week too, the board's value equals the change in
`teamValue` when the league is rebuilt with x on your roster (max difference 0.09 points over 12 pickups,
quantization).

## Upside: the stash bank

A projection is one number, but a waiver player's role can change (the starter ahead of him gets hurt, he wins the
job, his team trades someone), and you only start him in the weeks it pays. Lineup value is convex in his level, so
E[value(his level)] > value(E[his level]): the good outcomes count and the bad ones mostly don't.

`stash_study.py frames` replays the projection model (`backtest_core.Season.project`, through a per-team hook that
changes nothing else) at every week of 2022-26 and records, for every player on an active roster:

- `p0`: his projection that week as if he plays (a player who sat gets his own share added back, as the engine does);
- `c`: his projection if the best teammate at his position ahead of him sat (the contingent role; that teammate's
  work goes to the others as in a short absence: `damp` of it to depth players, a QB's attempts in full; c = p0
  when nobody at his position projects above him);
- his projection in every later week given who actually played then: 0 when his team played without him (hurt,
  inactive, cut), blank on a bye.

Everything is measured in **weekly-starter lines**: the projection of the 12th QB, 24th RB, 30th WR, 12th TE that
week. In those units the bank works for any scoring and league size; the page draws the same line from its own
projections (`starterLines`). `fit` keeps the rows a league could have on waivers (outside the top 8 QB / 18 RB /
24 WR / 6 TE by p0 that week, weeks 3-15, completed seasons): 21,470 rows, 2022-25.

A free agent's scenarios (`stashScenarios`) are the paths of the 60 nearest rows at his position, by

    d^2 = ((rel0 - rel0')/0.06)^2 + ((relc - relc')/0.15)^2 + ((week - week')/4)^2 + ((rookie - rookie')/0.5)^2

(rel = projection / line; kernel weights exp(-d^2/2)), each laid onto his own weekly projection: in week t his level is
`max(0, a_t + (rel'_k - rel0') * line_t)`, zero in weeks he's on bye or out; a player out now starts his scenarios the
week he's back. His value is the weighted average over scenarios; **Upside** = that minus his value on projection.
Kickers and defenses are valued on their projections (their swings are matchups, already in the projection).

### Checks (each season predicted from the other seasons' rows only)

Breakout = projecting at or above the weekly-starter line in one of the next four weeks.

| | log loss (breakout) | rank corr, expected vs actual surplus, all | stash zone (below 80% of the line) | top-10 stash-zone surplus |
|---|---|---|---|---|
| bank, all features | 0.1480 | 0.593 | 0.283 | 0.102 |
| no contingent role | 0.1490 | 0.591 | 0.282 | 0.090 |
| no week | 0.1485 | 0.582 | 0.268 | 0.107 |
| no rookie flag | 0.1473 | 0.581 | 0.269 | 0.089 |
| projection only (ranking); one rate per position (log loss) | 0.352 | 0.524 | 0.224 | 0.081 |
| **thinned bank (the page's)** | 0.1485 | 0.587 | 0.276 | 0.102 |

Surplus = sum over the next 8 weeks of max(0, level - line), in lines. Calibration of the breakout chance (thinned
bank): predicted 3.5% / 7.4% / 14.1% / 27.5% / 42.1% / 60.3% / 81.4% vs actual 3.6% / 7.2% / 13.6% / 29.4% / 39.9% /
60.7% / 81.9% (bins of 680-1,370 rows; below 2% predicted, 0.1% vs 0.3% on 15,100). Kernel widths were chosen on the held-out results (a grid of 72; differences are small).

Rookies: at the same projection, rookies more often grew into weekly starters (60-80% of the line: 13.5% vs 11.5%
within four weeks) and their 8-week surplus was about twice veterans' (0.094 vs 0.042 lines), which is why the
rookie flag helps the ranking even though it slightly worsens the log loss. The contingent role helps the ranking at
the top (0.090 -> 0.102) more than the breakout chance: the model's own split of a starter's work (Luce weights, 30%
to depth players) gives a backup about 1.6x his share, not the starter's whole role.

The page carries a thinned bank (209 KB, 12,449 rows): below 10% of the line one row in 8 (weight 8), 10-30% one
in 3 (weight 3), everything above. Thinning every other week above 30% cost a sixth of the top-10 surplus, so those
rows stay. Encoding: one string per row (week, rel0 in steps of 0.02, relc in 0.04, flags = rookie + 2 x broke out +
4 x weight code, then the path one character a week in steps of 0.04 up to 2.52, "." for a bye).

## Can you afford to wait for it?

**Which weeks count (`waiverWeights`).** Default "auto": your title chances. `seasonOdds` simulates the rest of the
season 2,500 times: the ESPN schedule when imported (random pairings otherwise), records and points for so far, each
team's projected lineup every week (`lineupForWeek` at its waiver depth) plus a weekly swing of 18% of the league's
average lineup, seeding by wins then points, and the bracket (top seeds get byes when the field isn't a power of
two; the playoff weeks split evenly into rounds, a two-week round adds both weeks). Then it adds half a swing to your
score one week at a time, in the same simulated seasons, and counts how often you win the title:
lev_t = dP(title)/dpoints in week t. The weights are `lam * lev (scaled) + (1 - lam) * even`, lam = min(0.75,
title wins / 150) (no signal, no tilt), scaled to the trade tool's total (`wSum`) so values stay in rest-of-season
points. Checks: title chances add up to 1 across a league, playoff chances to the field size; on a fixed build an
unbeaten team's playoff weeks count 4x its regular weeks, a winless team's 1.4x. Other modes: every week the same
(the trade tool's weights), the next few weeks (each 60% of the one before), the playoff weeks (regular weeks a
quarter as much).

**How long you can hold him.** Room = open spots (starting slots + bench - roster, IR excluded) + players adding
less than 1 point to your lineups the rest of the season (free to drop). Each week, the streamers in your best lineup
are the fill-ins you need (byes, injuries); each needs a spot. The hold week H is the first week the pickup leaves
your lineup a fill-in short that you could have covered without him:
`max(0, holes_t(after) - room_after) - max(0, holes_t(before) - room) > 0`. Past H a stash stays only if his
projection at H, carried forward (what you'd know then, not his future), is worth more than the fill-ins he costs;
if he stays, those fill-ins are charged. With no crunch, he can sit all season.

## FAAB

Worth up to: value / `faabPerDollar` (the going rate for the season's remaining waiver breakouts, the trade tool's
FAAB price). The rival is the other manager who'd gain most from him by his own view (`perspective`: his style and
favorite team; he drops the player he values least; "q" lineup math); bid = min(your worth, his dollars + 1, your
budget). If he values the player more, the page says so.

## Not modeled yet

- The chance you'd win him on waivers anyway after his role grows: a handcuff is worth less than shown if you'd surely
  win that claim. (Needs the claim competition after a breakout; the obvious data source is the league's own
  transaction log.)
- Breakouts among the other free agents: the streamer is the wire as it projects today.
- Grading: the board isn't frozen and graded yet. The natural test: each Tuesday's top 20 by value vs by projection
  alone, scored by what they added to the team's lineups over the next four weeks.

## Refit

Yearly with the annual refit (`runbooks/annual-refit.md` step 7c): fetch history, `stash_study.py frames --seasons
<H>` for the season just finished, `fit --write`; keep it if the thinned bank still beats the projection in the stash
zone (the test checks this and the calibration).
