# Fantasy Trader — trade autopsy (each January, after the fantasy season)

Purpose: for every trade in the user's ESPN league this season, compare what the model said at the time
(the engine and data archived for that week) with what each side actually gained over the rest of the
season, and re-grade the acceptance model on trades that happened. Tool: `tools/trade_autopsy.py` (with
`tools/autopsy_runner.js`). Results go to `docs/trade-autopsy-<S>.md` and `data/autopsy/<S>.csv`. This
changes nothing in the model; it's evidence for later decisions about the market/acceptance side (which has
no automatic tuning).

League: ESPN 1989275344 ("Goon squad"), private (the ESPN API answers 401 without the user's login).
Repo: github.com/AC-codemaster/fantasy-trader (private). Page: https://claude.ai/artifact/QYtsAKr3WaL59s1xWMcw1C.
S = the season that just ended.

1. `add_repo` owner `AC-codemaster`, repo `fantasy-trader`, access `push`; clone it, `cd` into it,
   `git checkout -b trade-autopsy-<S>`, `mkdir -p work && cd work`.
2. Data: `python3 ../pipeline/build_db.py --fetch` (games.csv and the season's weekly stats `s<yy>.csv`
   are what the autopsy needs; a failed build after the downloads is fine).
3. Trades. First look in the page's database: `ArtifactData` list on the page URL, collection `leagues`,
   doc `espn-1989275344`. Save the doc as `saved_league.json` (it carries the user's settings and manager
   styles; pass it with `--saved`). If the doc (or another doc in `leagues`) has a trade log (a `trades` or
   `transactions` field), write it as `{"trades": [...]}` in the normalized format described at the top of
   `tools/trade_autopsy.py` and use `--trades` plus an ESPN league JSON for rosters if one is available.
   As of Oct 2026 the page does not log trades, so normally:
4. Ask the user (SendUserMessage, and a push notification if the run is unattended) to open, while signed in
   to ESPN, and paste or upload the JSON of:
   `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<S>/segments/0/leagues/1989275344?view=mSettings&view=mTeam&view=mRoster&view=mTransactions2`
   and, if that shows few transactions, the same link with `&scoringPeriodId=N` for each week N with a trade
   (ESPN may return only one period's transactions per call). Then stop: the run ends here until they reply.
   When they do (in this session or a new one), save the files and continue.
5. Run: `python3 ../tools/trade_autopsy.py --espn league.json [--espn week files...] --saved saved_league.json --season <S> --out ../docs/trade-autopsy-<S>.md`.
   Rows marked "(after the trade)" used the first archived week after the trade (no archive at the trade
   date, e.g. before Week 5 2026); kickers and defenses are in the data from the Week 7 2026 archive on (Oct 20), so
   one traded before that shows as unmatched; "rollback misses" means transactions were missing, so the rosters at the
   trade are approximate. Records at the trade date are not in the data, so managers are judged without
   their win/loss mood.
6. Read the report and add a short "What it says" section at the top of the doc in plain language: did the
   side the model favored gain more; were the misses injuries (check the players' games played) or
   valuation; was acceptance plausible for trades that happened (and declined proposals, if any).
7. `python3 ../tests/run_tests.py` from the repo root must pass (the autopsy changes no model files). Commit
   on the branch ("Trade autopsy <S>"), merge into main, push. Mirror the doc to project doc
   `claude/trade-autopsy-<S>.md`.
8. Next year: create a one-time scheduled task for <S+1>-01-12 ~10:00 America/New_York with the same
   prompt (list scheduled tasks first; don't duplicate).
9. Report: number of trades, how often the model's favored side won, the biggest misses, the acceptance
   check, and whether anything couldn't be evaluated.
