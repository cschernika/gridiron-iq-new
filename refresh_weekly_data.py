"""Refresh Gridiron IQ's current-season offensive and defensive snapshots.

The script is designed for the bundled GitHub Actions workflow. It downloads
public nflverse files, writes a current offensive snapshot, and builds the
coverage/trench snapshot used by the defensive and weekly-matchup pages.

If the current regular-season files have not been published yet, the script
exits successfully without replacing the known-good bundled baseline.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
USER_AGENT = "Gridiron-IQ-Weekly-Refresh/2026"
FANTASY_POSITIONS = {"QB", "RB", "FB", "WR", "TE", "K"}
STRING_FIELDS = {
    "player_id", "player_name", "player_display_name", "position",
    "position_group", "headshot_url", "recent_team", "team", "season_type",
}


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def clean_number(value):
    if value in (None, "", "NA", "NaN", "nan", "null"):
        return 0
    try:
        number = float(value)
        return int(number) if number.is_integer() else round(number, 4)
    except (TypeError, ValueError):
        return value


def download_one(urls, target, required=True):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in urls:
        for attempt in range(3):
            partial = target.with_suffix(target.suffix + ".download")
            try:
                request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
                with urlopen(request, timeout=90) as response, partial.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
                if partial.stat().st_size < 20:
                    raise RuntimeError("download was unexpectedly small")
                os.replace(partial, target)
                print(f"Downloaded {target.name} ({target.stat().st_size:,} bytes)")
                return target
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
                errors.append(f"{url}: {exc}")
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
                if attempt < 2:
                    time.sleep(2 ** attempt)
    if required:
        raise RuntimeError(f"Could not download {target.name}: {' | '.join(errors[-3:])}")
    print(f"Optional source unavailable: {target.name}")
    return None


def source_urls(season, matchup_season):
    release = "https://github.com/nflverse/nflverse-data/releases/download"
    return {
        "player": [
            f"{release}/stats_player/stats_player_reg_{season}.csv",
            f"{release}/player_stats/stats_player_reg_{season}.csv",
        ],
        "pfr": [f"{release}/pfr_advstats/advstats_season_def.csv"],
        "snap": [f"{release}/snap_counts/snap_counts_{season}.csv"],
        "pbp": [f"{release}/pbp/play_by_play_{season}.csv.gz"],
        "participation": [f"{release}/pbp_participation/pbp_participation_{season}.csv"],
        "ftn": [f"{release}/ftn_charting/ftn_charting_{season}.csv"],
        "roster": [f"{release}/rosters/roster_{matchup_season}.csv"],
        "schedule": ["https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"],
    }


def expected_paths(source_dir, season, matchup_season):
    source_dir = Path(source_dir)
    return {
        "player": source_dir / f"stats_player_reg_{season}.csv",
        "pfr": source_dir / "advstats_season_def.csv",
        "snap": source_dir / f"snap_counts_{season}.csv",
        "pbp": source_dir / f"play_by_play_{season}.csv.gz",
        "participation": source_dir / f"pbp_participation_{season}.csv",
        "ftn": source_dir / f"ftn_charting_{season}.csv",
        "roster": source_dir / f"roster_{matchup_season}.csv",
        "schedule": source_dir / "games.csv",
    }


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def csv_has_season(path, season, minimum_rows=1):
    if not Path(path).exists():
        return False
    matches = 0
    try:
        for row in read_rows(path):
            if str(row.get("season") or "") == str(season):
                matches += 1
                if matches >= minimum_rows:
                    return True
    except (OSError, UnicodeError, csv.Error):
        return False
    return False


def build_offensive_snapshot(csv_path, season, output_path):
    players = {}
    position_counts = {}
    max_games = 0
    for raw in read_rows(csv_path):
        if str(raw.get("season_type") or "REG").upper() != "REG":
            continue
        name = str(raw.get("player_display_name") or raw.get("player_name") or "").strip()
        position = str(raw.get("position") or raw.get("position_group") or "").upper()
        if not name or position not in FANTASY_POSITIONS:
            continue
        if position == "FB":
            position = "RB"
        record = {
            "name": name,
            "player_id": str(raw.get("player_id") or ""),
            "position": position,
            "team": str(raw.get("recent_team") or raw.get("team") or "").upper(),
            "season": season,
            "data_type": "actual",
        }
        for key, value in raw.items():
            if key in STRING_FIELDS or key in record:
                continue
            record[key] = clean_number(value)
        record["games"] = clean_number(raw.get("games"))
        record["total_tds"] = sum(
            float(record.get(field) or 0)
            for field in ("passing_tds", "rushing_tds", "receiving_tds")
        )
        max_games = max(max_games, int(float(record.get("games") or 0)))
        players[normalized(name)] = record
        position_counts[position] = position_counts.get(position, 0) + 1

    if not players or max_games <= 0:
        raise RuntimeError(f"{season} regular-season player statistics are not available yet")

    payload = {
        "season": season,
        "season_type": "REG",
        "data_type": "actual",
        "source": f"nflverse {season} Player Summary Stats — automatic weekly refresh",
        "status": "weekly-refresh",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "games_played_max": max_games,
        "player_count": len(players),
        "position_counts": position_counts,
        "players": players,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, output_path)
    print(f"Built {output_path} with {len(players)} offensive players")
    return payload


def empty_optional_csv(path, header):
    path = Path(path)
    if not path.exists():
        path.write_text(header.rstrip() + "\n", encoding="utf-8")


def build_defensive_snapshot(paths, season, matchup_season, offense_path, output_path):
    temporary = Path(output_path).with_suffix(".json.tmp")
    env = os.environ.copy()
    env.update({
        "GRIDIRON_STATS_SEASON": str(season),
        "GRIDIRON_MATCHUP_SEASON": str(matchup_season),
        "GRIDIRON_PLAYER_STATS_CSV": str(paths["player"]),
        "GRIDIRON_PFR_DEFENSE_CSV": str(paths["pfr"]),
        "GRIDIRON_SNAP_COUNTS_CSV": str(paths["snap"]),
        "GRIDIRON_PLAY_BY_PLAY_CSV": str(paths["pbp"]),
        "GRIDIRON_PARTICIPATION_CSV": str(paths["participation"]),
        "GRIDIRON_FTN_CHARTING_CSV": str(paths["ftn"]),
        "GRIDIRON_ROSTER_CSV": str(paths["roster"]),
        "GRIDIRON_SCHEDULES_CSV": str(paths["schedule"]),
        "GRIDIRON_OFFENSE_SNAPSHOT": str(offense_path),
        "GRIDIRON_DEFENSE_OUTPUT": str(temporary),
    })
    subprocess.run([sys.executable, str(ROOT / "build_defensive_snapshot.py")], cwd=ROOT, env=env, check=True)
    payload = json.loads(temporary.read_text(encoding="utf-8"))
    if payload.get("season") != season or len(payload.get("teams", {})) < 28:
        raise RuntimeError("Defensive refresh did not produce a complete league snapshot")
    if len(payload.get("schedule_2026", [])) < 200:
        raise RuntimeError("Defensive refresh did not include the complete matchup schedule")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, output_path)
    print(f"Built {output_path} with {len(payload['teams'])} teams and {len(payload.get('players', {}))} defenders")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--matchup-season", type=int, default=2026)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--source-dir", type=Path, help="Use already-downloaded source files instead of the network")
    parser.add_argument("--no-defense", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    temporary_context = None
    if args.source_dir:
        paths = expected_paths(args.source_dir, args.season, args.matchup_season)
        missing = [str(path) for key, path in paths.items() if key in {"player"} and not path.exists()]
        if missing:
            raise RuntimeError("Missing required local source: " + ", ".join(missing))
    else:
        temporary_context = tempfile.TemporaryDirectory(prefix="gridiron-weekly-")
        source_dir = Path(temporary_context.name)
        paths = expected_paths(source_dir, args.season, args.matchup_season)
        urls = source_urls(args.season, args.matchup_season)
        try:
            download_one(urls["player"], paths["player"], required=True)
        except RuntimeError as exc:
            print(f"No current-season update: {exc}")
            temporary_context.cleanup()
            return 0

    offense_path = args.output_dir / f"nfl_player_stats_{args.season}.json"
    try:
        build_offensive_snapshot(paths["player"], args.season, offense_path)
    except RuntimeError as exc:
        print(f"No current-season update: {exc}")
        if temporary_context:
            temporary_context.cleanup()
        return 0

    if not args.no_defense:
        if not args.source_dir:
            urls = source_urls(args.season, args.matchup_season)
            requirements = {"pbp": True, "participation": True, "roster": True, "schedule": True, "pfr": True, "snap": True, "ftn": False}
            failures = {}
            with ThreadPoolExecutor(max_workers=7) as executor:
                jobs = {executor.submit(download_one, urls[key], paths[key], required): key for key, required in requirements.items()}
                for future in as_completed(jobs):
                    key = jobs[future]
                    try:
                        future.result()
                    except Exception as exc:
                        failures[key] = str(exc)
            if any(key in failures for key in ("pbp", "participation", "roster", "schedule", "pfr", "snap")):
                print("Defensive refresh deferred; required charting source is not available yet:", failures)
                if temporary_context:
                    temporary_context.cleanup()
                return 0

        empty_optional_csv(paths["ftn"], "season,nflverse_game_id,nflverse_play_id,n_blitzers")
        required_local = [paths[key] for key in ("pbp", "participation", "roster", "schedule", "pfr", "snap")]
        charting_ready = csv_has_season(paths["pfr"], args.season, 50) and csv_has_season(paths["snap"], args.season, 50)
        if all(path.exists() for path in required_local) and charting_ready:
            defense_path = args.output_dir / "nfl_defensive_stats_current.json"
            build_defensive_snapshot(paths, args.season, args.matchup_season, offense_path, defense_path)
        else:
            print("Defensive refresh skipped until the complete current-season PFR, snap, play-by-play, and participation sources are published")

    if temporary_context:
        temporary_context.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
