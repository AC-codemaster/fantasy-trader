# Trade finder (Oct 28, 2026)

The finder used to rank every deal by **your gain × the chance they accept** and keep anything above a minimum
acceptance (30% on the page). That objective is "the biggest loss the other manager will still sign": on the user's
league (Week 5 fixture) 37 of its top 40 deals cost the partner more than 1 pt/week, median −1.4. Trading in a league
of friends isn't supposed to be that, and the acceptance model is the hardest part of the engine to calibrate against
a real league. So the finder now ranks on what a deal really does to both lineups, and acceptance only screens.

## Tiers

Every listed deal gains you at least 0.25 pts/week on our projections and clears the acceptance screen (10% by
default, adjustable from 0). Within that:

| Tier | Rule | Ranked by |
|---|---|---|
| Both teams improve | their real change ≥ 0 | your gain × their gain (per week) |
| Slight cost to them | −slight ≤ their change < 0, and your gain > their loss | your gain + their change |
| Lopsided (opt-in) | everything else | your gain × P(accept), the old score |

**Why the product.** It is what the Nash bargaining solution maximizes: among deals that help both sides it prefers
ones that help both a real amount. Helping both by a point (1 × 1 = 1) beats helping you by three and them by a
tenth (3 × 0.1 = 0.3), and a deal that is great for both beats one that is merely balanced.

**Why "your gain > their loss" in the slight tier.** Then the two lineups gain together, so the deal creates value
rather than only moving points from them to you.

## What "slight" means

The engine scores each team-week as its expected lineup plus noise with sd = 0.18 × the league's average lineup
(`TEAM_CV`, the same spread `seasonOdds` simulates). In an even matchup the margin has sd √2·sd, so a point a week
moves the weekly win chance by φ(0) / (√2·sd) = 1 / (sd·√(4π)). `matchupScale(ctx)` returns that and the default
slight-cost line, the loss worth **1.5% of a win a week** (`SLIGHT_WIN`):

| League average lineup | sd | Win chance per pt | Slight line |
|---|---|---|---|
| 90 | 16.2 | 1.74% | 0.86 pts/wk |
| 110 | 19.8 | 1.42% | 1.05 pts/wk |
| 120 | 21.6 | 1.31% | 1.15 pts/wk |

Over a 10-week rest of season that is about 0.15 wins, inside the luck of the schedule and too small for the other
manager ever to see in his results. The page has a slider for it (with a button back to the league's default).

## FAAB

- **Making a deal fair.** For deals that don't help both sides but where the two lineups gain together (and the loss
  is within what 60% of your FAAB can cover), the finder tries your money in 5%-of-budget steps and keeps the amount
  with the largest your-gain × their-gain among those that leave both better off, stopping once their gain reaches
  yours. The sweetened deal replaces the same players without money.
- **Evening out.** On a both-improve deal that helps them more than you, it notes the most of their FAAB (up to half)
  you could ask for while they still gain at least as much as you.

## Page

Results come in a section per tier. "They see" stays (how the deal looks on market numbers); on a both-improve deal
where it is negative, the row says "walk them through it": the deal is good for them but doesn't look it. The Trade
tab's headline names the slight-cost case ("You gain X, and it costs them only Y (about Z% of a win a week)").

## Checks (`tests/run_tests.py`, trade_engine_regressions)

On the user's league (all partners) and a sample league with FAAB (three partners, with and without lopsided deals):
tiers in order, every deal above the floors and in the right tier, no deal outside the lopsided tier costing the
partner more than the slight line, no lopsided deals unless asked, any FAAB ask leaving them at least your gain; at
least 3 both-improve and 10 slight-cost deals in the user's league and 10 both-improve in the sample league.

## Targeting players (Oct 28, 2026)

"Target specific players" takes players you want (on other teams) and players you'd trade away (yours). The search
then only evaluates deals that land a wanted player or move a shopped one (`findTrades` options `want`, `shop`):

- **Goals first.** Within each tier, deals that reach more goals (wanted players received + shopped players sent)
  come first, then the tier's usual score.
- **A small price is allowed.** Your floor drops from +0.25 to 0 pts/week, and a fourth tier, **small price for you**,
  lists deals that cost you under the slight line while they gain more than you lose (ranked by what they cost you,
  least first). With lopsided deals on, anything else that gains the two lineups together is listed too.
- **Wider search around targets.** Owners of wanted players are searched even when not among the picked partners;
  around a wanted player the search adds 2-for-2 and 3-for-1 packages (a "3 for 1" shape is also on the page for
  untargeted searches). Named players can be below the usual 6-point cut, and kickers or defenses if you name them.
- **Variety.** Named players don't count toward the 3-deals-per-player limit; instead each "core" (partner + named
  players moving, e.g. Lamb + Brown for Nacua) shows its best two versions across all tiers, so throw-in variants
  don't crowd out other routes.
- **FAAB both ways.** Money can now make a deal help both sides from either direction: yours when it costs them,
  theirs (up to half) when it costs you or gains you too little, in the amount with the largest product of gains.

Example (Week 8 data, the fixture league seen from Team 1, wanting Nacua and Kyren Williams, shopping Chase Brown and
CeeDee Lamb): about 7,500 deals in 2 seconds; the top deals are Lamb + Brown (alone or with a throw-in) for Nacua,
which help both lineups.

## Ignoring injuries (Oct 28, 2026)

"Ignore injuries (except season-ending)" runs the finder on `healthyView(DB, L)`: a copy of the data and league where
every player whose out week falls before the league's last week is marked healthy (his `L.out` set to 0, his data
timeline cleared), so he plays every week and his teammates' roles go back to normal. Players out through the last
week stay out. A player who was out two or more weeks is flagged (`hx`) so the expert blend skips him, as it does
while he's out, because the experts' rest-of-season rank prices in the games he'd miss. Injury tags stay, so this
week's weekly rank (which prices the chance he sits) still isn't used for him. The page builds this view once per
league change; the Trade tab keeps counting injuries, and the finder says so when the option was on.

Checks: the targeted search reaches each wanted and shopped player, every deal reaches a goal, goals are ordered,
cores are capped at two; the healthy view clears exactly the non-season-ending absences, keeps season-ending ones,
lets cleared players play every non-bye week, and leaves the league untouched.
