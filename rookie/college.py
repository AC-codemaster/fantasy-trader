"""College production from cfbfastR-data play-level player stats (sportsdataverse, GitHub raw).

    player_stats/csv/player_stats_<season>.csv  (2014 on): one row per play with the players involved.

Aggregated per player-season: games, receptions, receiving yards/TDs, carries, rushing yards/TDs, pass
attempts/yards/TDs/interceptions, and the same team totals, for market shares (share of team receiving
yards and TDs, dominator rating, rushing share). Targets are not usable (recorded on ~20% of incompletions).

Data quirks handled here: on some completions the passer and receiver columns are swapped, so each play's
passer is the name with more passer-only appearances (incompletions, interceptions thrown) for that
team-season. The `team` column is not always the offense; a player's team is his most frequent one.
"""
import os
import re

import numpy as np
import pandas as pd

RAW = "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/player_stats/csv/player_stats_{y}.csv"
FIRST_SEASON = 2014
USE = ["game_id", "season", "team", "reception_player_id", "reception_player", "reception_yds", "completion_player_id",
       "completion_player", "rush_player_id", "rush_player", "rush_yds", "touchdown_player", "incompletion_player_id",
       "incompletion_player", "interception_thrown_player_id", "interception_thrown_player"]


def norm_name(s):
    s = str(s).lower().replace("’", "'")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def season_file(folder, y):
    return os.path.join(folder, f"ps_{y}.csv")


def aggregate(path):
    d = pd.read_csv(path, low_memory=False, usecols=lambda c: c in USE)
    for c in ("reception_player_id", "completion_player_id", "rush_player_id", "incompletion_player_id", "interception_thrown_player_id"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    y = int(d.season.iloc[0])
    # passer-only appearances per (team, player id)
    pr = pd.concat([d[["team", "incompletion_player_id"]].rename(columns={"incompletion_player_id": "pid"}),
                    d[["team", "interception_thrown_player_id"]].rename(columns={"interception_thrown_player_id": "pid"})]).dropna()
    prole = pr.groupby(["team", "pid"]).size().to_dict()
    names = {}
    for idc, nc in (("reception_player_id", "reception_player"), ("completion_player_id", "completion_player"),
                    ("rush_player_id", "rush_player"), ("incompletion_player_id", "incompletion_player"),
                    ("interception_thrown_player_id", "interception_thrown_player")):
        x = d[[idc, nc]].dropna().drop_duplicates(idc)
        names.update(dict(zip(x[idc].astype(int), x[nc])))
    rows = []
    c = d[d.reception_player_id.notna() & d.completion_player_id.notna()]
    for r in c.itertuples(index=False):
        a, b = int(r.reception_player_id), int(r.completion_player_id)
        ra, rb = prole.get((r.team, a), 0), prole.get((r.team, b), 0)
        passer, rec = (a, b) if ra > rb else (b, a)
        td = r.touchdown_player if isinstance(r.touchdown_player, str) else None
        is_td = td is not None and norm_name(td) in (norm_name(names.get(a, "")), norm_name(names.get(b, "")))
        yd = r.reception_yds if pd.notna(r.reception_yds) else 0.0
        rows.append((r.game_id, r.team, rec, "rec", 1, yd, int(is_td)))
        rows.append((r.game_id, r.team, passer, "cmp", 1, yd, int(is_td)))
    for r in d[d.incompletion_player_id.notna()].itertuples(index=False):
        rows.append((r.game_id, r.team, int(r.incompletion_player_id), "inc", 1, 0.0, 0))
    for r in d[d.interception_thrown_player_id.notna()].itertuples(index=False):
        rows.append((r.game_id, r.team, int(r.interception_thrown_player_id), "int", 1, 0.0, 0))
    for r in d[d.rush_player_id.notna()].itertuples(index=False):
        td = r.touchdown_player if isinstance(r.touchdown_player, str) else None
        is_td = td is not None and norm_name(td) == norm_name(r.rush_player)
        rows.append((r.game_id, r.team, int(r.rush_player_id), "rush", 1, r.rush_yds if pd.notna(r.rush_yds) else 0.0, int(is_td)))
    E = pd.DataFrame(rows, columns=["game_id", "team", "pid", "kind", "n", "yds", "td"])
    P = E.pivot_table(index="pid", columns="kind", values=["n", "yds", "td"], aggfunc="sum", fill_value=0)
    P.columns = [f"{k}_{v}" for v, k in P.columns]
    for k in ("rec", "cmp", "inc", "int", "rush"):
        for v in ("n", "yds", "td"):
            if f"{k}_{v}" not in P.columns:
                P[f"{k}_{v}"] = 0
    out = pd.DataFrame(index=P.index)
    out["rec"], out["rec_yds"], out["rec_td"] = P.rec_n, P.rec_yds, P.rec_td
    out["rush"], out["rush_yds"], out["rush_td"] = P.rush_n, P.rush_yds, P.rush_td
    out["pass_cmp"] = P.cmp_n
    out["pass_att"] = P.cmp_n + P.inc_n + P.int_n
    out["pass_yds"], out["pass_td"], out["pass_int"] = P.cmp_yds, P.cmp_td, P.int_n
    out["games"] = E.groupby("pid").game_id.nunique()
    out["team"] = E.groupby(["pid", "team"]).size().reset_index().sort_values(0).groupby("pid").team.last()
    out["name"] = pd.Series(names)
    out["season"] = y
    # team totals (each player counted for his own team)
    T = out.groupby("team")[["rec", "rec_yds", "rec_td", "rush", "rush_yds", "rush_td", "pass_att", "pass_yds", "pass_td"]].sum()
    T.columns = ["tm_" + c for c in T.columns]
    T["tm_games"] = E.groupby("team").game_id.nunique()
    out = out.join(T, on="team")
    out.index.name = "cfb_id"
    return out.reset_index()


def build(folder, seasons):
    parts = []
    for y in seasons:
        p = season_file(folder, y)
        if os.path.exists(p):
            parts.append(aggregate(p))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


ALIAS = {"southern california": "usc", "mississippi": "ole miss", "miami fl": "miami", "miami (fl)": "miami",
         "louisiana state": "lsu", "central florida": "ucf", "brigham young": "byu", "texas christian": "tcu",
         "southern methodist": "smu", "alabama birmingham": "uab", "nevada las vegas": "unlv", "texas el paso": "utep",
         "texas san antonio": "utsa", "middle tennessee state": "middle tennessee", "florida international": "fiu",
         "boston col": "boston college", "pittsburgh": "pittsburgh", "louisiana lafayette": "louisiana",
         "louisiana monroe": "ul monroe", "north carolina state": "nc state", "miami oh": "miami (oh)",
         "hawaii": "hawai'i", "san jose state": "san josé state", "appalachian state": "app state"}


def norm_school(s):
    s = str(s).lower().replace(".", "").replace("&", "and")
    s = re.sub(r"\bst\b", "state", s)
    s = re.sub(r"\bcol\b", "college", s)
    s = re.sub(r"[()]", "", s).strip()
    return ALIAS.get(s, s)


def school_score(a, b):
    a, b = norm_school(a), norm_school(b)
    if a == b:
        return 2.0
    ta, tb = set(re.findall(r"[a-z']+", a)), set(re.findall(r"[a-z']+", b))
    return len(ta & tb) / max(1, len(ta | tb))


def match(draft, C):
    """Map drafted players (season = draft year, name, college, position) to their final college season and
    their career rows. Returns {draft index: (final row, career frame)}."""
    C = C.assign(nk=C.name.map(norm_name))
    by_name = {k: g for k, g in C.groupby("nk")}
    out = {}
    for i, r in draft.iterrows():
        g = by_name.get(norm_name(r.pfr_player_name))
        if g is None:
            continue
        g = g[(g.season < r.season) & (g.season >= r.season - 6)]
        if not len(g):
            continue
        sc = g.team.map(lambda t: school_score(t, r.college))
        prod = g.rec_yds + g.rush_yds + g.pass_yds / 3
        g = g.assign(sc=sc, prod=prod)
        # same person = same cfb id; pick the id whose seasons best match the school and recency
        best = None
        for cid, h in g.groupby("cfb_id"):
            s = (h.sc.max() >= 0.5) * 10 + (h.season.max() == r.season - 1) * 2 + np.log1p(h["prod"].sum()) / 10
            if best is None or s > best[0]:
                best = (s, cid, h)
        if best is None:
            continue
        s, cid, h = best
        if h.sc.max() < 0.5 and len(g.cfb_id.unique()) > 1:
            continue   # ambiguous name and no school match
        h = h.sort_values("season")
        out[i] = (h.iloc[-1], h)
    return out
