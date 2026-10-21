# Fantasy Trader — model notes

The full design notes for the projection model, market view, trade-market pricing, acceptance, injuries,
FAAB, manager profiles and track record (Oct 1–8, 2026) are in the claude.ai project doc
`claude/fantasy-trader-model.md`. Repo-era changes (parameters file, archived inputs, hindsight and
rest-of-season grading, the improvement loop) are in `docs/improvement-loop.md`; every parameter change
since is in `ledger/changelog.md`.

Start/sit (weekly points distributions, chance to win, floor vs ceiling, chance he plays, pre-kickoff refreshes):
`docs/start-sit.md` (Oct 17, 2026).

Kickers and team defenses (projections from the Vegas lines and their histories, scoring, start/sit simulation,
trade values, grading and tuning): `docs/kdst.md` (Oct 19, 2026).

Waivers (the best pickups for one team: value on projection against the drop, upside from past free agents like him,
week weights from your title chances, how long you can hold a stash, FAAB bids): `docs/waivers.md` (Oct 20, 2026).
