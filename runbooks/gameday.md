# Fantasy Trader — pre-kickoff refresh (Thursday night, Sunday morning)

Purpose: the best injury information before games lock. Thursday's run starts right after the Thursday game's
inactives (about 6:45 pm ET for an 8:15 pm kickoff); Sunday's right after the 1 pm inactives (about 11:30 am ET).
Each run folds in the latest injury reports and every game-day inactive list posted so far, republishes the
page (projections, Start/Sit, the floor-vs-ceiling tools) and freezes a pre-kickoff snapshot. No grading, no
improvement loop, no parameter changes.

Repo: github.com/AC-codemaster/fantasy-trader · Page: https://claude.ai/artifact/QYtsAKr3WaL59s1xWMcw1C

**The deadline is kickoff.** Thursday: 8:15 pm ET. Sunday: 1:00 pm ET. Publish by kickoff minus 15 minutes; if
you're running late, skip what's marked *optional* and publish. A page published after kickoff still helps the
later games, so publish late rather than not at all, and say so in the report.

## 0. Setup and the snapshot tag
1. `add_repo` owner `AC-codemaster`, repo `fantasy-trader`, access `push`; clone (generous timeout); `cd` into
   it; `mkdir -p work && cd work`.
2. The snapshot tag comes from the current time in America/New_York: Thursday → `late-thu`; Sunday before
   10:00 → `late-sun-am`; Sunday from 10:00 → `late-sun`; any other day (a catch-up run) → `late-` plus the
   three-letter weekday (`late-sat`, `late-fri`, ...). If the run's prompt names a tag, use that one.

## 1. Data and the week
- `python3 ../pipeline/build_db.py --fetch`. It prints the current week. If the regular season has no unplayed
  games, stop with a one-line report.
- Injury news: start from the newest of `../data/inputs/<S>/w<WW>/injury_news.json` (and its `late*/`
  folders) and the project doc `claude/injury_news.json`; copy it to `injury_news.json`.

## 2. Game-day inactives (the reason this run exists)
Teams post inactives 90 minutes before kickoff. From `games.csv`, list this week's games whose kickoff
(America/New_York) is at or before now + 80 minutes, and whose kickoff was no more than 5 hours ago (finished
games don't matter). For each of those games:
- WebSearch `NFL Week <W> inactives` and WebFetch the CBS Sports or NFL.com live inactives tracker if one comes
  up (one page covers every game); fill any team it lacks with that team's own site (`<Team> inactives week
  <W>`, e.g. neworleanssaints.com/news/...inactives...), ESPN or Yahoo. Use a list only if the source names it
  as the official inactive list for this game.
- Write `gameday.json`:
  `{"updated": "<ISO time>", "teams": {"<code>": {"inactive": ["Full Name", ...], "src": "<site>"}}}` with every
  inactive player the source lists (all positions are fine; names as the source gives them), and team codes
  as in `games.csv` (LA, JAX, WAS ...). Include a team only when you found its list; an empty list means you
  found it and nobody notable is inactive. Teams not in the file stay as the injury report has them.
- If none are posted yet (an early run), skip this step: Questionable players keep their chance to play.

## 3. Injury reports
- CBS Sports team injury pages, all 32 teams: exactly step 2 of `runbooks/weekly.md` (→ `cbs_injuries.tsv`).
  If time is short, do the teams that play after now first.
- *Optional, only with time to spare:* the news check on major injuries, step 3 of `runbooks/weekly.md`,
  limited to players newly out (no need to re-check timelines that Tuesday's run already confirmed).
- The NFL's own report for the week (nflverse injuries, downloaded in step 1) also counts: Out and Doubtful
  mean he misses this week's game, Questionable sets his chance to play from his last practice.

## 4. Build and check
- `python3 ../pipeline/build_db.py`. Read its summary: the current week; "this week's game status: N
  questionable, ..."; "inactives posted for ...: N of our players inactive" (check a few names you know were
  inactive); timelines plausible.
- `python3 ../tests/run_tests.py` must pass; if it doesn't, don't publish — report the failing test.

## 5. Publish
- `python3 ../tools/make_page.py --db db.json --injnews injury_news.json --out fantasy-trader.html`
- `Artifact` action `read` on the page URL, then publish with `url` = the page URL, `file_path` =
  `fantasy-trader.html`, no capabilities or icon, label "Week N <weekday> pre-kickoff". Note the version id.
  On a conflict, read again and publish once more.

## 6. Freeze the snapshot
`python3 ../pipeline/scorecard.py freeze --page fantasy-trader.html --tag <tag> --cbs cbs_injuries.tsv --version <version id>`
(players whose game already kicked off are left out; never `--force`). If it says there is no Tuesday freeze
for the week, skip it and say so in the report. Also copy `gameday.json` next to the archived inputs:
`cp gameday.json ../data/inputs/<S>/w<WW>/<tag>/` (the freeze creates that folder).

## 7. Save
- From the repo root: `git add -A data` then commit ("Week N: <weekday> pre-kickoff refresh (<tag>)") and push.
  If the push is rejected, `git pull --rebase` and push again.
- **Check it landed:** `git fetch origin main` and compare `git rev-parse HEAD` with `git rev-parse origin/main`.
  If they differ, push once more; if they still differ, put the exact error at the top of the report.
- Project doc `claude/injury_news.json` ← `work/injury_news.json` (Projects tool, `project_write` with `local_path`).

## 8. Report (a few lines)
When it published (and whether that was before kickoff), the teams whose inactives were included and any
notable inactive or newly ruled-out fantasy starters, Questionable starters still open, and anything that failed.
