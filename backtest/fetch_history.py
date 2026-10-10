"""Download the past seasons the backtest replays (nflverse, GitHub only) into the current folder.

    python3 backtest/fetch_history.py 2024 2025 2026     # seasons to replay; S-2 and S-1 come along

Files: s{yy}.csv (weekly player stats), r{yy}.csv (weekly rosters), snaps{yy}.csv, dc{yy}.csv (depth charts),
games.csv. Existing files for past seasons are kept; the current season is always refreshed by build_db.py.
"""
import os
import subprocess
import sys

NV = "https://github.com/nflverse/nflverse-data/releases/download"


def get(url, out, refresh=False):
    if os.path.exists(out) and not refresh:
        return
    print("+", out, flush=True)
    for attempt in range(2):
        if subprocess.run(["curl", "-sSLf", "-o", out + ".tmp", url]).returncode == 0:
            os.replace(out + ".tmp", out)
            return
    raise SystemExit(f"download failed: {url}")


def main(seasons, current=None):
    need_stats = sorted({y for S in seasons for y in (S - 2, S - 1, S)})
    for y in need_stats:
        r = y == current
        get(f"{NV}/stats_player/stats_player_week_{y}.csv", f"s{str(y)[2:]}.csv", r)
        get(f"{NV}/weekly_rosters/roster_weekly_{y}.csv", f"r{str(y)[2:]}.csv", r)
    for S in seasons:
        r = S == current
        get(f"{NV}/snap_counts/snap_counts_{S}.csv", f"snaps{str(S)[2:]}.csv", r)
        get(f"{NV}/depth_charts/depth_charts_{S}.csv", f"dc{str(S)[2:]}.csv", r)
    get("https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv", "games.csv")


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]] or [2024, 2025, 2026])
