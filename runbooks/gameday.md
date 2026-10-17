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
Teams post inactives 90 minutes before kickoff. From `games.csv`, list this week's games whose inactives are due
(kickoff minus 90 minutes, America/New_York, is at or before now) and whose kickoff was no more than 5 hours ago
(finished games don't matter). For each of those games:
- WebSearch `NFL Week <W> inactives` and WebFetch the CBS Sports or NFL.com live inactives tracker if one comes
  up (one page covers every game); fill any team it lacks with that team's own site (`<Team> inactives week
  <W>`, e.g. neworleanssaints.com/news/...inactives...), ESPN or Yahoo. Use a list only if the source names it
  as the official inactive list for this game.
- Write `gameday.json`:
  `{"updated": "<ISO time>", "teams": {"<code>": {"inactive": ["Full Name", ...], "src": "<site>"}}}` with every
  inactive player the source lists (all positions are fine; names as the source gives them), and team codes
  as in `games.csv` (LA, JAX, WAS ...). Include a team only when you found its list; an empty list means you
  found it and nobody notable is inactive. Teams not in the file stay as the injury report has them.
- A list that isn't up yet (sources lag a few minutes): look again after the CBS pages (step 3); if it's still
  missing, leave that team out, and its Questionable players keep their chance to play. With no game due
  (a catch-up run), skip this step and write no `gameday.json`.

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
for the week, skip it and say so in the report. If you wrote `gameday.json` (step 2), also copy it next to the
archived inputs: `cp gameday.json ../data/inputs/<S>/w<WW>/<tag>/` (the freeze creates that folder).

## 7. Save
- From the repo root: `git add -A data` then commit ("Week N: <weekday> pre-kickoff refresh (<tag>)") and push.
  If the push is rejected, `git pull --rebase` and push again.
- **Check it landed:** `git fetch origin main` and compare `git rev-parse HEAD` with `git rev-parse origin/main`.
  If they differ, push once more; if they still differ, put the exact error at the top of the report.
- Project doc `claude/injury_news.json` ← `work/injury_news.json` (Projects tool, `project_write` with `local_path`).

## 8. Report (a few lines)
When it published (and whether that was before kickoff), the teams whose inactives were included and any
notable inactive or newly ruled-out fantasy starters, Questionable starters still open, and anything that failed.

## Special game days
The recurring tasks cover Thursday night (6:52 pm ET), Sunday mornings with an international game (8:07 am,
skipped in other weeks) and Sunday 1 pm (11:37 am). Any other game day (Thanksgiving's daytime games, Black
Friday, Christmas, late-season Saturdays, a Wednesday game) gets a one-time scheduled task, created by the weekly
run (`runbooks/weekly.md` step 10b) when it doesn't exist yet:
- time: the day's first kickoff minus 83 minutes, America/New_York (`run_once_at` in UTC);
- name: `Fantasy Trader pre-kickoff refresh (<Weekday> <Mon> <D>)`;
- tag: `late-<3-letter weekday>`, but `late-thu-am` for a Thursday daytime game (the Thursday night run keeps
  `late-thu`);
- prompt (fill in the `<...>`):

> Run the Fantasy Trader pre-kickoff refresh for <Weekday> <Mon> <D>'s games (<away at home, kickoff ET; ...>):
> right after the first game's inactives (about <kickoff − 90 min> ET), fold the latest injury reports and the
> inactives into the page, republish it before the <first kickoff> ET kickoff, and freeze that version as a
> pre-kickoff snapshot.
>
> Page: https://claude.ai/artifact/QYtsAKr3WaL59s1xWMcw1C · Repo: github.com/AC-codemaster/fantasy-trader (private)
>
> 1. Download https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv (curl) and check that a
>    game still kicks off today within the next 3 hours (games get flexed or moved); if not, stop with a
>    one-line report.
> 2. Call add_repo with owner "AC-codemaster", repo "fantasy-trader", access "push". Clone it (git clone
>    https://github.com/AC-codemaster/fantasy-trader; generous timeout) and cd into it.
> 3. Read runbooks/gameday.md and follow it exactly. The snapshot tag is <tag>.
>
> Deadline: publish by <first kickoff − 15 min> ET. If you're running late, skip the optional steps and
> publish; a page published after kickoff still helps the later games, so publish late rather than not at all
> and say so.
>
> Rules: no grading, no improvement loop, no parameter changes. Never publish partial or obviously wrong data;
> tests must pass before publishing. Never edit frozen weeks or archived inputs and never pass --force. Don't
> touch the page's saved leagues or capabilities. If there's no Tuesday freeze for the week, still publish the
> page and skip only the freeze. If the repo can't be attached or a push is refused, report it plainly with the
> exact error; after pushing, check that origin/main equals your commit. Finish with a few lines: when it
> published, the inactives included, notable ruled-out fantasy starters, and anything that failed.
