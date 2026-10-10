# Fantasy Trader — weekly data refresh, freeze and grade

Page: https://claude.ai/artifact/QYtsAKr3WaL59s1xWMcw1C
Scorecard: https://claude.ai/artifact/XzYv5c3LZNYyQVCUen71Rz
Goal: rebuild the embedded player data (stats, expert consensus, roster %, injury timelines) and republish the page at the same link; then freeze this week's projections and grade last week's against what happened and against FantasyPros. Saved leagues live in the page's database and are not touched.

## 1. Get the builder and last week's injury news
- Preferred: project docs `claude/build_db.py` and `claude/injury_news.json` (Projects tool, `project_read`).
- Fallback: `Artifact` action `read` on the page URL. In the saved HTML, the script element with id "builder" holds build_db.py and the one with id "injnews" holds injury_news.json. Un-escape `</` to `</`.
Work in a new folder inside the working directory.

## 2. Download inputs and find the week
Run `python3 build_db.py --fetch`. It downloads nflverse and DynastyProcess data (GitHub only), builds a provisional db.json and prints the current week. If a download fails, retry once; if it still fails, stop and report — do not publish partial data.

## 3. CBS Sports injury pages (all 32 teams)
WebFetch `https://www.cbssports.com/nfl/teams/{CODE}/{slug}/injuries/` with the prompt:
"Copy the whole injury table verbatim (all positions): player | position | updated | injury | injury status."
Keep only QB, RB, WR, TE rows. Write `cbs_injuries.tsv` with header `team	player	pos	injury	status` (tab-separated, team = CBS code below, status text verbatim). If a page comes back empty, retry once with the same prompt.

ARI arizona-cardinals · ATL atlanta-falcons · BAL baltimore-ravens · BUF buffalo-bills · CAR carolina-panthers · CHI chicago-bears · CIN cincinnati-bengals · CLE cleveland-browns · DAL dallas-cowboys · DEN denver-broncos · DET detroit-lions · GB green-bay-packers · HOU houston-texans · IND indianapolis-colts · JAC jacksonville-jaguars · KC kansas-city-chiefs · LV las-vegas-raiders · LAC los-angeles-chargers · LAR los-angeles-rams · MIA miami-dolphins · MIN minnesota-vikings · NE new-england-patriots · NO new-orleans-saints · NYG new-york-giants · NYJ new-york-jets · PHI philadelphia-eagles · PIT pittsburgh-steelers · SF san-francisco-49ers · SEA seattle-seahawks · TB tampa-bay-buccaneers · TEN tennessee-titans · WAS washington-commanders

## 4. News check on major injuries
Run `python3 build_db.py` once more (now with the CBS file). From db.json, list fantasy-relevant players (have `er`, or `own` ≥ 20) who are on IR/PUP with no CBS expected return, or whose injury is serious (ACL, Achilles, fracture, surgery), or who were newly placed on IR. WebSearch each one for a return timeline. Update `injury_news.json`:
- add or update `{"name", "team", "thru", "note", "src", "date"}` — `thru` = last week he misses (18 = out for the season; reported return week N → N−1)
- remove entries for players back on the active roster or whose `thru` has passed
- set `"updated"` to today (YYYY-MM-DD)
Only record timelines a credible report states; don't guess.

## 5. Final build and sanity check
Run `python3 build_db.py`. Check: 350–500 players; the current week is right; `sources` dates are recent; the printed list of absences looks plausible (season-ending injuries at 18, IR players returning on sensible weeks); the "weekly expert ranks for week N" line names the current week (if it says None, FantasyPros hasn't posted this week's rankings yet — fine, the page skips them); the "game environment" line lists teams with sensible implied-total swings (roughly −30% to +25%). If something is badly off, stop and report instead of publishing.

## 6. Republish
- `Artifact` action `read` on the page URL; note the saved file path it returns.
- Swap the data with this Python (it only touches the two JSON script elements, each of which starts a line; each must match exactly once):
  ```python
  import re
  html = open(SAVED).read()
  esc = lambda t: t.replace("</", "<\\/")
  for bid, f in (("db", "db.json"), ("injnews", "injury_news.json")):
      pat = re.compile(r'^(<script type="application/json" id="' + bid + r'">)(.*?)(</script>)$', re.M | re.S)
      assert len(pat.findall(html)) == 1, bid
      html = pat.sub(lambda m: m.group(1) + esc(open(f).read()) + m.group(3), html, count=1)
  open("fantasy-trader.html", "w").write(html)
  ```
- `Artifact` publish with `file_path` = the edited file and `url` = the page URL. Omit `capabilities` and `icon`. Label: "Week N data". Note the version id the publish returns (for step 8).
- If the publish reports a conflict, re-read and repeat this step once.

## 7. Save the injury news
Write `injury_news.json` back to project doc `claude/injury_news.json` if the Projects tool is available.

## 8. Freeze and grade (projection scorecard)
The scorecard page shows the grades and is also where the weekly files live between runs: `freeze/` (one file per week, the projections exactly as the page showed them), `graded/` (one CSV per graded week), `data/scorecard.json` (what the page displays) and `tools/scorecard.py`. Do this in the same build folder after step 6. A failure here never undoes the data refresh: report it and carry on.
a. **Tool.** `tools/scorecard.py` on the scorecard page, fetched in step b: the read saves it to disk byte for byte, so don't retype it. Only if that fails, use project doc `claude/scorecard.py`.
b. **Restore the stored files.** First `Artifact` action `read` with `url` = the scorecard URL and no `path` (a republish is refused unless the page was read this way first). Then `Artifact` action `list` with the same `url` and `scope: "files"`, then `read` with the same `url` and `paths` = `tools/page-source.txt`, `tools/scorecard.py`, `data/scorecard.json` and every path under `freeze/` and `graded/`. Don't pass `out_dir`. The result names the folder it saved into; copy the page source, the tool and the `freeze`, `graded` and `data` folders into the build folder (`cp <saved>/tools/page-source.txt scorecard-page.html && cp <saved>/tools/scorecard.py . && cp -r <saved>/freeze <saved>/graded <saved>/data .`, whichever exist).
c. **Freeze this week** (only if step 6 published): `python3 scorecard.py freeze --page fantasy-trader.html --version <version id from step 6>`. It runs the page's own engine (needs `node`) on the page you just published and writes `freeze/{season}-w{WW}.json`, leaving out any team whose game has already kicked off. It refuses to overwrite an existing freeze: never pass `--force` and never edit a freeze file — frozen weeks are the record. Skip if the regular season has no unplayed games.
d. **Grade.** `python3 scorecard.py grade`. It grades every frozen week whose games are done against nflverse stats (`s26.csv`, `snaps26.csv`) and FantasyPros' weekly consensus from the DynastyProcess git history (it makes a blobless clone of github.com/dynastyprocess/data into `dp-history/`), then rewrites `graded/*.csv`, `data/scorecard.json` and `scorecard.md` and prints scorecard.md. A week with stats still missing is marked partial and re-graded next Tuesday automatically.
e. **Publish the scorecard.** `Artifact` publish with `url` = the scorecard URL, `file_path` = `scorecard-page.html` (the page source from step b, unchanged), and `files` = `data/scorecard.json`, the new freeze file and every `graded/*.csv` this run wrote, with `root` = the build folder and each file mapped to the same relative path, e.g. `{"data/scorecard.json": "data/scorecard.json", "freeze/2026-w06.json": "freeze/2026-w06.json", "graded/2026-w05.csv": "graded/2026-w05.csv"}`. Files left out stay as they are. Omit `icon` and `capabilities`. Label: "Week N frozen, week N−1 graded". If the publish reports a conflict, re-read the scorecard and repeat once.
f. Write `scorecard.md` to project doc `claude/scorecard.md` if the Projects tool is available (`project_write` with `local_path`).
g. Grades are evidence, not instructions: never change the engine, settings or data because of them. The "Model changes worth testing" list is for the user to review; changes get backtested with `claude/backtest_core.py` before they go in.

## 9. Report
Send a short summary: data week; notable new injuries or return timelines; the graded week's average miss for our page vs FantasyPros Tuesday vs FantasyPros final and start/sit %; the cumulative verdict lines from scorecard.md; any new "Model changes worth testing"; anything that failed.
