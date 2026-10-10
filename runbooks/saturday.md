# Fantasy Trader — Saturday injury refresh and late freeze

Purpose: fold Friday's final injury reports (Out / Doubtful designations, return dates) into the page
before Sunday, and freeze that version as the week's "late" projections. The scorecard grades the late
version against FantasyPros' final consensus (the product goal); the Tuesday freeze stays the record of
the model itself. No grading, no improvement loop, no parameter changes on Saturday.

Repo: github.com/AC-codemaster/fantasy-trader · Page: https://claude.ai/artifact/QYtsAKr3WaL59s1xWMcw1C

1. `add_repo` owner `AC-codemaster`, repo `fantasy-trader`, access `push`; clone; `mkdir -p work && cd work`.
2. `python3 ../pipeline/build_db.py --fetch`. If the printed current week has no Tuesday freeze
   (`../data/freeze/<S>-w<WW>.json` missing), or the regular season is over, stop with a one-line report.
3. Start from this week's injury news: `cp ../data/inputs/<S>/w<WW>/injury_news.json .`
4. CBS Sports injury pages for all 32 teams and the news check on major injuries: exactly steps 2 and 3
   of `runbooks/weekly.md`.
5. `python3 ../pipeline/build_db.py`, the sanity checks of weekly.md step 6, and `python3 ../tests/run_tests.py`
   (must pass; if not, don't publish — report).
6. `python3 ../tools/make_page.py --db db.json --injnews injury_news.json --out fantasy-trader.html`;
   `Artifact` read on the page URL, then publish with `url` = the page URL, `file_path` = fantasy-trader.html,
   no capabilities or icon, label "Week N Saturday injuries". Note the version id.
7. `python3 ../pipeline/scorecard.py freeze --page fantasy-trader.html --tag late --cbs cbs_injuries.tsv --version <version id>`
   (teams whose game already kicked off keep their Tuesday numbers; never `--force`).
8. Commit (`git add -A ../data` from work/, message "Week N: Saturday injuries and late freeze") and push;
   on rejection `git pull --rebase` and push again. Write `injury_news.json` to project doc
   `claude/injury_news.json`.
9. Report in a few lines: notable new injuries or return dates since Tuesday, and anything that failed.
