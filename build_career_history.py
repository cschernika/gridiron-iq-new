"""Build the complete Gridiron IQ offensive player career-history database.

The script downloads nflverse regular-season player summaries, keeps every
fantasy-relevant offensive player season, and writes one compact lookup used by
the Player Research profile. It is dependency-free so GitHub Actions can run it
without installing the Flask application.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
USER_AGENT = "Gridiron-IQ-Career-History/2026"
FANTASY_POSITIONS = {"QB", "RB", "FB", "WR", "TE", "K"}
MINIMUM_SEASON_PLAYERS = 150
STAT_FIELDS = (
    "games", "completions", "attempts", "passing_yards", "passing_tds",
    "sacks_suffered", "passing_air_yards", "passing_first_downs",
    "passing_epa", "passing_cpoe", "carries", "rushing_yards",
    "rushing_tds", "rushing_first_downs", "rushing_epa", "rushing_10",
    "rushing_20", "receptions", "targets", "receiving_yards",
    "receiving_tds", "receiving_air_yards", "receiving_yards_after_catch",
    "receiving_first_downs", "receiving_epa", "target_share",
    "air_yards_share", "wopr", "fg_made", "fg_att", "fg_pct", "fg_long",
    "fg_made_40_49", "fg_made_50_59", "fg_made_60_", "pat_made",
    "pat_att", "pat_pct", "fantasy_points", "fantasy_points_ppr",
)


def norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def clean_number(value):
    if value in (None, "", "NA", "NaN", "nan", "null"):
        return 0
    try:
        number = float(value)
        return int(number) if number.is_integer() else round(number, 4)
    except (TypeError, ValueError):
        return 0


def season_urls(season):
    release = "https://github.com/nflverse/nflverse-data/releases/download"
    return [
        f"{release}/stats_player/stats_player_reg_{season}.csv",
        f"{release}/player_stats/stats_player_reg_{season}.csv",
    ]


def download_season(season, directory):
    target = Path(directory) / f"stats_player_reg_{season}.csv"
    errors = []
    for url in season_urls(season):
        for attempt in range(3):
            partial = target.with_suffix(".csv.download")
            try:
                request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
                with urlopen(request, timeout=90) as response, partial.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
                if partial.stat().st_size < 1000:
                    raise RuntimeError("download was unexpectedly small")
                os.replace(partial, target)
                return season, target
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
                errors.append(str(exc))
                partial.unlink(missing_ok=True)
                if attempt < 2:
                    time.sleep(2 ** attempt)
    raise RuntimeError(f"{season}: {' | '.join(errors[-3:])}")


def player_name(row):
    return str(row.get("player_display_name") or row.get("player_name") or "").strip()


def team_code(value):
    code = str(value or "").strip().upper()
    return {
        "JAX": "JAC",
        "LA": "LAR",
        "OAK": "LV",
        "SD": "LAC",
        "STL": "LAR",
        "WSH": "WAS",
    }.get(code, code)


def build_season(path, season):
    records = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            if str(raw.get("season_type") or "REG").upper() != "REG":
                continue
            name = player_name(raw)
            position = str(raw.get("position") or raw.get("position_group") or "").upper()
            if not name or position not in FANTASY_POSITIONS:
                continue
            if position == "FB":
                position = "RB"
            key = norm(name)
            if not key:
                continue
            record = {
                "season": int(season),
                "name": name,
                "player_id": str(raw.get("player_id") or ""),
                "team": team_code(raw.get("recent_team") or raw.get("team")),
                "position": position,
            }
            for field in STAT_FIELDS:
                record[field] = clean_number(raw.get(field))
            record["interceptions"] = clean_number(
                raw.get("interceptions") or raw.get("passing_interceptions")
            )
            records[key] = record
    if len(records) < MINIMUM_SEASON_PLAYERS:
        raise RuntimeError(
            f"{season} produced only {len(records)} fantasy-player records; refusing incomplete history"
        )
    return records


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=1999)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--source-dir", type=Path, help="Use local season CSV files")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "nfl_player_career_history.json",
    )
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.start_season < 1999 or args.end_season < args.start_season:
        raise SystemExit("Season range must begin in 1999 or later and end after it begins")

    seasons = list(range(args.start_season, args.end_season + 1))
    temporary = None
    if args.source_dir:
        paths = {
            season: args.source_dir / f"stats_player_reg_{season}.csv"
            for season in seasons
        }
        missing = [str(path) for path in paths.values() if not path.exists()]
        if missing:
            raise RuntimeError("Missing career source files: " + ", ".join(missing[:5]))
    else:
        temporary = tempfile.TemporaryDirectory(prefix="gridiron-career-")
        paths = {}
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 10))) as executor:
            futures = {
                executor.submit(download_season, season, temporary.name): season
                for season in seasons
            }
            for future in as_completed(futures):
                season, path = future.result()
                paths[season] = path
                print(f"Downloaded career season {season}")

    players = {}
    season_counts = {}
    for season in seasons:
        records = build_season(paths[season], season)
        season_counts[str(season)] = len(records)
        for key, record in records.items():
            players.setdefault(key, {})[str(season)] = record
        print(f"Built career season {season}: {len(records)} players")

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "loaded_seasons": seasons,
        "season_count": len(seasons),
        "player_count": len(players),
        "season_player_counts": season_counts,
        "status": "complete",
        "source": "nflverse Player Summary Stats",
        "players": players,
    }
    atomic_json(args.output, payload)
    print(
        f"Wrote {args.output} with {len(players)} players and "
        f"{sum(len(value) for value in players.values())} player-seasons"
    )
    if temporary:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
