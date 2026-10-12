"""Trade autopsy: every trade in a league this season, what the model said at the time vs what happened.

    cd work && python3 ../tools/trade_autopsy.py --espn league.json [--espn tx_w01.json ...] \
        [--saved saved_league.json] [--season 2026] [--out ../docs/trade-autopsy-2026.md]

Inputs
  --espn   ESPN league JSON from lm-api-reads (views mSettings, mTeam, mRoster, mTransactions2). Several files
           can be given (e.g. one mTransactions2 page per scoring period); every "transactions" array found
           is merged (deduplicated by id). The file with teams + settings gives the final rosters.
  --trades alternatively a normalized file {"trades": [{"date": "2026-10-20T18:00:00Z", "a": espnTeamId,
           "b": espnTeamId, "aGives": [espn ids], "bGives": [...], "status": "executed" | "declined"}]}
           (what the page's database would hold if it logged trades).
  --saved  the page's saved league document (ArtifactData, collection "leagues", doc "espn-<id>").

For each trade (a = the proposing team when known):
  - week: the first week whose games start after the trade; the engine and data are the archived inputs of
    that week (data/inputs/<S>/wWW/, the newest one at or before it; flagged when only a later one exists);
  - rosters just before the trade: the final rosters with every later executed transaction undone;
  - predicted: the engine's real change for each side (lineup-aware, rest of season, per week), the acceptance
    chance it gave, and the plain points of the players each side received minus sent (projection × availability);
  - actual: the same players' points in the league's scoring over the same weeks (nflverse weekly stats).
Acceptance: executed trades are 1, declined proposals 0 (when the data has them): mean predicted chance,
Brier score and the share of executed trades the model gave under 20%.
Writes the markdown report (--out) and data/autopsy/<S>.csv.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCORE_COLS = {"passYd": "passing_yards", "passTd": "passing_tds", "int": "passing_interceptions", "rushYd": "rushing_yards",
              "rushTd": "rushing_tds", "rec": "receptions", "recYd": "receiving_yards", "recTd": "receiving_tds"}
EXECUTED = ("EXECUTED",)
DECLINED = ("DECLINED", "REJECTED")


def find_key(o, key, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key and isinstance(v, list):
                out.extend(v)
            else:
                find_key(v, key, out)
    elif isinstance(o, list):
        for v in o:
            find_key(v, key, out)
    return out


def load_espn(paths):
    base, tx = None, {}
    for p in paths:
        j = json.load(open(p))
        j0 = j[0] if isinstance(j, list) else j
        if isinstance(j0, dict) and j0.get("teams") and j0.get("settings"):
            base = j0
        for t in find_key(j, "transactions", []):
            if isinstance(t, dict) and t.get("id") is not None:
                tx[t["id"]] = t
    return base, sorted(tx.values(), key=lambda t: t.get("processDate") or t.get("proposedDate") or 0)


def trades_from_espn(tx):
    """Executed trades and declined proposals from mTransactions2 records."""
    out, used = [], set()
    for t in tx:
        items = [i for i in t.get("items") or [] if i.get("type") == "TRADE"]
        if not items:
            continue
        status = str(t.get("status", "")).upper()
        kind = str(t.get("type", "")).upper()
        if status in EXECUTED and kind in ("TRADE_ACCEPT", "TRADE_UPHOLD", "TRADE_PROPOSAL", "TRADE"):
            rel = t.get("relatedTransactionId")
            key = rel or t["id"]
            if key in used:
                continue
            used.add(key)
            teams = []
            for i in items:
                for x in (i.get("fromTeamId"), i.get("toTeamId")):
                    if x and x not in teams:
                        teams.append(x)
            prop = next((x.get("teamId") for x in tx if x.get("id") == rel), None) or t.get("teamId") or teams[0]
            a = prop if prop in teams else teams[0]
            b = next(x for x in teams if x != a)
            out.append({"id": t["id"], "ms": t.get("processDate") or t.get("proposedDate"), "a": a, "b": b, "status": "executed",
                        "aGives": [i["playerId"] for i in items if i.get("fromTeamId") == a],
                        "bGives": [i["playerId"] for i in items if i.get("fromTeamId") == b]})
        elif status in DECLINED and kind == "TRADE_PROPOSAL":
            a = t.get("teamId") or items[0].get("fromTeamId")
            b = next((x for i in items for x in (i.get("fromTeamId"), i.get("toTeamId")) if x and x != a), None)
            out.append({"id": t["id"], "ms": t.get("proposedDate") or t.get("processDate"), "a": a, "b": b, "status": "declined",
                        "aGives": [i["playerId"] for i in items if i.get("fromTeamId") == a],
                        "bGives": [i["playerId"] for i in items if i.get("fromTeamId") == b]})
    return out


def rollback(base, tx, before_ms):
    """ESPN league JSON with rosters as they were before time before_ms (later executed moves undone)."""
    j = json.loads(json.dumps(base))
    ro = {t["id"]: [str(e.get("playerId") or (e.get("playerPoolEntry") or {}).get("id")) for e in (t.get("roster") or {}).get("entries", [])]
          for t in j["teams"]}
    misses = 0
    for t in sorted(tx, key=lambda x: -(x.get("processDate") or 0)):
        if str(t.get("status", "")).upper() not in EXECUTED or (t.get("processDate") or 0) < before_ms:
            continue
        for i in t.get("items") or []:
            pid = str(i.get("playerId"))
            f, to = i.get("fromTeamId") or 0, i.get("toTeamId") or 0
            if f == to:
                continue   # lineup moves
            if to in ro:
                if pid in ro[to]:
                    ro[to].remove(pid)
                else:
                    misses += 1
            if f in ro and pid not in ro[f]:
                ro[f].append(pid)
    for t in j["teams"]:
        t["roster"] = {"entries": [{"playerId": int(p) if p.isdigit() else p} for p in ro[t["id"]]]}
    return j, misses


def week_of(ms, games, S):
    g = games[(games.season == S) & (games.game_type == "REG")]
    day = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    starts = g.groupby("week").gameday.min()
    later = [int(w) for w, d in starts.items() if str(d) > day]
    return min(later) if later else int(g.week.max()) + 1


def archived(S, W):
    d = os.path.join(ROOT, "data", "inputs", str(S))
    have = sorted(int(x[1:]) for x in os.listdir(d) if x.startswith("w") and x[1:].isdigit()) if os.path.isdir(d) else []
    before = [w for w in have if w <= W]
    if before:
        return before[-1], False
    after = [w for w in have if w > W]
    return (after[0], True) if after else (None, None)


def points(st, scoring, ids, weeks):
    sc = {k: float(scoring.get(k, 0) or 0) for k in SCORE_COLS}
    fum = float(scoring.get("fumble", 0) or 0)
    two = float(scoring.get("twoPt", 0) or 0)
    d = st[st.player_id.isin(ids) & st.week.isin(weeks)]
    if not len(d):
        return 0.0, {}
    p = sum(d[c].fillna(0) * sc[k] for k, c in SCORE_COLS.items())
    p = p + fum * d[["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]].fillna(0).sum(axis=1)
    p = p + two * d[["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"]].fillna(0).sum(axis=1)
    by = p.groupby(d.player_id).sum()
    return float(by.sum()), by.round(1).to_dict()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--espn", action="append", default=[])
    ap.add_argument("--trades", default=None)
    ap.add_argument("--saved", default=None)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    S = a.season
    base, tx = load_espn(a.espn) if a.espn else (None, [])
    if base is None:
        sys.exit("need an ESPN league JSON with teams and settings (views mSettings, mTeam, mRoster)")
    if a.trades:
        T = []
        for t in json.load(open(a.trades))["trades"]:
            ms = int(pd.Timestamp(t["date"]).timestamp() * 1000)
            T.append({"id": t.get("id", ms), "ms": ms, "a": t["a"], "b": t["b"], "aGives": t["aGives"], "bGives": t["bGives"],
                      "status": t.get("status", "executed")})
    else:
        T = trades_from_espn(tx)
    games = pd.read_csv("games.csv", low_memory=False)
    st = pd.read_csv(f"s{str(S)[2:]}.csv", low_memory=False)
    st = st[st.season_type == "REG"]
    names = {}
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for t in T:
            W = week_of(t["ms"], games, S)
            aw, late = archived(S, W)
            if aw is None:
                rows.append({**t, "week": W, "error": "no archived inputs for this season"})
                continue
            inp = os.path.join(ROOT, "data", "inputs", str(S), f"w{aw:02d}")
            j, misses = rollback(base, tx, t["ms"])
            ep, tp = os.path.join(td, "espn.json"), os.path.join(td, "trade.json")
            json.dump(j, open(ep, "w"))
            json.dump({"a": t["a"], "b": t["b"], "aGives": t["aGives"], "bGives": t["bGives"]}, open(tp, "w"))
            cmd = ["node", os.path.join(HERE, "autopsy_runner.js"), "--engine", os.path.join(inp, "engine.js"),
                   "--db", os.path.join(inp, "db.json"), "--espn", ep, "--trade", tp] + (["--saved", a.saved] if a.saved else [])
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                rows.append({**t, "week": W, "error": r.stderr.strip().splitlines()[-1] if r.stderr else "engine failed"})
                continue
            o = json.loads(r.stdout)
            db = json.load(open(os.path.join(inp, "db.json")))
            names.update({p["id"]: p["n"] for p in db["players"]})
            cur = int(o["curWeek"])
            last = min(int(o.get("lastWeek") or 17), 17)
            weeks = list(range(max(W, cur), last + 1))

            def proj(ids_):
                tot = 0.0
                for i in ids_:
                    v = o["players"].get(i)
                    if not v:
                        continue
                    for k, w in enumerate(range(cur, cur + len(v["weekly"]))):
                        if w in weeks:
                            tot += v["weekly"][k] * v["avail"][k]
                return tot
            n = max(1, len(weeks))
            pa_get, pa_give = proj(o["get"]), proj(o["give"])
            aa_get, by1 = points(st, o["scoring"], o["get"], weeks)
            aa_give, by2 = points(st, o["scoring"], o["give"], weeks)
            done_weeks = sorted(set(st.week.astype(int)) & set(weeks))
            rows.append({**t, "week": W, "inputs": f"w{aw:02d}" + (" (after the trade)" if late else ""), "weeks": f"{weeks[0]}–{weeks[-1]}" if weeks else "",
                         "weeks_played": len(done_weeks), "rollback_misses": misses,
                         "a_gets": ", ".join(names.get(i, i) for i in o["get"]), "b_gets": ", ".join(names.get(i, i) for i in o["give"]),
                         "pred_A_real_pw": o["perWeekA"], "pred_B_real_pw": o["perWeekB"], "accept": o["accept"],
                         "pred_A_pts_pw": (pa_get - pa_give) / n, "act_A_pts_pw": (aa_get - aa_give) / max(1, len(done_weeks)),
                         "pred_B_pts_pw": (pa_give - pa_get) / n, "act_B_pts_pw": (aa_give - aa_get) / max(1, len(done_weeks)),
                         "unmatched": len(o["unmatched"])})
    R = pd.DataFrame(rows)
    os.makedirs(os.path.join(ROOT, "data", "autopsy"), exist_ok=True)
    R.to_csv(os.path.join(ROOT, "data", "autopsy", f"{S}.csv"), index=False)
    ex = R[(R.status == "executed") & R.get("accept", pd.Series(dtype=float)).notna()] if "accept" in R else R.iloc[0:0]
    lines = [f"# Trade autopsy, {S}", "", f"League {base.get('id')} ({(base.get('settings') or {}).get('name', '')}). "
             f"{int((R.status == 'executed').sum())} executed trades, {int((R.status == 'declined').sum())} declined proposals in the data. "
             "Predicted = the engine and data archived at the trade week (rosters rolled back to the trade); actual = the "
             "same players' points in the league's scoring over the rest of the fantasy season. Per week; A = proposer.", ""]
    if len(ex):
        lines += ["| week | A gets | B gets | model: A real change /wk | B /wk | acceptance | A pts/wk predicted | actual | B pts/wk predicted | actual | inputs |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in ex.iterrows():
            lines.append(f"| {r.week} | {r.a_gets} | {r.b_gets} | {r.pred_A_real_pw:+.2f} | {r.pred_B_real_pw:+.2f} | {r.accept:.0%} | "
                         f"{r.pred_A_pts_pw:+.2f} | {r.act_A_pts_pw:+.2f} | {r.pred_B_pts_pw:+.2f} | {r.act_B_pts_pw:+.2f} | {r.inputs} |")
        hit = (np.sign(ex.pred_A_pts_pw) == np.sign(ex.act_A_pts_pw)).mean()
        lines += ["", f"- The model picked the side that gained more player points in {hit:.0%} of executed trades; "
                  f"mean absolute miss {(ex.pred_A_pts_pw - ex.act_A_pts_pw).abs().mean():.2f} pts/week per side.",
                  f"- Acceptance on executed trades: mean predicted chance {ex.accept.mean():.0%}; {(ex.accept < 0.2).mean():.0%} were given under 20%."]
        dec = R[(R.status == "declined") & R.get("accept", pd.Series(dtype=float)).notna()] if "accept" in R else R.iloc[0:0]
        if len(dec):
            y = np.r_[np.ones(len(ex)), np.zeros(len(dec))]
            p = np.r_[ex.accept.values, dec.accept.values]
            lines.append(f"- With {len(dec)} declined proposals: Brier score {np.mean((p - y) ** 2):.3f} "
                         f"(always guessing the base rate: {np.mean((y.mean() - y) ** 2):.3f}); mean chance on declined {dec.accept.mean():.0%}.")
        else:
            lines.append("- No declined proposals in the data, so acceptance can only be checked on trades that happened.")
        if (ex.rollback_misses > 0).any():
            lines.append("- Some rosters could not be rolled back exactly (transactions missing from the data): treat those rows with care.")
    err = R[R.get("error", pd.Series(dtype=object)).notna()] if "error" in R else R.iloc[0:0]
    if len(err):
        lines += ["", "Not evaluated: " + "; ".join(f"week {r.week}: {r.error}" for _, r in err.iterrows())]
    if not len(R):
        lines.append("No trades found in the data.")
    text = "\n".join(lines) + "\n"
    if a.out:
        open(a.out, "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
