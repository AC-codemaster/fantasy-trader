"""Build the embedded player database for Fantasy Trader.

Usage:  python3 build_db.py --fetch     # download fresh inputs, then build db.json
        python3 build_db.py             # build from inputs already in this folder

Inputs (downloaded with --fetch):
  nflverse:  stats_player_week_{2024,2025,2026}.csv, roster_weekly_2026.csv,
             injuries_2026.csv, games.csv
  DynastyProcess (FantasyPros consensus): db_fpecr_latest.csv, fp_latest_weekly.csv,
             db_playerids.csv, db_fpecr.parquet (preseason draft ranks)
Inputs gathered by Claude each week (see the refresh runbook):
  cbs_injuries.tsv   team, player, pos, injury, status  (CBS Sports team injury pages)
  injury_news.json   news-confirmed timelines, e.g. season-ending injuries
  gameday.json       game-day inactives, gathered by the Thursday and Sunday pre-kickoff runs (runbooks/gameday.md):
                     {"updated": ISO time, "teams": {"JAX": {"inactive": ["Full Name", ...], "src": "..."}, ...}};
                     a team listed has posted its inactives: everyone else on it is active this week

Per player, the database stores per-game scoring components (scored in the page, so
league settings change every number):
  a -> usage model: volume blended across seasons, efficiency & TD rates shrunk toward
       positional league rates (regression to the mean)
  s -> 2026 season-to-date average;  f -> form, last two games played
crowd signals:
  er/es -> FantasyPros rest-of-season consensus positional rank / std dev
  dr/dp -> FantasyPros preseason draft consensus overall / positional rank (ADP stand-in)
  own   -> roster % (average across platforms)
injury timeline:
  ij = {thru, st, inj, why, src, upd}  thru = last week he is expected to miss (18 = season)
  lg    -> last 2026 week he played (stats or offensive snaps): the engine discounts a first game back
  ew    -> FantasyPros weekly position rank for the current week (DB.ewWeek says which week)
  gs/pr -> this week's game status (Questionable / Doubtful / Out) and last practice (Full / Limited / DNP);
           gd = "active" / "inactive" once his team's game-day inactives are out (start/sit chance he plays)
per team: env = {week: [x, spread, implied]} game environment from Vegas lines (current week) or
  projected from market power ratings (later weeks); x = implied total vs the team's usual, minus 1
this week: opp = {team: opponent}, kick = {team: kickoff, ISO with offset}

Backtested formula settings (2024 fit, 2025-26 holdout): share fit weights recent games by DECAY per
week; efficiency for thin samples shrinks toward low-volume players' rates, not the league average.
"""
import json
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kdst  # noqa: E402  kickers and team defenses (shared with the backtest and the scorecard)

POS = ["QB", "RB", "WR", "TE"]
SEASON = 2026


def _load_params():
    """Tuned constants from params/params.json (the improvement loop changes them). Looked up in
    $FT_PARAMS, ./params.json, then ../params/params.json next to this script; built-in defaults otherwise."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.environ.get("FT_PARAMS"), "params.json", os.path.join(here, "..", "params", "params.json")):
        if path and os.path.exists(path):
            j = json.load(open(path))
            return {k: v["value"] for k, v in j["params"].items()}, j.get("version"), path
    return {}, None, None


PRM, PARAMS_VERSION, PARAMS_PATH = _load_params()


def _load_annual():
    """Yearly-refitted constants from params/annual.json (runbooks/annual-refit.md): $FT_ANNUAL, ./annual.json,
    ../params/annual.json next to this script; the built-in values below otherwise (= annual.json version 1)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.environ.get("FT_ANNUAL"), "annual.json", os.path.join(here, "..", "params", "annual.json")):
        if path and os.path.exists(path):
            return json.load(open(path))
    return {}


ANNUAL = _load_annual()


def prm(key, default):
    return float(PRM.get(key, default))

OLD_W = 0.5  # weight on 2025 counting stats in the efficiency history
NV = "https://github.com/nflverse/nflverse-data/releases/download"
DP_DIR = "dynastyprocess-data"


def sh(cmd):
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def fetch():
    for y in (2024, 2025, SEASON):
        sh(f"curl -sSLf -o s{str(y)[2:]}.csv {NV}/stats_player/stats_player_week_{y}.csv")
    sh(f"curl -sSLf -o r26.csv {NV}/weekly_rosters/roster_weekly_{SEASON}.csv")
    for y in (2024, 2025):
        if not os.path.exists(f"r{str(y)[2:]}.csv"):
            sh(f"curl -sSLf -o r{str(y)[2:]}.csv {NV}/weekly_rosters/roster_weekly_{y}.csv")
    sh(f"curl -sSLf -o inj26.csv {NV}/injuries/injuries_{SEASON}.csv")
    sh(f"curl -sSLf -o snaps26.csv {NV}/snap_counts/snap_counts_{SEASON}.csv")
    sh(f"curl -sSLf -o dc26.csv {NV}/depth_charts/depth_charts_{SEASON}.csv")
    sh("curl -sSLf -o games.csv https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv")
    if os.path.isdir(os.path.join(DP_DIR, ".git")):
        sh(f"git -C {DP_DIR} fetch --depth 1 origin && git -C {DP_DIR} reset --hard FETCH_HEAD")
    else:
        sh(f"GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/dynastyprocess/data {DP_DIR}")
    for f in ("db_fpecr_latest.csv", "fp_latest_weekly.csv", "db_playerids.csv"):
        sh(f"cp {DP_DIR}/files/{f} .")
    # parquet support: newer pyarrow releases break pandas' parquet reader, so check in a child process
    # and fall back to a compatible pyarrow (installed before this process imports it)
    chk = f"import pandas as pd; pd.read_parquet('{DP_DIR}/files/db_fpecr.parquet', columns=['scrape_date'])"
    if subprocess.run([sys.executable, "-c", chk], capture_output=True).returncode != 0:
        sh('pip install -q --break-system-packages "pyarrow<21"')
    if not os.path.exists("fp_preseason.csv"):
        e = pd.read_parquet(f"{DP_DIR}/files/db_fpecr.parquet")
        e["scrape_date"] = e.scrape_date.astype(str)
        c = e[(e.fp_page == "/nfl/rankings/ppr-cheatsheets.php") & (e.scrape_date < f"{SEASON}-09-08") & (e.scrape_date >= f"{SEASON}-07-01")]
        c = c[c.scrape_date == c.scrape_date.max()]
        c.to_csv("fp_preseason.csv", index=False)


if "--fetch" in sys.argv:
    fetch()

# ---------------- schedule: current week, byes, week dates ----------------
g = pd.read_csv("games.csv", low_memory=False)
g = g[(g.season == SEASON) & (g.game_type == "REG")]
LAST_WEEK = int(g.week.max())
unplayed = g[g.home_score.isna()]
CUR_WEEK = int(unplayed.week.min()) if len(unplayed) else LAST_WEEK + 1
DONE_WEEK = CUR_WEEK - 1
last_game_day = str(g[g.week == DONE_WEEK].gameday.max()) if DONE_WEEK >= 1 else ""
teams = sorted(set(g.home_team) | set(g.away_team))
byes = {}
team_weeks = {}
for tm in teams:
    played = set(int(w) for w in g[(g.home_team == tm) | (g.away_team == tm)].week)
    team_weeks[tm] = sorted(played)
    byes[tm] = [w for w in range(1, LAST_WEEK + 1) if w not in played]
week_dates = {int(w): str(d) for w, d in g.groupby("week").gameday.min().items()}

# ---------------- stats ----------------
frames, RAW = {}, {}
for key, f in (("24", "s24.csv"), ("25", "s25.csv"), ("26", "s26.csv")):
    d = pd.read_csv(f, low_memory=False)
    RAW[2000 + int(key)] = d          # every position: kickers and team defenses come from here (pipeline/kdst.py)
    d = d[(d.season_type == "REG") & d.position.isin(POS)].copy()
    d["fl"] = d[["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]].fillna(0).sum(axis=1)
    d["two"] = d[["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"]].fillna(0).sum(axis=1)
    frames[key] = d
s24, s25, s26 = frames["24"], frames["25"], frames["26"]

COLS = ["attempts", "passing_yards", "passing_tds", "passing_interceptions", "carries", "rushing_yards",
        "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds", "fl", "two"]


def season_totals(d):
    t = d.groupby("player_id")[COLS].sum()
    t["g"] = d.groupby("player_id").size()
    t["ts"] = d.groupby("player_id").target_share.mean()
    return t


t24, t25, t26 = season_totals(s24), season_totals(s25), season_totals(s26)

# form: each player's last two games played
recent = s26.sort_values("week").groupby("player_id").tail(2)
last2 = recent.groupby("player_id")[COLS].sum()
last2["g"] = recent.groupby("player_id").size()

# positional league rates (all seasons pooled) — the priors we shrink toward
lg = pd.concat([s24, s25, s26]).groupby("position")[COLS].sum()


def rate(num, den, pos):
    return lg.loc[pos, num] / max(lg.loc[pos, den], 1)


# Shrinkage strengths, in opportunities. Bigger = noisier stat = more regression.
K = {k_: prm("K_" + k_, v_) for k_, v_ in {"ypa": 150, "ptd": 250, "int": 300, "ypc": 100, "rtd": 150, "cr": 40, "ypt": 60, "rectd": 120}.items()}

# Players with little history regress toward what low-volume players produce, not the league average
# (backup QBs: 6.4 yards/attempt and a 2.9% TD rate vs 7.3 and 4.8% for starters). The target moves
# from the low-volume rate to the league rate as his weighted opportunities approach AFULL.
LOWCUT = {"QB": ("attempts", 150), "RB": ("carries", 40), "WR": ("targets", 25), "TE": ("targets", 20), "RB_rec": ("targets", 15)}
AFULL0 = {"QB": 300, "RB": 100, "WR": 60, "TE": 45, "RB_rec": 40}
if "low_volume" in ANNUAL:
    LOWCUT = {k_: tuple(v_) for k_, v_ in ANNUAL["low_volume"]["lowcut"].items()}
    AFULL0 = dict(ANNUAL["low_volume"]["afull"])
AFULL = {k_: v_ * prm("low_target", 2.0) for k_, v_ in AFULL0.items()}  # 2.0 → 600/200/120/90/80
_seas = pd.concat([s24.groupby(["player_id", "position"])[COLS].sum().reset_index(),
                   s25.groupby(["player_id", "position"])[COLS].sum().reset_index()])
lg_low = {}
for key_, (col_, cut_) in LOWCUT.items():
    pos_ = "RB" if key_ == "RB_rec" else key_
    lg_low[key_] = _seas[(_seas.position == pos_) & (_seas[col_] > 0) & (_seas[col_] <= cut_)][COLS].sum()

# ---------------- crowd signals (FantasyPros via DynastyProcess) ----------------
idmap = pd.read_csv("db_playerids.csv", low_memory=False)[["fantasypros_id", "gsis_id", "espn_id"]]
fp2g = idmap.dropna(subset=["fantasypros_id", "gsis_id"]).drop_duplicates("fantasypros_id").set_index("fantasypros_id").gsis_id.to_dict()
g2espn = idmap.dropna(subset=["gsis_id", "espn_id"]).drop_duplicates("gsis_id").set_index("gsis_id").espn_id.to_dict()

ecr = pd.read_csv("db_fpecr_latest.csv", low_memory=False)
ros = ecr[ecr.page_type.isin(["redraft-qb", "redraft-rb", "redraft-wr", "redraft-te", "redraft-k", "redraft-dst"])].copy()
ROS_DATE = str(ros[ros.pos.isin(POS)].scrape_date.max())
ros["gsis"] = ros.id.map(fp2g)
ros["prank"] = ros.groupby("page_type").ecr.rank(method="first")
ros_by = ros.dropna(subset=["gsis"]).drop_duplicates("gsis").set_index("gsis")
ROS_N = {k: int(v) for k, v in ros.groupby("pos").size().items()}
# cross-positional price: rest-of-season PPR overall consensus (how the market ranks a QB against an RB; it
# lists the top kickers and defenses too, far down)
ovr = ecr[(ecr.page_type == "redraft-overall") & ecr.pos.isin(POS + ["K", "DST"])].copy()
ovr["gsis"] = ovr.id.map(fp2g)
ovr_by = ovr.dropna(subset=["gsis"]).drop_duplicates("gsis").set_index("gsis").ecr.to_dict()

pre = pd.read_csv("fp_preseason.csv", low_memory=False)
PRE_DATE = str(pre.scrape_date.max())
pre = pre[pre.pos.isin(POS + ["K", "DST"])].copy()
pre["gsis"] = pre.id.map(fp2g)
pre["orank"] = pre.ecr.rank(method="first")
pre["prank"] = pre.groupby("pos").ecr.rank(method="first")
pre_by = pre.dropna(subset=["gsis"]).drop_duplicates("gsis").set_index("gsis")

wk = pd.read_csv("fp_latest_weekly.csv", low_memory=False)
WK_DATE = str(wk.scrape_date.max())
wk["gsis"] = wk.fantasypros_id.map(fp2g)
own_by = wk.dropna(subset=["gsis", "player_owned_avg"]).drop_duplicates("gsis").set_index("gsis").player_owned_avg.to_dict()

# Team defenses have no player id at FantasyPros: they're matched by team (FantasyPros writes JAC and LAR).
FP_TEAM = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}
DST_ID = lambda team: "DST-" + team  # noqa: E731
for _d in (ros, ovr, pre, wk):
    _m = _d.pos == "DST"
    if _m.any():
        _d.loc[_m, "gsis"] = _d.loc[_m, "team"].map(lambda t: DST_ID(FP_TEAM.get(str(t), str(t))))
ros_by = ros.dropna(subset=["gsis"]).drop_duplicates("gsis").set_index("gsis")
ovr_by = ovr.dropna(subset=["gsis"]).drop_duplicates("gsis").set_index("gsis").ecr.to_dict()
pre_by = pre.dropna(subset=["gsis"]).drop_duplicates("gsis").set_index("gsis")
own_by = wk.dropna(subset=["gsis", "player_owned_avg"]).drop_duplicates("gsis").set_index("gsis").player_owned_avg.to_dict()


def week_of_day(day):
    ws = [w_ for w_, d_ in week_dates.items() if d_ <= day]
    return max(ws) if ws else None


# FantasyPros weekly rankings: position rank for the week they were made for (kept only if that's
# the current week). Backtested: blending them into this week's projection at 50% cut misses.
wkr = wk[wk.pos.isin(POS + ["K", "DST"])].dropna(subset=["gsis", "ecr"]).copy()
wkr["day"] = pd.to_datetime(wkr.player_game_kickoff_ts, unit="s", errors="coerce").dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
wk_weeks = wkr.day.dropna().map(week_of_day).dropna()
EW_WEEK = int(wk_weeks.mode().iloc[0]) if len(wk_weeks) else None
EW_WEEK = EW_WEEK if EW_WEEK == CUR_WEEK else None
wkr["prank"] = wkr.groupby("pos").ecr.rank(method="first")
ew_by = wkr.drop_duplicates("gsis").set_index("gsis").prank.to_dict() if EW_WEEK else {}

# last week each player played this season (any stat, or offensive snaps)
last_played = s26.groupby("player_id").week.max().to_dict()
if os.path.exists("snaps26.csv"):
    _ids = pd.read_csv("db_playerids.csv", low_memory=False, usecols=["pfr_id", "gsis_id"]).dropna()
    _pfr = _ids.drop_duplicates("pfr_id").set_index("pfr_id").gsis_id.to_dict()
    _sn = pd.read_csv("snaps26.csv", low_memory=False)
    _sn = _sn[(_sn.offense_snaps > 0) & (_sn.game_type == "REG")].assign(g=lambda d: d.pfr_player_id.map(_pfr)).dropna(subset=["g"])
    for pid_, w_ in _sn.groupby("g").week.max().items():
        last_played[pid_] = max(int(w_), int(last_played.get(pid_, 0)))

# ---------------- rosters and injury timelines ----------------
rw = pd.read_csv("r26.csv", low_memory=False)
# Each team's newest weekly roster. A team on bye has no rows in the week it sits out, so taking the file's last
# week alone dropped every player on the teams on bye (the Oct 13 page had no CAR or KC players, Oct 18 no CIN,
# DET, MIA or MIN). A player who changed teams since keeps his newest row.
_tw = rw.groupby("team").week.transform("max")
ROSTER = rw[rw.week == _tw].sort_values("week").drop_duplicates("gsis_id", keep="last")
r = ROSTER[ROSTER.position.isin(POS) & ~ROSTER.status.isin(["CUT", "RET"])]
r = r.set_index("gsis_id")

# first week of each player's current reserve stint (IR, PUP, NFI...)
res_start = {}
for pid, h in rw[rw.position.isin(POS + ["K"])].sort_values("week").groupby("gsis_id"):
    st = list(zip(h.week.astype(int), h.status))
    if not st or st[-1][1] != "RES":
        continue
    w0 = st[-1][0]
    for w, s in reversed(st):
        if s != "RES":
            break
        w0 = w
    res_start[pid] = w0

inj = pd.read_csv("inj26.csv", low_memory=False)
rep_wk = int(inj[inj.report_status.notna()].week.max())
rep = inj[(inj.week == rep_wk) & inj.report_status.notna()].drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
prac_wk = int(inj.week.max())
prac = inj[(inj.week == prac_wk) & inj.practice_status.notna()].drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
PR = {"Did Not Participate In Practice": "DNP", "Limited Participation in Practice": "Limited"}

CBS_TEAM = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}


def norm(s):
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", str(s).lower())
    return re.sub(r"[^a-z]", "", s)


def name_key(name):
    """('j', 'mason') from 'J. Mason' or 'Jordan Mason'."""
    parts = str(name).replace(".", ". ").split()
    if len(parts) < 2:
        return ("", norm(name))
    return (parts[0][0].lower(), norm(" ".join(parts[1:])))


cbs = {}
if os.path.exists("cbs_injuries.tsv"):
    c = pd.read_csv("cbs_injuries.tsv", sep="\t", dtype=str).fillna("")
    for _, row in c.iterrows():
        cbs[(CBS_TEAM.get(row.team, row.team), row.pos) + name_key(row.player)] = row
# game-day inactives (Thursday / Sunday pre-kickoff runs): teams listed have posted theirs
GAMEDAY, GAMEDAY_AT = {}, ""
if os.path.exists("gameday.json"):
    _gd = json.load(open("gameday.json"))
    GAMEDAY_AT = _gd.get("updated", "")
    for _t, _v in (_gd.get("teams") or {}).items():
        GAMEDAY[CBS_TEAM.get(_t, _t)] = {name_key(x) for x in _v.get("inactive", [])}
news = {}
NEWS_DATE = ""
if os.path.exists("injury_news.json"):
    nj = json.load(open("injury_news.json"))
    NEWS_DATE = nj.get("updated", "")
    for x in nj.get("players", []):
        news[(x["team"], norm(x["name"]))] = x


def nth_game_week(team, start, n):
    """Week of the team's n-th game counting from week `start` (byes don't count)."""
    ws = [w for w in team_weeks.get(team, []) if w >= start]
    return ws[n - 1] if len(ws) >= n else 18


def timeline(pid, ro):
    """Expected absence: the last week he misses (or None) and how we know."""
    team, pos, full = ro.team, ro.position, ro.full_name
    row = cbs.get((team, pos) + name_key(full))
    nw = news.get((team, norm(full)))
    injury, label = "", ""
    cands = []
    floor = None
    if pid in res_start:
        floor = (nth_game_week(team, res_start[pid], 4), f"on reserve since week {res_start[pid]}, so he must miss at least 4 games", "NFL IR rule")
        label = "IR"
    if row is not None:
        status, injury = row.status, row.injury
        is_res = bool(re.match(r"(IR|Physically Unable|NFI)", status))
        m = re.search(r"Expected Return - Week (\d+)", status)
        if m:
            cands.append((int(m.group(1)) - 1, f"expected back week {m.group(1)}", "CBS Sports"))
        m = re.search(r"Out for Week (\d+)", status)
        if m:
            cands.append((int(m.group(1)), f"ruled out for week {m.group(1)}", "CBS Sports"))
            label = label or "Out"
        m = re.search(r"Doubtful for Week (\d+)", status)
        if m:
            cands.append((int(m.group(1)), f"doubtful for week {m.group(1)}", "CBS Sports"))
            label = label or "Doubtful"
        if "Questionable for Week" in status and not label:
            label = "Questionable"
        if is_res:
            label = "IR" if status.startswith("IR") else ("PUP" if "Physically" in status else "NFI")
            if "Expected Return" not in status and re.search(r"ACL|Achilles", injury):
                cands.append((18, f"{injury}, no return timeline", "CBS Sports"))
    # the NFL's own injury report for this week (nflverse): Out and Doubtful mean he misses this week's game,
    # Questionable is a label (the start/sit chance he plays). Catches what the CBS pages don't have yet.
    gs_rep = str(rep.loc[pid].report_status) if pid in rep.index and rep_wk == CUR_WEEK else ""
    if gs_rep in ("Out", "Doubtful"):
        cands.append((CUR_WEEK, f"{gs_rep.lower()} for week {CUR_WEEK} on the NFL injury report", "NFL injury report"))
        if not label or label == "Questionable":
            label = gs_rep
    elif gs_rep == "Questionable" and not label:
        label = "Questionable"
    if floor:
        cands.append(floor)  # after CBS, so CBS wins ties
    if nw:
        cands = [(int(nw["thru"]), nw["note"], nw["src"])]
        if not label or label in ("Questionable", "Doubtful"):
            label = "Out"
    thru, why, src = (max(cands, key=lambda x: x[0]) if cands else (None, "", ""))
    if thru is not None and thru < CUR_WEEK:
        thru, why, src = None, "", ""
        if label in ("IR", "PUP", "NFI"):
            label = ""
    if thru is not None and thru >= 18:
        label, thru = "Out for season", 18
    elif thru is not None and label in ("IR", "PUP", "NFI"):
        # back from a reserve list but on this week's report: the report is the news
        label = gs_rep if src == "NFL injury report" else f"{label} · back wk {thru + 1}"
    if not label:
        if gs_rep == "Questionable":       # e.g. back from a reserve list and listed this week
            label = "Questionable"
        elif pid in prac.index and prac.loc[pid].practice_status in PR:
            label = f"{PR[prac.loc[pid].practice_status]} practice"
        elif pid in rep.index and rep_wk >= CUR_WEEK:
            label = str(rep.loc[pid].report_status)
    if ro.status == "EXE" and thru is None:
        thru, label, why, src = 18, "Exempt list", "on the commissioner's exempt list; no return timeline", "NFL transactions"
    # game day: his team's inactives are out. Inactive = out this week; anyone else on the team is active, which
    # settles a Questionable, Doubtful or Out tag for this week (not a reserve-list absence: those aren't listed)
    if team in GAMEDAY and ro.status not in ("RES", "EXE"):
        if name_key(full) in GAMEDAY[team]:
            if thru is None or thru < CUR_WEEK:
                thru, why, src = CUR_WEEK, "inactive for this week's game", "game-day inactives"
            label = label if label.startswith(("IR", "PUP", "NFI", "Out for season")) else "Inactive"
        elif thru == CUR_WEEK and label in ("Out", "Doubtful", "Questionable", ""):
            thru, why, src, label = None, "", "", f"Active (was {label})" if label else "Active"
        elif thru is None and label in ("Questionable", "Doubtful", "Out") or label.endswith("practice"):
            label = f"Active (was {label})"
    if not label and thru is None:
        return None
    return {"thru": thru, "st": label, "inj": injury, "why": why, "src": src,
            "upd": nw.get("date", NEWS_DATE) if nw else ""}


def week_status(pid, ro):
    """This week's game status and last practice (start/sit chance he plays), and game-day active/inactive."""
    team, pos, full = ro.team, ro.position, ro.full_name
    out = {}
    row = cbs.get((team, pos) + name_key(full))
    m = re.search(r"(Questionable|Doubtful|Out) for Week (\d+)", row.status) if row is not None else None
    if m and int(m.group(2)) == CUR_WEEK:
        out["gs"] = m.group(1)
    elif pid in rep.index and rep_wk == CUR_WEEK and str(rep.loc[pid].report_status) in ("Questionable", "Doubtful", "Out"):
        out["gs"] = str(rep.loc[pid].report_status)
    if pid in prac.index and prac_wk == CUR_WEEK:
        pr = {"Full Participation in Practice": "Full", "Limited Participation in Practice": "Limited",
              "Did Not Participate In Practice": "DNP"}.get(str(prac.loc[pid].practice_status))
        if pr:
            out["pr"] = pr
    if team in GAMEDAY and ro.status not in ("RES", "EXE"):
        out["gd"] = "inactive" if name_key(full) in GAMEDAY[team] else "active"
    return out


# ---------------- aging ----------------
# Expected change in per-game production from one season to the next, by age in the new season.
# Approximate positional aging curves; used to adjust last year's data before it is blended in.
YOY = {
    "RB": [(24, 1.04), (25, 1.01), (26, 0.98), (27, 0.95), (28, 0.91), (29, 0.88), (99, 0.85)],
    "WR": [(23, 1.08), (24, 1.05), (25, 1.03), (26, 1.01), (27, 1.00), (28, 0.98), (29, 0.96), (30, 0.93), (31, 0.90), (99, 0.87)],
    "TE": [(24, 1.10), (25, 1.06), (26, 1.03), (27, 1.01), (28, 1.00), (29, 0.97), (30, 0.94), (31, 0.91), (99, 0.88)],
    "QB": [(25, 1.05), (26, 1.03), (27, 1.01), (32, 1.00), (33, 0.98), (34, 0.96), (35, 0.94), (36, 0.92), (99, 0.89)],
}
if "yoy" in ANNUAL:   # refitted yearly (params/annual.json); the table above is version 1
    YOY = {k_: [tuple(x_) for x_ in v_] for k_, v_ in ANNUAL["yoy"].items()}
VET_AGE = {"RB": 28, "WR": 30, "TE": 30, "QB": 35}   # from here on, last year's data counts less
VET_PRIOR = prm("vet_prior", 0.6)
SEASON_START = pd.Timestamp(f"{SEASON}-09-01")


def yoy(pos, age):
    if age is None:
        return 1.0
    for a, f in YOY[pos]:
        if age <= a:
            return f
    return 1.0


ages = {}
for pid, bd in rw.dropna(subset=["birth_date"]).drop_duplicates("gsis_id", keep="last").set_index("gsis_id").birth_date.items():
    try:
        ages[pid] = int((SEASON_START - pd.Timestamp(bd)).days // 365.25)
    except Exception:
        pass

# ---------------- team-share usage model ----------------
# Each player gets a weight u for three pools of team work: non-QB carries ("r"), targets ("t")
# and QB pass attempts ("p"). In any game, a pool is split among the players who are active in
# proportion to u (a Luce / Bradley-Terry share model). The weights are fitted to 2026 games,
# using who was actually active in each game, with last season as a prior. Future weeks then
# re-split the pool among whoever is healthy that week.
POOLS = {"r": ("carries", ["RB", "WR", "TE"]), "t": ("targets", ["RB", "WR", "TE"]), "p": ("attempts", ["QB"])}
PRIOR_GAMES = prm("prior_games", 3.0)          # last season counts like 3 games of this season...
PRIOR_GAMES_MOVED = prm("prior_moved", 1.5)    # ...or 1.5 if he changed teams
TEAM_PRIOR_GAMES = prm("team_prior", 3.0)     # team volume shrinks toward league average by 3 games
DECAY = prm("decay", 0.9)                # each older week counts 10% less in this season's share fit (tuned)

latest = ROSTER
cur_team = latest.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
status_by = {(row.gsis_id, int(row.week)): (row.team, row.status) for row in rw.itertuples()}


def last_team(df):
    if df is None or not len(df):
        return {}
    return df.sort_values("week").groupby("player_id").team.agg(lambda s: s.iloc[-1]).to_dict()


team25, team24 = last_team(s25), last_team(s24)

g26_games = s26.groupby(["team", "week"]).size().reset_index()[["team", "week"]]
pool_game = {}
for c, (col, poss) in POOLS.items():
    pool_game[c] = s26[s26.position.isin(poss)].groupby(["team", "week"])[col].sum()
lg_pool = {c: float(pool_game[c].mean()) for c in POOLS}
team_pool = {}
for tm in teams:
    team_pool[tm] = {}
    for c in POOLS:
        vals = pool_game[c][tm] if tm in pool_game[c].index.get_level_values(0) else pd.Series(dtype=float)
        team_pool[tm][c] = float((vals.sum() + TEAM_PRIOR_GAMES * lg_pool[c]) / (len(vals) + TEAM_PRIOR_GAMES))

opp_cols = {"r": "carries", "t": "targets", "p": "attempts"}
by_game = s26.set_index(["player_id", "week"])


def fit_luce(stats, status_map, tm, col, poss, cur=(), u0=None, n=None, decay=1.0):
    """Fit share weights for one team pool from game logs.
    stats: player-game rows; status_map: (pid, week) -> (team, status) from weekly rosters.
    Returns (u, present_games, team_games, expected_denominator)."""
    u0, n = u0 or {}, n or {}
    rows = stats[(stats.team == tm) & stats.position.isin(poss)]
    games = sorted(set(int(w) for w in stats[stats.team == tm].week))
    cnt = {(pid, int(w)): float(v) for (pid, w), v in rows.groupby(["player_id", "week"])[col].sum().items()}
    here = set(rows.player_id) | set(cur)
    present, C = {}, {}
    for w in games:
        P = set()
        for pid in here:
            st = status_map.get((pid, w))
            if (pid, w) in cnt or (st and st[0] == tm and st[1] == "ACT"):
                P.add(pid)
        # a starter hurt early in a game and moved to reserve right after: treat as absent
        for pid in list(P):
            nxt = status_map.get((pid, w + 1))
            others = [cnt[(pid, x)] for x in games if x != w and (pid, x) in cnt]
            if nxt and nxt[1] == "RES" and others and cnt.get((pid, w), 0) < 0.4 * np.mean(others):
                P.discard(pid)
        present[w] = P
        C[w] = sum(cnt.get((pid, w), 0.0) for pid in P)
    tot = sum(C.values()) or 1.0
    last = max(games) if games else 0
    wt = {w: decay ** (last - w) for w in games}
    u = {pid: max(u0.get(pid, 0.0), sum(v for (q, w), v in cnt.items() if q == pid) / tot, 1e-3) for pid in here}
    for _ in range(300):
        D = {w: sum(u[k] for k in present[w]) for w in games}
        new = {}
        for pid in here:
            num = sum(wt[w] * cnt.get((pid, w), 0.0) for w in games if pid in present[w]) + n.get(pid, 0.0) * u0.get(pid, 0.0)
            den = sum(wt[w] * C[w] / D[w] for w in games if pid in present[w] and D[w] > 0) + n.get(pid, 0.0)
            new[pid] = num / den if den > 0 else 0.0
        u = new
    pg = {pid: sum(1 for w in games if pid in present[w]) for pid in here}
    ed = sum(u[k] * pg[k] for k in here) / max(len(games), 1)
    return u, pg, len(games), ed


# Last season's shares, fitted the same way: a player's share of his team's work in a typical game
# he played. Unlike per-game averages, this doesn't inflate fill-in starters.
def season_shares(stats, rost_file):
    if stats is None or not len(stats) or not os.path.exists(rost_file):
        return {}
    rr = pd.read_csv(rost_file, low_memory=False, usecols=["gsis_id", "week", "team", "status"])
    smap = {(x.gsis_id, int(x.week)): (x.team, x.status) for x in rr.itertuples()}
    out = {}
    for tm_ in sorted(set(stats.team)):
        for c, (col, poss) in POOLS.items():
            if c == "p":
                continue
            u, pg, ng, ed = fit_luce(stats, smap, tm_, col, poss)
            for pid, v in u.items():
                if pg[pid] and ed > 0:
                    prev = out.get((c, pid))
                    if prev is None or pg[pid] > prev[1]:
                        out[(c, pid)] = (v / ed, pg[pid], tm_)
    return out


prior25 = season_shares(s25, "r25.csv")
prior24 = season_shares(s24, "r24.csv")
SEASON2_BLEND = prm("blend2", 0.5)  # weight of 2024 usage shares when 2025 already has a full sample


def prior_share(pid, pos, c):
    """Last season's typical-game share, aged, with 2024 at full weight when 2025 is thin and at
    SEASON2_BLEND weight otherwise (backtested Oct 8: small gain on 2024 and on 2025-26). None if no data."""
    age = ages.get(pid)
    f1 = yoy(pos, age)
    f2 = f1 * yoy(pos, age - 1 if age else None)
    a25, a24 = prior25.get((c, pid)), prior24.get((c, pid))
    num = den = 0.0
    if a25:
        num += a25[0] * a25[1] * np.sqrt(f1)
        den += a25[1]
    if a24 and (not a25 or a25[1] < 6):
        num += a24[0] * a24[1] * np.sqrt(f2)
        den += a24[1]
    elif a24:
        num += SEASON2_BLEND * a24[0] * a24[1] * np.sqrt(f2)
        den += SEASON2_BLEND * a24[1]
    return (num / den) if den else None


def prior_strength(pid, pos, team, c):
    a25, a24 = prior25.get((c, pid)), prior24.get((c, pid))
    if not a25 and not a24:
        return 0.0
    moved = (a25 or a24)[2] != team
    k = PRIOR_GAMES_MOVED if moved else PRIOR_GAMES
    age = ages.get(pid)
    if age is not None and age >= VET_AGE[pos]:
        k *= VET_PRIOR
    return k


# Rookie prior (data/rookie/predictions.csv, rookie/rookie_model.py): for drafted rookies, who have no NFL
# history, the rookie model's share of team carries/targets and per-opportunity efficiency from draft slot.
# ROOKIE_PRIOR weights it: shares count like ROOKIE_PRIOR x PRIOR_GAMES games; efficiency gets ROOKIE_PRIOR x
# ROOKIE_OPPS pseudo-opportunities at the predicted rates. 0 = no prior (the model before Oct 12, 2026, exactly).
# QB pass attempts keep the depth-chart prior.
ROOKIE_PRIOR = prm("rookie_prior", 0.0)
ROOKIE_OPPS = {"QB": {"attempts": 150}, "RB": {"carries": 60, "targets": 20}, "WR": {"targets": 40}, "TE": {"targets": 30}}
ROOKIES = {}
if ROOKIE_PRIOR > 0:
    _rp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "rookie", "predictions.csv")
    for _p in (os.environ.get("FT_ROOKIES"), "rookie_predictions.csv", _rp):
        if _p and os.path.exists(_p):
            _rk = pd.read_csv(_p, low_memory=False)
            ROOKIES = {r_.gsis_id: r_._asdict() for r_ in _rk[_rk.season == SEASON].itertuples(index=False)}
            break


def rookie_pseudo(pid, pos):
    """Pseudo-counts the rookie prior adds to his efficiency history ({} when off or not a rookie)."""
    rk = ROOKIES.get(pid)
    if ROOKIE_PRIOR <= 0 or rk is None:
        return {}
    n = {k_: ROOKIE_PRIOR * v_ for k_, v_ in ROOKIE_OPPS.get(pos, {}).items()}
    out = {}
    if pos == "QB":
        a_ = n.get("attempts", 0.0)
        qc_ = a_ * rk["cpa"]
        out = {"attempts": a_, "passing_yards": a_ * rk["ypa"], "passing_tds": a_ * rk["ptd"], "passing_interceptions": a_ * rk["ipa"],
               "carries": qc_, "rushing_yards": qc_ * rk["ypc"], "rushing_tds": qc_ * rk["rtd"]}
    else:
        c_, t_ = n.get("carries", 0.0), n.get("targets", 0.0)
        out = {"carries": c_, "rushing_yards": c_ * rk["ypc"], "rushing_tds": c_ * rk["rtd"], "targets": t_,
               "receptions": t_ * rk["cr"], "receiving_yards": t_ * rk["ypt"], "receiving_tds": t_ * rk["rctd"]}
    opp = out.get("carries", 0.0) + out.get("targets", 0.0) + (out.get("attempts", 0.0) if pos == "QB" else 0.0)
    lg_opp_ = (lg.loc[pos, "attempts"] + lg.loc[pos, "carries"]) if pos == "QB" else (lg.loc[pos, "carries"] + lg.loc[pos, "targets"])
    out["fl"] = opp * lg.loc[pos, "fl"] / max(lg_opp_, 1)
    out["two"] = opp * lg.loc[pos, "two"] / max(lg_opp_, 1)
    return out


# Latest ESPN depth chart (via nflverse): QB order sets the prior for who throws the passes,
# because a backup's numbers only come from games he started.
qb_depth = {}
depth_rank = {}
if os.path.exists("dc26.csv"):
    dc = pd.read_csv("dc26.csv", low_memory=False, usecols=["dt", "team", "gsis_id", "pos_abb", "pos_rank"])
    dc = dc[dc.pos_abb.isin(["QB", "RB", "WR", "TE", "PK"])]
    dc = dc[dc.dt == dc.dt.max()]
    depth_rank = {(r_.team, r_.gsis_id): int(r_.pos_rank) for r_ in dc.itertuples() if isinstance(r_.gsis_id, str)}
    qbs = set(dc[dc.pos_abb == "QB"].gsis_id)
    qb_depth = {k: v for k, v in depth_rank.items() if k[1] in qbs}
QB_PRIOR = {1: 0.95, 2: 0.04, 3: 0.01}
CUR_OK = ("ACT", "INA", "RES", "EXE")

U = {c: {} for c in POOLS}       # (team, pid) -> weight
for tm in teams:
    for c, (col, poss) in POOLS.items():
        cur = set(cur_team[(cur_team.team == tm) & cur_team.position.isin(poss) & cur_team.status.isin(CUR_OK)].index)
        u0, n = {}, {}
        for pid in cur:
            pos = cur_team.loc[pid].position
            if c == "p":
                rk = qb_depth.get((tm, pid))
                if rk in QB_PRIOR:
                    u0[pid], n[pid] = QB_PRIOR[rk], PRIOR_GAMES * team_pool[tm][c]
                continue
            v = prior_share(pid, pos, c)
            k = prior_strength(pid, pos, tm, c)
            if v is not None and k > 0:
                u0[pid], n[pid] = v, k * team_pool[tm][c]
            elif ROOKIE_PRIOR > 0 and pid in ROOKIES and ROOKIES[pid]["sh_" + c] > 0:
                u0[pid], n[pid] = ROOKIES[pid]["sh_" + c], ROOKIE_PRIOR * PRIOR_GAMES * team_pool[tm][c]
        tot0 = sum(u0.values())
        if tot0 > 1:
            u0 = {k_: v / tot0 for k_, v in u0.items()}
        u, _, _, _ = fit_luce(s26, status_by, tm, col, poss, cur, u0, n, decay=DECAY)
        for pid in cur:
            U[c][(tm, pid)] = u.get(pid, 0.0)

# ---------------- efficiency (per opportunity), with last year's data and aging ----------------
W25, W24 = prm("w1", 0.8), prm("w2", 0.4)        # weight of 2025 and 2024 opportunities vs this season's
K = {k_: prm("K_" + k_, v_) for k_, v_ in {"ypa": 150, "ptd": 250, "int": 300, "ypc": 100, "rtd": 150, "cr": 40, "ypt": 60, "rectd": 120,
                                           "cpa": 150, "fl": 250, "two": 400}.items()}
lgq = lg.loc["QB"]


def efficiency(pid, pos):
    a = t26.loc[pid] if pid in t26.index else None
    b = t25.loc[pid] if pid in t25.index else None
    c24 = t24.loc[pid] if pid in t24.index else None
    age = ages.get(pid)
    f1 = yoy(pos, age)
    f2 = f1 * yoy(pos, age - 1 if age else None)
    vet = VET_PRIOR if (age is not None and age >= VET_AGE[pos]) else 1.0
    scaled = {"passing_yards", "passing_tds", "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds"}
    rk_add = rookie_pseudo(pid, pos)

    def h(col, real=False):
        x = a[col] if a is not None else 0.0
        if b is not None:
            x += W25 * vet * b[col] * (np.sqrt(f1) if col in scaled else 1.0)
        if c24 is not None:
            x += W24 * vet * c24[col] * (np.sqrt(f2) if col in scaled else 1.0)
        if rk_add and not real:
            x += rk_add.get(col, 0.0)
        return x

    def sh(num, den, k, base_pos=pos, num_extra=None):
        lr = lg.loc[base_pos, num] / max(lg.loc[base_pos, den], 1)
        key = "RB_rec" if (base_pos == "RB" and den == "targets") else base_pos
        lo = lg_low.get(key)
        if lo is not None and lo[den] > 0:
            lr_low = lo[num] / lo[den]
            lr = lr_low + (lr - lr_low) * min(1.0, h(den, real=True) / AFULL[key])
        return (h(num) + k * lr) / (h(den) + k)

    def sh2(nv, dv, k, lr):
        return (nv + k * lr) / (dv + k)

    opp_skill = h("carries") + h("targets")
    lg_opp_skill = lg.loc[pos, "carries"] + lg.loc[pos, "targets"]
    if pos == "QB":
        opp = h("attempts") + h("carries")
        lg_opp = lgq["attempts"] + lgq["carries"]
        return {
            "ypa": sh("passing_yards", "attempts", K["ypa"]), "ptd": sh("passing_tds", "attempts", K["ptd"]),
            "ipa": sh("passing_interceptions", "attempts", K["int"]),
            "cpa": sh2(h("carries"), h("attempts"), K["cpa"], lgq["carries"] / lgq["attempts"]),
            "ypc": sh("rushing_yards", "carries", K["ypc"]), "rtd": sh("rushing_tds", "carries", K["rtd"]),
            "cr": 0.0, "ypt": 0.0, "rctd": 0.0,
            "fl": sh2(h("fl"), opp, K["fl"], lgq["fl"] / lg_opp), "two": sh2(h("two"), opp, K["two"], lgq["two"] / lg_opp),
        }
    return {
        "ypa": 0.0, "ptd": 0.0, "ipa": 0.0, "cpa": 0.0,
        "ypc": sh("rushing_yards", "carries", K["ypc"]), "rtd": sh("rushing_tds", "carries", K["rtd"]),
        "cr": sh("receptions", "targets", K["cr"]), "ypt": sh("receiving_yards", "targets", K["ypt"]),
        "rctd": sh("receiving_tds", "targets", K["rectd"]),
        "fl": sh2(h("fl"), opp_skill, K["fl"], lg.loc[pos, "fl"] / lg_opp_skill),
        "two": sh2(h("two"), opp_skill, K["two"], lg.loc[pos, "two"] / lg_opp_skill),
    }


def components(pos, eff, car, tgt, att):
    """Per-game scoring components from opportunities and efficiency."""
    if pos == "QB":
        qcar = att * eff["cpa"]
        opp = att + qcar
        return [att * eff["ypa"], att * eff["ptd"], att * eff["ipa"], qcar * eff["ypc"], qcar * eff["rtd"],
                0.0, 0.0, 0.0, opp * eff["fl"], opp * eff["two"]]
    opp = car + tgt
    return [0.0, 0.0, 0.0, car * eff["ypc"], car * eff["rtd"], tgt * eff["cr"], tgt * eff["ypt"], tgt * eff["rctd"],
            opp * eff["fl"], opp * eff["two"]]


# weeks around the experts' rankings date: injuries after it are news the experts hadn't priced in
ROS_WEEK = max([w for w, d in week_dates.items() if d <= ROS_DATE] or [1])

# ---------------- game environment ----------------
# A team's Vegas implied total vs its usual level moves volume, yards and TDs (fit on 2022-25 team
# games; the elasticities live in the engine). Weeks with a line use it; later weeks use market power
# ratings fitted to this season's lines (implied = mu + home + offense + opponent defense), shrunk by
# ENV_SHRINK because a rating 3+ weeks out explains only part of the eventual line (backtested 0.74).
ENV_SHRINK = prm("env_shrink", 0.74)
LINES = {}
for r_ in g[g.total_line.notna() & g.spread_line.notna()].itertuples():
    LINES[(r_.home_team, int(r_.week))] = (r_.total_line / 2 + r_.spread_line / 2, float(r_.spread_line))
    LINES[(r_.away_team, int(r_.week))] = (r_.total_line / 2 - r_.spread_line / 2, -float(r_.spread_line))
lg_imp = float(np.mean([v[0] for v in LINES.values()])) if LINES else 22.0
_tix = {t_: i for i, t_ in enumerate(teams)}
_X, _y = [], []
for r_ in g[g.total_line.notna() & g.spread_line.notna()].itertuples():
    for tm_, opp_, home_ in ((r_.home_team, r_.away_team, 1), (r_.away_team, r_.home_team, 0)):
        row_ = np.zeros(2 * len(teams) + 2)
        row_[0], row_[1], row_[2 + _tix[tm_]], row_[2 + len(teams) + _tix[opp_]] = 1, home_, 1, 1
        _X.append(row_)
        _y.append(LINES[(tm_, int(r_.week))][0])
if _X:
    _X, _y = np.array(_X), np.array(_y)
    _R = np.eye(_X.shape[1]) * 4.0
    _R[0, 0] = _R[1, 1] = 0
    _b = np.linalg.solve(_X.T @ _X + _R, _X.T @ _y)
else:
    _b = np.zeros(2 * len(teams) + 2)
    _b[0] = lg_imp


def proj_implied(tm_, opp_, home_):
    return _b[0] + _b[1] * home_ + _b[2 + _tix[tm_]] + _b[2 + len(teams) + _tix[opp_]]


ENV, USUAL = {}, {}
for tm in teams:
    prev = [LINES[(tm, w)][0] for w in range(1, CUR_WEEK) if (tm, w) in LINES]
    usual = (sum(prev) + 3 * lg_imp) / (len(prev) + 3)
    USUAL[tm] = usual
    ENV[tm] = {}
    for r_ in g[((g.home_team == tm) | (g.away_team == tm)) & (g.week >= CUR_WEEK)].itertuples():
        w = int(r_.week)
        home_ = 1 if r_.home_team == tm else 0
        opp_ = r_.away_team if home_ else r_.home_team
        if (tm, w) in LINES:
            imp, sp = LINES[(tm, w)]
            x = imp / usual - 1
        else:
            imp = proj_implied(tm, opp_, home_)
            sp = (imp - proj_implied(opp_, tm, 1 - home_)) * ENV_SHRINK
            x = (imp / usual - 1) * ENV_SHRINK
        ENV[tm][str(w)] = [round(float(x), 3), round(float(sp), 1), round(float(imp), 1)]
last_game_week = s26.groupby("player_id").week.max().to_dict()

players = []
ids = set(t26.index) | set(t25.index) | set(t24.index)
for pid in ids:
    if pid not in r.index:
        continue
    ro = r.loc[pid]
    pos, tm = ro.position, ro.team
    a = t26.loc[pid] if pid in t26.index else None
    b = t25.loc[pid] if pid in t25.index else None
    c24 = t24.loc[pid] if pid in t24.index else None
    g26 = int(a.g) if a is not None else 0
    g25 = int(b.g) if b is not None else 0
    g24 = int(c24.g) if c24 is not None else 0
    ranked = pid in ros_by.index
    if g26 == 0 and g25 < 4 and not (ranked and g25 + g24 >= 4):
        continue
    if tm not in team_pool:
        continue

    def pg(t, col):
        return t[col] / t.g if t is not None and t.g > 0 else np.nan

    ur, ut, up = U["r"].get((tm, pid), 0.0), U["t"].get((tm, pid), 0.0), U["p"].get((tm, pid), 0.0)
    eff = efficiency(pid, pos)
    comp = ["passing_yards", "passing_tds", "passing_interceptions", "rushing_yards", "rushing_tds",
            "receptions", "receiving_yards", "receiving_tds", "fl", "two"]
    l2 = last2.loc[pid] if pid in last2.index else None
    season = [pg(a, col) if a is not None else 0.0 for col in comp]
    form = [pg(l2, col) if l2 is not None else 0.0 for col in comp]

    ij = timeline(pid, ro)
    if ij and ij["thru"] is not None and ij["thru"] >= CUR_WEEK + 1 and last_game_week.get(pid, 0) >= ROS_WEEK:
        ij["nx"] = 1   # long absence that started after the experts' rankings
    espn = ro.espn_id if pd.notna(ro.espn_id) else g2espn.get(pid)
    rec = {
        "id": pid,
        "espn": int(float(espn)) if espn is not None and pd.notna(espn) else None,
        "n": ro.full_name,
        "p": pos,
        "t": tm,
        "age": ages.get(pid),
        "g26": g26,
        "g25": g25,
        "ts": round(float(a.ts), 3) if a is not None and pd.notna(a.ts) else None,
        "inj": ij["st"] if ij else "",
        "m": [round(float(x), 5) for x in (ur, ut, up, eff["ypc"], eff["rtd"], eff["cr"], eff["ypt"], eff["rctd"],
                                            eff["ypa"], eff["ptd"], eff["ipa"], eff["cpa"], eff["fl"], eff["two"])],
        "s": [round(float(x), 3) for x in np.nan_to_num(season)],
        "f": [round(float(x), 3) for x in np.nan_to_num(form)],
        "g24": g24,
    }
    # track record: per-game components in each of the last two seasons (the engine scores them)
    if g25 > 0:
        rec["s25"] = [round(float(x), 3) for x in np.nan_to_num([pg(b, col) for col in comp])]
    if g24 > 0:
        rec["s24"] = [round(float(x), 3) for x in np.nan_to_num([pg(c24, col) for col in comp])]
    if ij:
        rec["ij"] = ij
    if ranked:
        rr = ros_by.loc[pid]
        rec["er"] = int(rr.prank)
        rec["es"] = round(float(rr.sd), 2) if pd.notna(rr.sd) else None
    if pid in ovr_by and pd.notna(ovr_by[pid]):
        rec["eo"] = round(float(ovr_by[pid]), 1)
    if pid in pre_by.index:
        rec["dr"] = int(pre_by.loc[pid].orank)
        rec["dp"] = int(pre_by.loc[pid].prank)
    if pid in own_by:
        rec["own"] = round(float(own_by[pid]), 1)
    if pid in last_played:
        rec["lg"] = int(last_played[pid])
    if pid in ew_by:
        rec["ew"] = int(ew_by[pid])
    rec.update(week_status(pid, ro))
    players.append(rec)

# healthy-roster share per player (for display and filtering)
ids_in = {}
for p in players:
    ids_in.setdefault(p["t"], []).append(p)
team_out = {}
for tm in teams:
    tot = {c: sum(U[c].get((tm, pid), 0.0) for pid in cur_team[cur_team.team == tm].index
                  if cur_team.loc[pid].status in ("ACT", "INA") or pid in {q["id"] for q in ids_in.get(tm, [])}) for c in POOLS}
    in_db = {q["id"] for q in ids_in.get(tm, [])}
    other = {c: sum(U[c].get((tm, pid), 0.0) for pid in cur_team[cur_team.team == tm].index
                    if pid not in in_db and cur_team.loc[pid].status in ("ACT", "INA")) for c in POOLS}
    team_out[tm] = {"r": round(team_pool[tm]["r"], 2), "t": round(team_pool[tm]["t"], 2), "p": round(team_pool[tm]["p"], 2),
                    "or": round(other["r"], 5), "ot": round(other["t"], 5), "op": round(other["p"], 5), "env": ENV.get(tm, {})}
    for q in ids_in.get(tm, []):
        m = q["m"]
        share = {c: (m[i] / tot[c] if tot[c] > 0 else 0.0) for i, c in enumerate("rtp")}
        q["sh"] = [round(share["r"], 3), round(share["t"], 3), round(share["p"], 3)]
        q["cpg"] = round(team_pool[tm]["r"] * share["r"], 1) if q["p"] != "QB" else round(team_pool[tm]["p"] * share["p"] * m[11], 1)
        q["tpg"] = round(team_pool[tm]["t"] * share["t"], 1) if q["p"] != "QB" else None
        e = dict(zip(["ypc", "rtd", "cr", "ypt", "rctd", "ypa", "ptd", "ipa", "cpa", "fl", "two"], m[3:]))
        q["a"] = [round(float(x), 3) for x in components(q["p"], e, team_pool[tm]["r"] * share["r"],
                                                          team_pool[tm]["t"] * share["t"], team_pool[tm]["p"] * share["p"])]


# biggest weekly share each player gets over the rest of the season, given known absences
out_thru = {p["id"]: p["ij"]["thru"] for p in players if p.get("ij") and p["ij"]["thru"] is not None}
cur_status = cur_team.status.to_dict()
for tm in teams:
    roster_c = [pid for pid in cur_team[cur_team.team == tm].index if cur_status[pid] in CUR_OK]
    uw = {c: {pid: U[c].get((tm, pid), 0.0) for pid in roster_c} for c in "rtp"}
    dens = []
    for w in range(CUR_WEEK, LAST_WEEK + 1):
        if w in byes.get(tm, []):
            continue
        avail = [pid for pid in roster_c if not (out_thru.get(pid) is not None and out_thru[pid] >= w)
                 and (cur_status[pid] not in ("RES", "EXE") or pid in out_thru)]
        dens.append({c: sum(uw[c][pid] for pid in avail) for c in "rtp"})
    for q in ids_in.get(tm, []):
        best = list(q["sh"])
        for dd in dens:
            for i, c in enumerate("rtp"):
                if dd[c] > 0:
                    best[i] = max(best[i], min(1.0, q["m"][i] / dd[c]))
        q["mx"] = [round(x, 3) for x in best]
    for q in ids_in.get(tm, []):
        rk = depth_rank.get((tm, q["id"]))
        if rk:
            q["dc"] = rk


def half_ppr(v):
    return v[0] * .04 + v[1] * 4 - v[2] * 2 + v[3] * .1 + v[4] * 6 + v[5] * .5 + v[6] * .1 + v[7] * 6 - v[8] * 2 + v[9] * 2


players = [p for p in players if max(half_ppr(p["a"]), half_ppr(p["s"])) >= 2.0 or "er" in p or p.get("own", 0) >= 5
           or (p["p"] in ("RB", "QB") and max(p["sh"]) >= 0.12)
           or p["mx"][0] >= 0.3 or p["mx"][1] >= 0.12 or p["mx"][2] >= 0.5]
players.sort(key=lambda p: -half_ppr(p["a"]))
kept = {p["id"] for p in players}
# players dropped by the filter join their team's "other" bucket
for tm in teams:
    for q in ids_in.get(tm, []):
        if q["id"] not in kept and q["id"] in cur_team.index and cur_team.loc[q["id"]].status in ("ACT", "INA"):
            team_out[tm]["or"] = round(team_out[tm]["or"] + q["m"][0], 5)
            team_out[tm]["ot"] = round(team_out[tm]["ot"] + q["m"][1], 5)
            team_out[tm]["op"] = round(team_out[tm]["op"] + q["m"][2], 5)

# ---------------- FAAB: the value of future waiver breakouts ----------------
# From past seasons: players who were on waivers (outside the preseason consensus top 20 QB/TE,
# 50 RB, 70 WR, and below waiver level so far) and then produced like startable players. Their
# points above a startable level after breaking out form the pool that FAAB dollars compete for.
def breakout_pool(stats, year):
    pre_path = f"{DP_DIR}/files/db_fpecr.parquet"
    if stats is None or not len(stats) or not os.path.exists(pre_path):
        return None
    e = pd.read_parquet(pre_path, columns=["fp_page", "scrape_date", "id", "pos", "ecr"])
    e["scrape_date"] = e.scrape_date.astype(str)
    c = e[(e.fp_page == "/nfl/rankings/ppr-cheatsheets.php") & (e.scrape_date >= f"{year}-07-01") & (e.scrape_date < f"{year}-09-06")]
    if not len(c):
        return None
    c = c[(c.scrape_date == c.scrape_date.max()) & c.pos.isin(POS)].copy()
    c["gsis"] = pd.to_numeric(c.id, errors="coerce").map(fp2g)
    c["prank"] = c.groupby("pos").ecr.rank(method="first")
    pre = c.dropna(subset=["gsis"]).set_index("gsis").prank.to_dict()
    CUT = {"QB": 20, "RB": 50, "WR": 70, "TE": 20}
    N_START = {"QB": 12, "RB": 30, "WR": 40, "TE": 12}
    N_WAIVER = {"QB": 18, "RB": 48, "WR": 64, "TE": 18}
    if "faab" in ANNUAL:
        CUT, N_START, N_WAIVER = ANNUAL["faab"]["cut"], ANNUAL["faab"]["n_start"], ANNUAL["faab"]["n_waiver"]
    out = {}
    for key, col in (("std", "fantasy_points"), ("ppr", "fantasy_points_ppr")):
        g = stats.groupby(["player_id", "position"])[col].agg(["sum", "count"])
        g = g[g["count"] >= 6]
        g["ppg"] = g["sum"] / g["count"]
        T = {pos: g.xs(pos, level="position").ppg.sort_values(ascending=False).values[N_START[pos] - 1] for pos in POS}
        Uw = {pos: g.xs(pos, level="position").ppg.sort_values(ascending=False).values[N_WAIVER[pos] - 1] for pos in POS}
        pool = {w: 0.0 for w in range(1, 19)}
        for (pid, pos), h in stats.sort_values("week").groupby(["player_id", "position"]):
            if pid in pre and pre[pid] <= CUT[pos]:
                continue
            played = list(zip(h.week.astype(int), h[col].astype(float)))
            if len(played) < 4:
                continue
            for i in range(1, len(played) - 2):
                before = [v for _, v in played[:i]]
                nxt = [v for _, v in played[i:i + 4]]
                if np.mean(before) < Uw[pos] and len(nxt) >= 3 and np.mean(nxt) >= T[pos]:
                    after = [v for _, v in played[i:]]
                    val = (np.mean(after) - T[pos]) * len(after)
                    if val > 0:
                        for w in range(1, played[i][0] + 1):
                            pool[w] += val
                    break
        out[key] = {str(w): round(v, 1) for w, v in pool.items()}
    return out


pools = [p for p in (breakout_pool(s24, 2024), breakout_pool(s25, 2025)) if p]
FAAB_POOL = None
if pools:
    FAAB_POOL = {k: {w: round(sum(p[k][w] for p in pools) / len(pools), 1) for w in pools[0][k]} for k in ("std", "ppr")}

# this week's games: opponents (the start/sit simulation pairs teams that play each other) and kickoffs
OPP_WK, KICK_WK = {}, {}
for _r in g[g.week == CUR_WEEK].itertuples():
    OPP_WK[_r.home_team], OPP_WK[_r.away_team] = _r.away_team, _r.home_team
    try:
        _k = pd.Timestamp(f"{_r.gameday} {_r.gametime}", tz="America/New_York").isoformat()
    except Exception:
        _k = None
    KICK_WK[_r.home_team] = KICK_WK[_r.away_team] = _k

# ---------------- kickers and team defenses (pipeline/kdst.py) ----------------
# Projected from the Vegas lines and each team's and kicker's history: one expected stat line per remaining week
# ("kw", in DB.kdst.kComp / dComp order). The page scores them with each league's own settings.
KP = {k_: prm(k_, v_) for k_, v_ in kdst.DEFAULTS.items()}
KD_TG, KD_KG = kdst.history(RAW, pd.read_csv("games.csv", low_memory=False))
_th, _kh = kdst.cut(KD_TG, KD_KG, SEASON, CUR_WEEK)
KD_L = kdst.league(_th, _kh)
KD_D, KD_K = kdst.profiles(_th, _kh, KD_L, SEASON, KP)
ESPN_TEAM = {"ATL": 1, "BUF": 2, "CHI": 3, "CIN": 4, "CLE": 5, "DAL": 6, "DEN": 7, "DET": 8, "GB": 9, "TEN": 10, "IND": 11, "KC": 12,
             "LV": 13, "LA": 14, "MIA": 15, "MIN": 16, "NE": 17, "NO": 18, "NYG": 19, "NYJ": 20, "PHI": 21, "ARI": 22, "PIT": 23,
             "LAC": 24, "SF": 25, "SEA": 26, "TB": 27, "WAS": 28, "CAR": 29, "JAX": 30, "BAL": 33, "HOU": 34}
TEAM_NAME = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals",
             "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers", "HOU": "Texans", "IND": "Colts",
             "JAX": "Jaguars", "KC": "Chiefs", "LA": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins", "MIN": "Vikings",
             "NE": "Patriots", "NO": "Saints", "NYG": "Giants", "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks",
             "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders"}
SCHED = {}
for _r in g[g.week >= CUR_WEEK].itertuples():
    SCHED[(_r.home_team, int(_r.week))], SCHED[(_r.away_team, int(_r.week))] = _r.away_team, _r.home_team


def eff_line(tm, w):
    """(implied total, spread) for team tm in week w: the Vegas line when there is one, else the market-rating
    projection, shrunk the way the offense's game environment is (env x and spread are already shrunk)."""
    e = ENV.get(tm, {}).get(str(w))
    return (USUAL[tm] * (1 + e[0]), e[1]) if e else (None, 0.0)


def kd_round(v, kind):
    if kind == "K":
        return [round(float(x), 3) for x in v]
    return [round(float(x), 3) for x in v[:7]] + [round(float(v[7]), 1), round(float(v[8]), 1)] + [round(float(x), 4) for x in v[9:]]


def kd_mean(df, cols, kind):
    return kd_round(df[cols].astype(float).mean().values, kind) if len(df) else None


def kd_crowd(rec, key):
    """Expert, draft, roster and weekly-rank signals (FantasyPros) for a kicker or defense."""
    if key in ros_by.index:
        rr = ros_by.loc[key]
        rec["er"] = int(rr.prank)
        rec["es"] = round(float(rr.sd), 2) if pd.notna(rr.sd) else None
    if key in ovr_by and pd.notna(ovr_by[key]):
        rec["eo"] = round(float(ovr_by[key]), 1)
    if key in pre_by.index:
        rec["dr"], rec["dp"] = int(pre_by.loc[key].orank), int(pre_by.loc[key].prank)
    if key in own_by:
        rec["own"] = round(float(own_by[key]), 1)
    if key in ew_by:
        rec["ew"] = int(ew_by[key])


def kd_weeks(tm, fn):
    out = {}
    for w in range(CUR_WEEK, LAST_WEEK + 1):
        opp = SCHED.get((tm, w))
        if opp:
            out[str(w)] = fn(w, opp)
    return out


KD_AD, KD_AK = kdst.actual_dst(KD_TG), kdst.actual_k(KD_KG)
kd_players = []
for tm in teams:
    h = KD_AD[KD_AD.team == tm]
    h26 = h[h.season == SEASON].sort_values("week")

    def dst_week(w, opp, tm=tm):
        imp_o, _ = eff_line(opp, w)
        _, sp = eff_line(tm, w)
        return kd_round(kdst.project_dst(KD_L, KD_D, tm, opp, imp_o, sp, KP), "DST")
    rec = {"id": "DST-" + tm, "espn": -16000 - ESPN_TEAM[tm] if tm in ESPN_TEAM else None, "n": f"{TEAM_NAME.get(tm, tm)} D/ST",
           "p": "DST", "t": tm, "age": None, "g26": int(len(h26)), "g25": int((h.season == SEASON - 1).sum()), "g24": int((h.season == SEASON - 2).sum()),
           "inj": "", "s": kd_mean(h26, kdst.D_COMP, "DST") or [0.0] * len(kdst.D_COMP),
           "f": kd_mean(h26.tail(2), kdst.D_COMP, "DST") or [0.0] * len(kdst.D_COMP), "kw": kd_weeks(tm, dst_week)}
    for yy, key in ((SEASON - 1, "s25"), (SEASON - 2, "s24")):
        v = kd_mean(h[h.season == yy], kdst.D_COMP, "DST")
        if v:
            rec[key] = v
    if len(h26):
        rec["lg"] = int(h26.week.max())
    kd_crowd(rec, rec["id"])
    kd_players.append(rec)

# kickers: each team's kicker (depth chart first, else whoever kicked for it most recently), plus a kicker on a
# reserve list who kicked for it this season (his timeline says when he's back; the active one kicks meanwhile)
_kr = ROSTER[(ROSTER.position == "K") & ROSTER.status.isin(["ACT", "INA", "RES", "EXE"])].set_index("gsis_id")
_last_k = KD_KG[KD_KG.season == SEASON].sort_values("week").groupby("team").id.last().to_dict()
_kicked = KD_KG[KD_KG.season == SEASON].groupby(["team", "id"]).size()
for tm in teams:
    ks = _kr[_kr.team == tm]
    act = [pid for pid in ks.index if ks.loc[pid].status in ("ACT", "INA")]
    first = [pid for pid in act if depth_rank.get((tm, pid)) == 1]
    pick = first[:1] or [pid for pid in act if pid == _last_k.get(tm)][:1] or act[:1]
    pick += [pid for pid in ks.index if ks.loc[pid].status == "RES" and (tm, pid) in _kicked.index and pid not in pick]
    for pid in pick:
        ro = ks.loc[pid]
        h = KD_AK[KD_AK.id == pid]
        h26 = h[h.season == SEASON].sort_values("week")

        def k_week(w, opp, tm=tm, pid=pid):
            imp, sp = eff_line(tm, w)
            return kd_round(kdst.project_k(KD_L, KD_D, KD_K, pid, tm, imp, sp), "K")
        espn = ro.espn_id if pd.notna(ro.espn_id) else g2espn.get(pid)
        rec = {"id": pid, "espn": int(float(espn)) if espn is not None and pd.notna(espn) else None, "n": ro.full_name, "p": "K", "t": tm,
               "age": ages.get(pid), "g26": int(len(h26)), "g25": int((h.season == SEASON - 1).sum()), "g24": int((h.season == SEASON - 2).sum()),
               "s": kd_mean(h26, kdst.K_COMP, "K") or [0.0] * len(kdst.K_COMP), "f": kd_mean(h26.tail(2), kdst.K_COMP, "K") or [0.0] * len(kdst.K_COMP),
               "kw": kd_weeks(tm, k_week)}
        for yy, key in ((SEASON - 1, "s25"), (SEASON - 2, "s24")):
            v = kd_mean(h[h.season == yy], kdst.K_COMP, "K")
            if v:
                rec[key] = v
        ij = timeline(pid, ro)
        rec["inj"] = ij["st"] if ij else ""
        if ij:
            rec["ij"] = ij
        if len(h26):
            rec["lg"] = int(h26.week.max())
        if depth_rank.get((tm, pid)):
            rec["dc"] = depth_rank[(tm, pid)]
        kd_crowd(rec, pid)
        rec.update(week_status(pid, ro))
        kd_players.append(rec)
players += kd_players
KDST_DB = {"v": 1, "kComp": kdst.K_COMP, "dComp": kdst.D_COMP, "paEdges": kdst.PA_EDGES, "yaEdges": kdst.YA_EDGES[1:],
           "sim": kdst.sim_params(KD_L), "params": KP}

matched_cbs = sum(1 for p in players if p.get("ij") and p["ij"]["src"] == "CBS Sports")
out = {
    "v": 7,
    "asOf": f"{SEASON} Week {DONE_WEEK} stats (through {last_game_day})",
    "builtAt": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
    "season": SEASON, "curWeek": CUR_WEEK, "doneWeek": DONE_WEEK, "lastWeek": LAST_WEEK, "rosWeek": ROS_WEEK,
    "sources": {"ros": ROS_DATE, "pre": PRE_DATE, "own": WK_DATE, "inj": NEWS_DATE},
    "params": {"version": PARAMS_VERSION, "values": PRM, "annual": ANNUAL.get("version")}, "ewWeek": EW_WEEK, "rosN": ROS_N, "byes": byes, "weekDates": week_dates, "teams": team_out, "faabPool": FAAB_POOL,
    "opp": OPP_WK, "kick": KICK_WK, "gameday": {"at": GAMEDAY_AT, "teams": sorted(GAMEDAY)} if GAMEDAY else None, "kdst": KDST_DB,
    "players": players,
}
json.dump(out, open("db.json", "w"), separators=(",", ":"))
print(len(players), "players;", len(json.dumps(out)) // 1024, "KB; current week", CUR_WEEK, "; timelines from CBS:", matched_cbs)
print("sources", out["sources"], "experts' week", ROS_WEEK, "| weekly expert ranks for week", EW_WEEK, f"({len(ew_by)} players)")
_envs = sorted(((v[str(CUR_WEEK)][0], tm) for tm, v in ENV.items() if str(CUR_WEEK) in v), reverse=True)
if _envs:
    print(f"week {CUR_WEEK} game environment (implied vs usual):", ", ".join(f"{tm} {x:+.0%}" for x, tm in _envs[:4]), "...", ", ".join(f"{tm} {x:+.0%}" for x, tm in _envs[-4:]))
_kd = [(kdst.d_points(p["kw"][str(CUR_WEEK)]) if p["p"] == "DST" else kdst.k_points(p["kw"][str(CUR_WEEK)]), p["n"], p["p"])
       for p in kd_players if str(CUR_WEEK) in p["kw"] and not (p.get("ij") and p["ij"]["thru"] is not None and p["ij"]["thru"] >= CUR_WEEK)]
print(f"kickers and defenses: {sum(1 for p in kd_players if p['p'] == 'K')} kickers, {sum(1 for p in kd_players if p['p'] == 'DST')} defenses; "
      f"week {CUR_WEEK} (standard scoring) D/ST:", ", ".join([f"{n} {v:.1f}" for v, n, q in sorted(_kd, reverse=True) if q == "DST"][:4]),
      "| K:", ", ".join([f"{n} {v:.1f}" for v, n, q in sorted(_kd, reverse=True) if q == "K"][:4]))
print("FAAB breakout pool (PPR points above startable, league-wide) from week:", {w: FAAB_POOL["ppr"][w] for w in list(FAAB_POOL["ppr"])[2:10]} if FAAB_POOL else None)
unmatched = [k for k in cbs if not any((p["t"], p["p"]) + name_key(p["n"]) == k for p in players)]
print("CBS rows not matched to a player in the data:", len(unmatched), unmatched)
_q = [p for p in players if p.get("gs") == "Questionable"]
print(f"this week's game status: {len(_q)} questionable, {sum(1 for p in players if p.get('gs') == 'Doubtful')} doubtful, "
      f"{sum(1 for p in players if p.get('pr'))} with a practice report" + (f"; inactives posted for {len(GAMEDAY)} teams ({', '.join(sorted(GAMEDAY))}): "
      f"{sum(1 for p in players if p.get('gd') == 'inactive')} of our players inactive" if GAMEDAY else ""))
if GAMEDAY:
    _un = [(t, n) for t, names in GAMEDAY.items() for n in names if not any(p["t"] == t and name_key(p["n"]) == n for p in players)]
    print("  inactive names not in the player data (other positions or depth players; fine):", len(_un))
for p in players:
    if p.get("ij") and p["ij"]["thru"] is not None and ("er" in p or p.get("own", 0) >= 20):
        print(f"  {p['n']:<24}{p['p']} {p['t']:<4} out thru {p['ij']['thru']:>2}{' new' if p['ij'].get('nx') else '    '}  {p['ij']['st']:<20} {p['ij']['why']} [{p['ij']['src']}]")
