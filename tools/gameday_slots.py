"""Pre-kickoff refresh slots from nflverse games.csv, so one scheduled task can chain itself through the season.

    python3 tools/gameday_slots.py            # JSON: the slot this run is for ("current") and the next one, with its cron
    python3 tools/gameday_slots.py --list     # every slot from today to the end of the schedule
    options: --games <games.csv> (default: download it)   --now <ISO time> (for testing)

A slot is 83 minutes before a kickoff (7 minutes after that game's inactives), America/New_York:
- every game day except Monday: before the day's first kickoff;
- a morning first kickoff (international Sunday): also before the first kickoff from noon on (the main slate);
- a Thursday that starts before 5 pm (Thanksgiving): also before the night game;
- a Thursday with no game in a week that has games (Week 18): 6:52 pm, for Thursday's practice reports.
Monday and Sunday night games ride on the day's earlier refresh. Tags follow runbooks/gameday.md.
Standard library only, so it runs before anything is installed.
"""
import argparse
import csv
import json
import subprocess
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
LEAD = timedelta(minutes=83)
BACK, AHEAD = timedelta(hours=3), timedelta(minutes=45)   # a run counts as a slot's run within this window


def load_games(path=None):
    if path is None:
        path = tempfile.mkstemp(suffix=".csv")[1]
        subprocess.run(["curl", "-sSLf", "-o", path, URL], check=True)
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if r["game_type"] == "REG" and ":" in (r["gametime"] or "")]


def kickoff(r):
    return datetime.fromisoformat(f"{r['gameday']}T{r['gametime']}").replace(tzinfo=ET)


def tag(day, at, ko):
    wd = day.strftime("%a").lower()
    if wd == "thu":
        return "late-thu-am" if ko and ko.hour < 17 else "late-thu"
    if wd == "sun":
        return "late-sun-am" if at.hour < 10 else "late-sun"
    return f"late-{wd}"


def slots(games):
    """Every slot in time order: {at, tag, kickoff, games}."""
    by_day, by_week = {}, {}
    for r in games:
        by_day.setdefault(r["gameday"], []).append(r)
        by_week.setdefault((r["season"], r["week"]), set()).add(r["gameday"])
    out = []
    for rs in by_day.values():
        rs.sort(key=kickoff)
        ks = [kickoff(r) for r in rs]
        first, day = ks[0], ks[0].date()
        if first.weekday() == 0:
            continue
        starts = [first]
        if first.hour < 12 and any(k.hour >= 12 for k in ks):
            starts.append(next(k for k in ks if k.hour >= 12))
        if first.weekday() == 3 and first.hour < 17 and any(k.hour >= 19 for k in ks):
            starts.append(next(k for k in ks if k.hour >= 19))
        for i, s in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else None
            covered = [r for r, k in zip(rs, ks) if k >= s and (end is None or k < end)]
            out.append({"at": s - LEAD, "tag": tag(day, s - LEAD, s), "kickoff": s,
                        "games": [f"{r['away_team']} at {r['home_team']} {kickoff(r):%-I:%M %p}" for r in covered]})
    for days in by_week.values():   # game-less Thursday of a week with a Sunday slate
        suns = [d for d in days if datetime.fromisoformat(d).weekday() == 6]
        thu = suns and (datetime.fromisoformat(max(suns)) - timedelta(days=3)).date()
        if thu and thu.isoformat() not in days:
            at = datetime(thu.year, thu.month, thu.day, 18, 52, tzinfo=ET)
            out.append({"at": at, "tag": "late-thu", "kickoff": None, "games": []})
    return sorted(out, key=lambda s: s["at"])


def cron(at):
    return f"CRON_TZ=America/New_York {at.minute} {at.hour} {at.day} {at.month} *"


def show(s):
    if s is None:
        return None
    ko = s["kickoff"]
    return {"at": s["at"].isoformat(), "label": f"{s['at']:%A %b %-d}", "tag": s["tag"],
            "kickoff": ko and ko.isoformat(), "deadline": ko and (ko - timedelta(minutes=15)).strftime("%-I:%M %p ET"),
            "games": s["games"], "cron": cron(s["at"])}


def plan(all_slots, now):
    """The slot a run starting now is for (fired up to 3 h late or 45 min early), and the one after it."""
    cur = [s for s in all_slots if now - BACK <= s["at"] <= now + AHEAD]
    cur = cur[-1] if cur else None
    floor = max(now + AHEAD, cur["at"] if cur else now)
    nxt = next((s for s in all_slots if s["at"] > floor), None)
    return {"now": now.isoformat(), "current": show(cur), "next": show(nxt)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--games")
    ap.add_argument("--now")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    now = datetime.fromisoformat(a.now).astimezone(ET) if a.now else datetime.now(ET)
    S = slots(load_games(a.games))
    if a.list:
        for s in S:
            if s["at"] >= now - timedelta(days=1):
                print(f"{s['at']:%Y-%m-%d %a %H:%M}  {s['tag']:<12} {', '.join(s['games']) or '(no game: practice reports)'}")
    else:
        print(json.dumps(plan(S, now), indent=1))
