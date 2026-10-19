# Fantasy Trader — Tuesday run: refresh, grade, improve, publish, freeze

Repo: github.com/AC-codemaster/fantasy-trader (private). Everything below happens in a clone of it.
Page: https://claude.ai/artifact/QYtsAKr3WaL59s1xWMcw1C · Scorecard: https://claude.ai/artifact/XzYv5c3LZNYyQVCUen71Rz

Order matters: grade last week first (the improvement loop reads the grades), improve, rebuild with the
live parameters, run the tests, publish, then freeze what was published. A failure in grading or the
improvement loop never blocks the data refresh: report it and carry on. Never publish partial or
obviously wrong data.

## 0. Repo and work folder
- `add_repo` owner `AC-codemaster`, repo `fantasy-trader`, access `push`; then clone it and `cd` into it.
- `mkdir -p work && cd work` — all downloads and builds happen here (git-ignored). Commands below run
  from `work/` and call scripts as `../pipeline/...`.
- `pip install -q --break-system-packages pandas numpy` only if missing; `node` must be on the PATH.

## 1. Download inputs and find the week
- `python3 ../pipeline/build_db.py --fetch` — nflverse + DynastyProcess (GitHub only); prints the current
  week. If a download fails, retry once; if it still fails, stop and report.
- `python3 ../backtest/fetch_history.py <S-2> <S-1> <S>` with S = the current season (e.g. 2024 2025 2026)
  — past seasons for the backtest.
- Copy last week's injury news: `cp ../data/inputs/<S>/w<previous WW>/injury_news.json .` (the newest
  archived one), or the project doc `claude/injury_news.json` if newer.

## 2. CBS Sports injury pages (all 32 teams)
WebFetch `https://www.cbssports.com/nfl/teams/{CODE}/{slug}/injuries/` with the prompt:
"Copy the whole injury table verbatim (all positions): player | position | updated | injury | injury status."
Keep QB, RB, WR, TE and K rows (kickers have injury timelines too; team defenses don't). Write `cbs_injuries.tsv` with header `team	player	pos	injury	status`
(tab-separated, team = CBS code below, status text verbatim). If a page comes back empty, retry once.

ARI arizona-cardinals · ATL atlanta-falcons · BAL baltimore-ravens · BUF buffalo-bills · CAR carolina-panthers · CHI chicago-bears · CIN cincinnati-bengals · CLE cleveland-browns · DAL dallas-cowboys · DEN denver-broncos · DET detroit-lions · GB green-bay-packers · HOU houston-texans · IND indianapolis-colts · JAC jacksonville-jaguars · KC kansas-city-chiefs · LV las-vegas-raiders · LAC los-angeles-chargers · LAR los-angeles-rams · MIA miami-dolphins · MIN minnesota-vikings · NE new-england-patriots · NO new-orleans-saints · NYG new-york-giants · NYJ new-york-jets · PHI philadelphia-eagles · PIT pittsburgh-steelers · SF san-francisco-49ers · SEA seattle-seahawks · TB tampa-bay-buccaneers · TEN tennessee-titans · WAS washington-commanders

## 3. News check on major injuries
`python3 ../pipeline/build_db.py`, then from db.json list fantasy-relevant players (have `er`, or `own` ≥ 20)
on IR/PUP with no CBS expected return, with serious injuries (ACL, Achilles, fracture, surgery), or newly
placed on IR. WebSearch each for a return timeline and update `injury_news.json`: add/update
`{"name","team","thru","note","src","date"}` (`thru` = last week missed; 18 = season; return week N → N−1),
remove players back on the active roster or whose `thru` has passed, set `"updated"` to today. Only record
timelines a credible report states.

## 4. Grade last week
`python3 ../pipeline/scorecard.py grade` — grades every frozen week whose games are done (nflverse stats,
FantasyPros history via a blobless clone into `dp-history/`), reruns each archived week with hindsight
availability, grades rest-of-season projections, sweeps the expert weights, and rewrites
`../data/graded/`, `../data/ros/`, `../data/scorecard/`. Partial weeks are re-graded next Tuesday.

## 5. Improve the model (runbooks/improve-agent.md has the details)
- First the agent step in improve-agent.md §2 (usually nothing to do).
- Then `python3 ../improve/improve.py` (5–10 minutes). It re-checks changes on probation, tests up to 8
  parameter changes on the offense backtest and up to 3 kicker/D-ST settings on their own replay
  (`backtest/kdst_backtest.py`), and adopts at most one change in all that passes the gate, editing
  `../params/params.json` and writing `../ledger/`. Read `../ledger/last_run.md` for the summary.
- If it errors, run it again once with `--budget 4`; if it still fails, skip it this week and report.

## 5b. Recalibrate the start/sit distributions
The projection model may have changed in step 5, and with it how far its numbers sit from what happens.
- `python3 ../dist/bt_frames.py` (about a minute: the backtest projections with their stat lines), then
  `python3 ../dist/fit_dist.py means --write` — refreshes the mean multipliers and the chance-he-plays table in
  `../params/dist.json`, keeps the fitted spreads and correlations (those are refitted yearly, see
  `runbooks/annual-refit.md`). Report the line it prints. If it fails, keep the old file and say so.

## 6. Final build and checks
- `python3 ../pipeline/build_db.py` — with the live parameters (step 5 may have changed them).
- Sanity: 400–580 players, including 32 defenses and 28+ kickers (the line "kickers and defenses: N kickers, 32
  defenses; week W (standard scoring) D/ST: ... | K: ..." names the week's top ones; implausible names or a
  missing team means a roster problem: report it); the current week is right; `sources` dates recent; absences plausible
  (season-ending at 18, IR returns on sensible weeks); "weekly expert ranks for week N" names the current
  week (None is fine: FantasyPros hasn't posted yet); game-environment swings roughly −30% to +25%.
- `python3 ../tests/run_tests.py` must pass. If it fails only after a parameter change from step 5: restore
  the previous `../params/params.json` (`git checkout -- ../params/params.json`), append a line to
  `../ledger/changelog.md` saying the change was withdrawn because tests failed (name the test), remove it
  from `probation` in `../ledger/state.json`, rebuild, and rerun the tests. If tests fail without any change,
  publish the data refresh anyway but report the failure.

## 7. Publish the page
- `python3 ../tools/make_page.py --db db.json --injnews injury_news.json --out fantasy-trader.html`
- `Artifact` action `read` on the page URL (required before republishing), then `Artifact` publish with
  `file_path` = `fantasy-trader.html` and `url` = the page URL. Omit `capabilities` and `icon` (the page
  keeps its stored ones). Label: "Week N data" (add ", params vN" when step 5 changed them). Note the
  version id. If the publish reports a conflict, re-read and publish once more.

## 8. Freeze this week
`python3 ../pipeline/scorecard.py freeze --page fantasy-trader.html --cbs cbs_injuries.tsv --version <version id>`
— runs the published page's engine, writes `../data/freeze/`, `../data/ros/` and archives the inputs in
`../data/inputs/<S>/w<WW>/`. It refuses to overwrite a freeze: never pass `--force`, never edit a freeze.
Skip if the regular season has no unplayed games. Then `python3 ../pipeline/scorecard.py grade` once more
(fast) so the scorecard lists the new frozen week.

## 9. Publish the scorecard
`Artifact` action `read` on the scorecard URL (no path), then publish with `url` = scorecard URL,
`file_path` = `../scorecard_page/index.html`, `root` = the repo root, `files` =
`{"data/scorecard.json": "data/scorecard/scorecard.json"}`. Omit icon and capabilities. Label "Week N
frozen, week N−1 graded". On a conflict, re-read and repeat once.

## 10. Save everything
- From the repo root: `git add -A params ledger data pipeline engine page backtest improve tests tools runbooks docs scorecard_page dist README.md`
  then commit ("Week N: refresh, grade, improve (<adopted change or 'no change'>)") and `git push`.
  If the push is rejected, `git pull --rebase` and push again.
- **Check it landed:** `git fetch origin main`, then `git rev-parse HEAD` must equal `git rev-parse origin/main`.
  If not, push once more; if it still doesn't match, put the exact error at the top of the report. (The Oct 13
  run's push silently never arrived, so main lost that week's parameters and freeze until they were rebuilt.)
- Project docs (Projects tool, `project_write` with `local_path`): `claude/scorecard.md` ←
  `data/scorecard/scorecard.md`; `claude/model-changelog.md` ← `ledger/changelog.md`;
  `claude/injury_news.json` ← `work/injury_news.json`.

## 10b. Gameday task check
Every game-day refresh comes from one self-scheduling task (`runbooks/gameday.md`, "Scheduling"). Make sure it's
armed: `python3 tools/gameday_slots.py` (from the repo root) prints the `next` slot; `list_triggers` and find
**Fantasy Trader gameday refresh** (`trig_01SUieyie6kMwKGEbyqUzdnm`). If it is disabled or its `next_run_at`
isn't the same moment as the printed `next.at`, `update_trigger` it with `cron_expression` = `next.cron` and `enabled=true` (with no
`next` slot, leave it paused). Say in the report what you changed, if anything. Don't create one-time tasks.

## 11. Report
A short summary: data week; notable injury changes; last week's average miss for our page vs FantasyPros
Tuesday vs FantasyPros final, and with hindsight; start/sit %; the goal lines; kickers and defenses (the
scorecard's "Kickers and defenses" section: our miss and start/sit % vs FantasyPros, from the Week 7 freeze on); what the improvement loop
tested and adopted or reverted, kicker/D-ST settings included (from `ledger/last_run.md`); the distribution recalibration line (5b); whether
the push landed; anything that failed. If the season is over
(no unplayed regular-season games): grade, publish the scorecard, commit, and say so.
