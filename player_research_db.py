
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sqlite3
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from flask import Blueprint, current_app, jsonify, request


bp = Blueprint("player_research_db", __name__)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("GRIDIRON_DATA_DIR") or (BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "player_research.sqlite3"

POSITION_VALUES = {"QB", "RB", "WR", "TE", "K", "DEF"}
STAT_FIELDS = (
    "games",
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "fantasy_points",
    "fantasy_points_ppr",
)


def _norm(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _position(value: Any) -> str:
    pos = str(value or "").upper().strip()
    if pos == "DST":
        pos = "DEF"
    return pos if pos in POSITION_VALUES else ""


def _number(value: Any) -> float:
    try:
        if value in (None, "", "NA", "NaN", "nan", "null"):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


@contextmanager
def connect():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_database() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                player_key TEXT PRIMARY KEY,
                player_id TEXT,
                name TEXT NOT NULL,
                position TEXT,
                team TEXT,
                age REAL,
                college TEXT,
                years_exp REAL,
                status TEXT,
                injury_status TEXT,
                rookie INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                first_season INTEGER,
                last_season INTEGER,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_players_name
                ON players(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_players_position
                ON players(position);
            CREATE INDEX IF NOT EXISTS idx_players_team
                ON players(team);

            CREATE TABLE IF NOT EXISTS season_stats (
                player_key TEXT NOT NULL,
                season INTEGER NOT NULL,
                team TEXT,
                position TEXT,
                games REAL NOT NULL DEFAULT 0,
                completions REAL NOT NULL DEFAULT 0,
                attempts REAL NOT NULL DEFAULT 0,
                passing_yards REAL NOT NULL DEFAULT 0,
                passing_tds REAL NOT NULL DEFAULT 0,
                interceptions REAL NOT NULL DEFAULT 0,
                carries REAL NOT NULL DEFAULT 0,
                rushing_yards REAL NOT NULL DEFAULT 0,
                rushing_tds REAL NOT NULL DEFAULT 0,
                targets REAL NOT NULL DEFAULT 0,
                receptions REAL NOT NULL DEFAULT 0,
                receiving_yards REAL NOT NULL DEFAULT 0,
                receiving_tds REAL NOT NULL DEFAULT 0,
                fantasy_points REAL NOT NULL DEFAULT 0,
                fantasy_points_ppr REAL NOT NULL DEFAULT 0,
                source TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (player_key, season),
                FOREIGN KEY (player_key) REFERENCES players(player_key)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_season_stats_season
                ON season_stats(season);

            CREATE TABLE IF NOT EXISTS adp (
                player_key TEXT NOT NULL,
                season INTEGER NOT NULL,
                platform TEXT NOT NULL,
                adp REAL,
                position_adp TEXT,
                rank_value REAL,
                source TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (player_key, season, platform),
                FOREIGN KEY (player_key) REFERENCES players(player_key)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_adp_lookup
                ON adp(season, platform, adp);

            CREATE TABLE IF NOT EXISTS projections (
                player_key TEXT NOT NULL,
                season INTEGER NOT NULL,
                games REAL NOT NULL DEFAULT 17,
                passing_yards REAL NOT NULL DEFAULT 0,
                passing_tds REAL NOT NULL DEFAULT 0,
                interceptions REAL NOT NULL DEFAULT 0,
                carries REAL NOT NULL DEFAULT 0,
                rushing_yards REAL NOT NULL DEFAULT 0,
                rushing_tds REAL NOT NULL DEFAULT 0,
                targets REAL NOT NULL DEFAULT 0,
                receptions REAL NOT NULL DEFAULT 0,
                receiving_yards REAL NOT NULL DEFAULT 0,
                receiving_tds REAL NOT NULL DEFAULT 0,
                fantasy_points_ppr REAL NOT NULL DEFAULT 0,
                method TEXT,
                source TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (player_key, season),
                FOREIGN KEY (player_key) REFERENCES players(player_key)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS build_status (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )


def _set_status(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute(
        """
        INSERT INTO build_status(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def import_current_players() -> int:
    init_database()
    cache_path = DATA_DIR / "sleeper_players_cache.json"
    payload: dict[str, Any] = {}

    try:
        if cache_path.exists():
            payload = _load_json(cache_path)
    except Exception:
        payload = {}

    if not payload:
        response = requests.get(
            "https://api.sleeper.app/v1/players/nfl",
            headers={"User-Agent": "Gridiron-IQ/2026"},
            timeout=(10, 45),
        )
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict):
            payload = result
            cache_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

    now = datetime.now(timezone.utc).isoformat()
    rows = []

    for player_id, player in payload.items():
        if not isinstance(player, dict):
            continue

        name = (
            player.get("full_name")
            or " ".join(
                part for part in [
                    player.get("first_name"),
                    player.get("last_name"),
                ] if part
            )
        ).strip()
        if not name:
            continue

        position = _position(
            player.get("position")
            or ((player.get("fantasy_positions") or [""])[0])
        )
        if not position:
            continue

        active = player.get("active")
        status = str(player.get("status") or "").lower()
        team = str(player.get("team") or "").upper()

        current_signal = (
            active is True
            or bool(team)
            or status in {
                "active",
                "injured reserve",
                "pup",
                "suspended",
                "non-football injury",
            }
        )
        if not current_signal:
            continue

        rows.append(
            (
                _norm(name),
                str(player_id),
                name,
                position,
                team or "FA",
                _number(player.get("age")) or None,
                player.get("college") or "",
                _number(player.get("years_exp")) or None,
                player.get("status") or "",
                player.get("injury_status") or "",
                1 if player.get("rookie") else 0,
                1,
                now,
            )
        )

    with connect() as db:
        db.executemany(
            """
            INSERT INTO players(
                player_key, player_id, name, position, team, age, college,
                years_exp, status, injury_status, rookie, active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                player_id=excluded.player_id,
                name=excluded.name,
                position=excluded.position,
                team=excluded.team,
                age=excluded.age,
                college=excluded.college,
                years_exp=excluded.years_exp,
                status=excluded.status,
                injury_status=excluded.injury_status,
                rookie=excluded.rookie,
                active=excluded.active,
                updated_at=excluded.updated_at
            """,
            rows,
        )
        _set_status(db, "current_players", {"count": len(rows)})

    return len(rows)


def _stats_urls(season: int) -> list[str]:
    return [
        f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_reg_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_week_{season}.csv",
    ]


def _download_season_rows(season: int) -> list[dict[str, str]]:
    cache_path = DATA_DIR / f"player_stats_{season}.csv"

    if cache_path.exists() and cache_path.stat().st_size > 1000:
        text = cache_path.read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        if rows:
            return rows

    errors = []
    for url in _stats_urls(season):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Gridiron-IQ/2026"},
                timeout=(10, 90),
            )
            if response.status_code != 200:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue

            text = response.content.decode("utf-8-sig", errors="replace")
            rows = list(csv.DictReader(io.StringIO(text)))
            if not rows:
                errors.append(f"{url}: empty")
                continue

            cache_path.write_text(text, encoding="utf-8")
            return rows
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError(
        f"Unable to load {season} nflverse statistics: "
        + " | ".join(errors[-4:])
    )


def _row_name(row: dict[str, Any]) -> str:
    return str(
        row.get("player_display_name")
        or row.get("player_name")
        or row.get("full_name")
        or row.get("name")
        or ""
    ).strip()


def _aggregate_rows(rows: list[dict[str, Any]], name: str) -> dict[str, float]:
    if not rows:
        return {}

    # nflverse player-summary files contain one row per player; weekly files
    # require summing. Max games prevents weekly files from summing cumulative
    # game values incorrectly.
    result = {field: 0.0 for field in STAT_FIELDS}

    for field in STAT_FIELDS:
        values = [_number(row.get(field)) for row in rows]
        if field == "games":
            result[field] = max(values or [0])
        else:
            result[field] = sum(values)

    # Some nflverse summary files already provide fantasy points while others
    # do not. Calculate a PPR fallback when necessary.
    if result["fantasy_points_ppr"] <= 0:
        result["fantasy_points_ppr"] = (
            result["passing_yards"] * 0.04
            + result["passing_tds"] * 4
            - result["interceptions"] * 2
            + result["rushing_yards"] * 0.1
            + result["rushing_tds"] * 6
            + result["receptions"]
            + result["receiving_yards"] * 0.1
            + result["receiving_tds"] * 6
        )

    return result


def import_season(season: int) -> int:
    init_database()
    season = int(season)
    if season < 1999 or season > 2025:
        raise ValueError("Season must be between 1999 and 2025.")

    raw_rows = _download_season_rows(season)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in raw_rows:
        name = _row_name(row)
        if name:
            grouped[_norm(name)].append(row)

    now = datetime.now(timezone.utc).isoformat()
    player_rows = []
    stat_rows = []

    for player_key, matches in grouped.items():
        first = matches[0]
        name = _row_name(first)
        position = _position(
            first.get("position")
            or first.get("position_group")
        )
        team = str(
            first.get("recent_team")
            or first.get("team")
            or ""
        ).upper()
        stats = _aggregate_rows(matches, name)

        player_rows.append(
            (
                player_key,
                str(first.get("player_id") or ""),
                name,
                position,
                team or "FA",
                1,
                season,
                season,
                now,
            )
        )

        stat_rows.append(
            (
                player_key,
                season,
                team or "FA",
                position,
                *[stats[field] for field in STAT_FIELDS],
                "nflverse Player Stats",
                now,
            )
        )

    with connect() as db:
        db.executemany(
            """
            INSERT INTO players(
                player_key, player_id, name, position, team, active,
                first_season, last_season, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                player_id=CASE
                    WHEN excluded.player_id <> '' THEN excluded.player_id
                    ELSE players.player_id
                END,
                name=excluded.name,
                position=CASE
                    WHEN excluded.position <> '' THEN excluded.position
                    ELSE players.position
                END,
                team=CASE
                    WHEN players.team IS NULL OR players.team='' OR players.team='FA'
                    THEN excluded.team ELSE players.team END,
                first_season=CASE
                    WHEN players.first_season IS NULL
                    THEN excluded.first_season
                    ELSE MIN(players.first_season, excluded.first_season)
                END,
                last_season=CASE
                    WHEN players.last_season IS NULL
                    THEN excluded.last_season
                    ELSE MAX(players.last_season, excluded.last_season)
                END,
                updated_at=excluded.updated_at
            """,
            player_rows,
        )

        db.executemany(
            """
            INSERT INTO season_stats(
                player_key, season, team, position,
                games, completions, attempts, passing_yards, passing_tds,
                interceptions, carries, rushing_yards, rushing_tds,
                targets, receptions, receiving_yards, receiving_tds,
                fantasy_points, fantasy_points_ppr, source, updated_at
            )
            VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            ON CONFLICT(player_key, season) DO UPDATE SET
                team=excluded.team,
                position=excluded.position,
                games=excluded.games,
                completions=excluded.completions,
                attempts=excluded.attempts,
                passing_yards=excluded.passing_yards,
                passing_tds=excluded.passing_tds,
                interceptions=excluded.interceptions,
                carries=excluded.carries,
                rushing_yards=excluded.rushing_yards,
                rushing_tds=excluded.rushing_tds,
                targets=excluded.targets,
                receptions=excluded.receptions,
                receiving_yards=excluded.receiving_yards,
                receiving_tds=excluded.receiving_tds,
                fantasy_points=excluded.fantasy_points,
                fantasy_points_ppr=excluded.fantasy_points_ppr,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            stat_rows,
        )

        _set_status(
            db,
            f"season_{season}",
            {"season": season, "players": len(stat_rows)},
        )

    return len(stat_rows)


def import_all_history(start_season: int = 1999, end_season: int = 2025) -> dict[str, Any]:
    imported = {}
    failures = {}

    for season in range(int(start_season), int(end_season) + 1):
        try:
            imported[str(season)] = import_season(season)
        except Exception as exc:
            failures[str(season)] = str(exc)

    return {
        "imported": imported,
        "failures": failures,
        "season_count": len(imported),
    }


def _adp_candidates(platform: str) -> list[Path]:
    platform = platform.upper()
    if platform == "ESPN":
        return [
            DATA_DIR / "espn_adp_2026.json",
            DATA_DIR / "espn_native_adp_2026.json",
        ]
    return [DATA_DIR / "yahoo_adp_2026.json"]


def import_adp(platform: str = "ESPN") -> dict[str, Any]:
    init_database()
    platform = platform.upper()
    if platform not in {"ESPN", "YAHOO"}:
        raise ValueError("Platform must be ESPN or YAHOO.")

    payload = {}
    source_path = None

    for candidate in _adp_candidates(platform):
        current = _load_json(candidate)
        if current.get("players"):
            payload = current
            source_path = candidate
            break

    if not payload:
        return {
            "ok": False,
            "platform": platform,
            "count": 0,
            "message": (
                f"No saved {platform} ADP dataset was found. "
                "Sync the league or provide an authorized ADP file first."
            ),
        }

    now = datetime.now(timezone.utc).isoformat()
    player_rows = []
    adp_rows = []

    for player_key, row in payload.get("players", {}).items():
        if not isinstance(row, dict):
            continue

        name = str(row.get("name") or row.get("player_name") or "").strip()
        if not name:
            continue

        normalized = _norm(name)
        position = _position(row.get("position") or row.get("pos"))
        team = str(row.get("team") or "").upper()

        try:
            adp_value = float(row.get("adp"))
            if not (0 < adp_value < 999):
                continue
        except Exception:
            continue

        player_rows.append(
            (
                normalized,
                str(row.get("player_id") or ""),
                name,
                position,
                team or "FA",
                1,
                now,
            )
        )
        adp_rows.append(
            (
                normalized,
                2026,
                platform,
                adp_value,
                str(
                    row.get("position_adp")
                    or row.get("positional_rank")
                    or ""
                ),
                _number(row.get("rank") or row.get("rank_value")) or None,
                payload.get("source") or source_path.name,
                payload.get("updated_at") or now,
            )
        )

    with connect() as db:
        db.executemany(
            """
            INSERT INTO players(
                player_key, player_id, name, position, team, active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                player_id=CASE WHEN excluded.player_id<>'' THEN excluded.player_id ELSE players.player_id END,
                name=excluded.name,
                position=CASE WHEN excluded.position<>'' THEN excluded.position ELSE players.position END,
                team=CASE WHEN excluded.team<>'FA' THEN excluded.team ELSE players.team END,
                active=1,
                updated_at=excluded.updated_at
            """,
            player_rows,
        )
        db.execute("DELETE FROM adp WHERE season=2026 AND platform=?", (platform,))
        db.executemany(
            """
            INSERT INTO adp(
                player_key, season, platform, adp, position_adp,
                rank_value, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            adp_rows,
        )
        _set_status(
            db,
            f"adp_{platform.lower()}_2026",
            {
                "count": len(adp_rows),
                "source": payload.get("source") or str(source_path),
            },
        )

    return {
        "ok": bool(adp_rows),
        "platform": platform,
        "count": len(adp_rows),
        "source": payload.get("source") or source_path.name,
    }


def import_projections() -> int:
    init_database()
    path = DATA_DIR / "nfl_players_2026.json"
    payload = _load_json(path)
    players = payload.get("players", {})
    now = datetime.now(timezone.utc).isoformat()
    player_rows = []
    projection_rows = []

    for player_key, row in players.items():
        if not isinstance(row, dict):
            continue

        name = str(row.get("name") or row.get("full_name") or "").strip()
        if not name:
            continue

        normalized = _norm(name)
        position = _position(row.get("position"))
        team = str(row.get("team") or "").upper()
        projection = row.get("projection") or {}
        if not isinstance(projection, dict):
            projection = {}

        player_rows.append(
            (
                normalized,
                str(row.get("sleeper_id") or row.get("player_id") or ""),
                name,
                position,
                team or "FA",
                _number(row.get("age")) or None,
                row.get("college") or "",
                _number(row.get("years_exp")) or None,
                row.get("status") or "",
                row.get("injury_status") or "",
                1 if row.get("rookie") else 0,
                1,
                now,
            )
        )

        projection_rows.append(
            (
                normalized,
                2026,
                _number(projection.get("games")) or 17,
                _number(projection.get("passing_yards") or projection.get("pass_yards")),
                _number(projection.get("passing_tds") or projection.get("pass_tds")),
                _number(projection.get("interceptions")),
                _number(projection.get("carries") or projection.get("rush_attempts")),
                _number(projection.get("rushing_yards") or projection.get("rush_yards")),
                _number(projection.get("rushing_tds") or projection.get("rush_tds")),
                _number(projection.get("targets")),
                _number(projection.get("receptions")),
                _number(projection.get("receiving_yards") or projection.get("rec_yards")),
                _number(projection.get("receiving_tds") or projection.get("rec_tds")),
                _number(
                    projection.get("ppr_points")
                    or projection.get("fantasy_points_ppr")
                    or projection.get("fantasy_points")
                    or projection.get("points")
                ),
                projection.get("method") or "source projection",
                payload.get("source") or path.name,
                payload.get("updated_at") or now,
            )
        )

    with connect() as db:
        db.executemany(
            """
            INSERT INTO players(
                player_key, player_id, name, position, team, age, college,
                years_exp, status, injury_status, rookie, active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                player_id=CASE WHEN excluded.player_id<>'' THEN excluded.player_id ELSE players.player_id END,
                name=excluded.name,
                position=CASE WHEN excluded.position<>'' THEN excluded.position ELSE players.position END,
                team=CASE WHEN excluded.team<>'FA' THEN excluded.team ELSE players.team END,
                age=COALESCE(excluded.age, players.age),
                college=CASE WHEN excluded.college<>'' THEN excluded.college ELSE players.college END,
                years_exp=COALESCE(excluded.years_exp, players.years_exp),
                status=CASE WHEN excluded.status<>'' THEN excluded.status ELSE players.status END,
                injury_status=CASE WHEN excluded.injury_status<>'' THEN excluded.injury_status ELSE players.injury_status END,
                rookie=MAX(players.rookie, excluded.rookie),
                active=1,
                updated_at=excluded.updated_at
            """,
            player_rows,
        )
        db.execute("DELETE FROM projections WHERE season=2026")
        db.executemany(
            """
            INSERT INTO projections(
                player_key, season, games, passing_yards, passing_tds,
                interceptions, carries, rushing_yards, rushing_tds,
                targets, receptions, receiving_yards, receiving_tds,
                fantasy_points_ppr, method, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            projection_rows,
        )
        _set_status(db, "projections_2026", {"count": len(projection_rows)})

    return len(projection_rows)


def build_everything(start_season: int = 1999, end_season: int = 2025) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result["current_players"] = import_current_players()
    result["history"] = import_all_history(start_season, end_season)
    result["projections_2026"] = import_projections()
    result["adp_espn"] = import_adp("ESPN")
    result["adp_yahoo"] = import_adp("YAHOO")
    return result


def _fallback_projection(stats: sqlite3.Row | None, position: str) -> dict[str, float]:
    def value(key: str) -> float:
        return _number(stats[key]) if stats is not None and key in stats.keys() else 0.0

    factor = {
        "QB": 1.01,
        "RB": 0.98,
        "WR": 1.01,
        "TE": 1.02,
        "K": 1.00,
        "DEF": 1.00,
    }.get(position, 1.0)

    ppr = value("fantasy_points_ppr")
    if ppr <= 0:
        ppr = {
            "QB": 245.0,
            "RB": 145.0,
            "WR": 140.0,
            "TE": 105.0,
            "K": 120.0,
            "DEF": 120.0,
        }.get(position, 100.0)

    return {
        "games": 17,
        "passing_yards": round(value("passing_yards") * factor),
        "passing_tds": round(value("passing_tds") * factor, 1),
        "interceptions": round(value("interceptions") * factor, 1),
        "carries": round(value("carries") * factor),
        "rushing_yards": round(value("rushing_yards") * factor),
        "rushing_tds": round(value("rushing_tds") * factor, 1),
        "targets": round(value("targets") * factor),
        "receptions": round(value("receptions") * factor),
        "receiving_yards": round(value("receiving_yards") * factor),
        "receiving_tds": round(value("receiving_tds") * factor, 1),
        "fantasy_points_ppr": round(ppr * factor, 1),
        "method": "Gridiron IQ 2025-production fallback",
    }


def database_status() -> dict[str, Any]:
    init_database()
    with connect() as db:
        counts = {
            "players": db.execute("SELECT COUNT(*) FROM players").fetchone()[0],
            "season_rows": db.execute("SELECT COUNT(*) FROM season_stats").fetchone()[0],
            "seasons": db.execute("SELECT COUNT(DISTINCT season) FROM season_stats").fetchone()[0],
            "espn_adp": db.execute(
                "SELECT COUNT(*) FROM adp WHERE season=2026 AND platform='ESPN'"
            ).fetchone()[0],
            "yahoo_adp": db.execute(
                "SELECT COUNT(*) FROM adp WHERE season=2026 AND platform='YAHOO'"
            ).fetchone()[0],
            "projections": db.execute(
                "SELECT COUNT(*) FROM projections WHERE season=2026"
            ).fetchone()[0],
        }
        min_max = db.execute(
            "SELECT MIN(season), MAX(season) FROM season_stats"
        ).fetchone()

    return {
        "ok": counts["players"] > 0,
        "database": str(DB_PATH),
        **counts,
        "first_season": min_max[0],
        "last_season": min_max[1],
    }


@bp.get("/api/player-research-db/status")
def status_api():
    return jsonify(database_status())


@bp.post("/api/player-research-db/import-current")
def import_current_api():
    try:
        count = import_current_players()
        return jsonify(ok=True, player_count=count)
    except Exception as exc:
        current_app.logger.exception("Player database current-player import failed")
        return jsonify(ok=False, error=str(exc)), 500


@bp.post("/api/player-research-db/import-adp")
def import_adp_api():
    body = request.get_json(silent=True) or {}
    platform = str(body.get("platform") or "ESPN").upper()
    try:
        result = import_adp(platform)
        return jsonify(result), 200 if result.get("ok") else 409
    except Exception as exc:
        current_app.logger.exception("Player database ADP import failed")
        return jsonify(ok=False, error=str(exc)), 500


@bp.post("/api/player-research-db/import-projections")
def import_projection_api():
    try:
        count = import_projections()
        return jsonify(ok=True, projection_count=count)
    except Exception as exc:
        current_app.logger.exception("Player database projection import failed")
        return jsonify(ok=False, error=str(exc)), 500


@bp.post("/api/player-research-db/import-season/<int:season>")
def import_season_api(season: int):
    try:
        count = import_season(season)
        return jsonify(ok=True, season=season, player_count=count)
    except Exception as exc:
        current_app.logger.exception("Season %s database import failed", season)
        return jsonify(ok=False, season=season, error=str(exc)), 500


@bp.get("/api/player-research-db/table")
def table_api():
    init_database()
    platform = str(request.args.get("platform") or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    position = _position(request.args.get("position"))
    query = str(request.args.get("q") or "").strip()
    sort = str(request.args.get("sort") or "adp")
    direction = "DESC" if str(request.args.get("direction") or "asc").lower() == "desc" else "ASC"

    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1
    try:
        page_size = min(250, max(25, int(request.args.get("page_size", 100))))
    except Exception:
        page_size = 100

    sort_columns = {
        "name": "p.name",
        "team": "p.team",
        "position": "p.position",
        "adp": "COALESCE(a.adp, 999999)",
        "position_adp": "a.position_adp",
        "points_2025": "COALESCE(s.fantasy_points_ppr, 0)",
        "projection_2026": "COALESCE(pr.fantasy_points_ppr, 0)",
        "games": "COALESCE(s.games, 0)",
    }
    sort_sql = sort_columns.get(sort, sort_columns["adp"])

    where = ["p.active=1"]
    parameters: list[Any] = [platform]

    if position:
        where.append("p.position=?")
        parameters.append(position)
    if query:
        where.append("(p.name LIKE ? OR p.team LIKE ? OR p.position LIKE ?)")
        token = f"%{query}%"
        parameters.extend([token, token, token])

    where_sql = " AND ".join(where)

    base_join = """
        FROM players p
        LEFT JOIN season_stats s
          ON s.player_key=p.player_key AND s.season=2025
        LEFT JOIN adp a
          ON a.player_key=p.player_key
         AND a.season=2026
         AND a.platform=?
        LEFT JOIN projections pr
          ON pr.player_key=p.player_key AND pr.season=2026
    """

    with connect() as db:
        total = db.execute(
            f"SELECT COUNT(*) {base_join} WHERE {where_sql}",
            parameters,
        ).fetchone()[0]

        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size

        rows = db.execute(
            f"""
            SELECT
                p.player_key,
                p.player_id,
                p.name,
                p.position,
                p.team,
                p.age,
                p.college,
                p.years_exp,
                p.status,
                p.injury_status,
                p.rookie,
                p.first_season,
                p.last_season,
                COALESCE(a.adp, 999) AS adp,
                COALESCE(a.position_adp, '') AS position_adp,
                COALESCE(s.games, 0) AS games,
                COALESCE(s.fantasy_points_ppr, 0) AS fantasy_points_ppr,
                COALESCE(s.passing_yards, 0) AS passing_yards,
                COALESCE(s.passing_tds, 0) AS passing_tds,
                COALESCE(s.rushing_yards, 0) AS rushing_yards,
                COALESCE(s.rushing_tds, 0) AS rushing_tds,
                COALESCE(s.receptions, 0) AS receptions,
                COALESCE(s.receiving_yards, 0) AS receiving_yards,
                COALESCE(s.receiving_tds, 0) AS receiving_tds,
                COALESCE(pr.fantasy_points_ppr, 0) AS proj_2026_ppr
            {base_join}
            WHERE {where_sql}
            ORDER BY {sort_sql} {direction}, p.name COLLATE NOCASE ASC
            LIMIT ? OFFSET ?
            """,
            [*parameters, page_size, offset],
        ).fetchall()

        count_rows = db.execute(
            """
            SELECT position, COUNT(*) AS count
            FROM players
            WHERE active=1 AND position IN ('QB','RB','WR','TE','K','DEF')
            GROUP BY position
            """
        ).fetchall()

        status = database_status()

        adp_source = db.execute(
            """
            SELECT source, MAX(updated_at) AS updated_at
            FROM adp
            WHERE season=2026 AND platform=?
            """,
            (platform,),
        ).fetchone()

    return jsonify(
        ok=True,
        platform=platform,
        selected_position=position or "ALL",
        count=total,
        returned_count=len(rows),
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        position_counts={row["position"]: row["count"] for row in count_rows},
        players=[dict(row) for row in rows],
        sources={
            "stats_2025": "SQLite historical database",
            "projections_2026": "SQLite projection database",
            "adp_2026": (
                adp_source["source"]
                if adp_source and adp_source["source"]
                else "not imported"
            ),
        },
        updated_at={
            "stats_2025": status.get("last_season") == 2025,
            "adp_2026": (
                adp_source["updated_at"]
                if adp_source else ""
            ),
        },
        warnings=[],
        database_status=status,
    )


@bp.get("/api/player-research-db/profile/<path:player_name>")
def profile_api(player_name: str):
    init_database()
    platform = str(request.args.get("platform") or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    player_key = _norm(player_name)

    with connect() as db:
        player = db.execute(
            "SELECT * FROM players WHERE player_key=?",
            (player_key,),
        ).fetchone()

        if not player:
            player = db.execute(
                "SELECT * FROM players WHERE name=? COLLATE NOCASE LIMIT 1",
                (player_name,),
            ).fetchone()

        if not player:
            return jsonify(ok=False, error="Player not found in database."), 404

        player_key = player["player_key"]
        history = db.execute(
            """
            SELECT *
            FROM season_stats
            WHERE player_key=?
            ORDER BY season ASC
            """,
            (player_key,),
        ).fetchall()

        adp = db.execute(
            """
            SELECT *
            FROM adp
            WHERE player_key=? AND season=2026 AND platform=?
            """,
            (player_key, platform),
        ).fetchone()

        projection = db.execute(
            """
            SELECT *
            FROM projections
            WHERE player_key=? AND season=2026
            """,
            (player_key,),
        ).fetchone()

        stats_2025 = next(
            (row for row in history if row["season"] == 2025),
            None,
        )

    projection_data = dict(projection) if projection else _fallback_projection(
        stats_2025,
        player["position"],
    )
    projection_data["season"] = 2026

    previous_year = dict(stats_2025) if stats_2025 else {
        field: 0 for field in STAT_FIELDS
    }

    return jsonify(
        ok=True,
        profile={
            "bio": {
                **dict(player),
                "adp": adp["adp"] if adp else 999,
                "position_adp": adp["position_adp"] if adp else "",
            },
            "previous_year": previous_year,
            "history": [dict(row) for row in history],
            "projection": projection_data,
            "injury": {
                "status": player["injury_status"] or "",
                "source": "current player database",
            },
            "news_available": True,
            "data_sources": [
                "SQLite players",
                "nflverse history",
                f"{platform} ADP" if adp else "ADP not imported",
            ],
        },
    )


def register(app):
    init_database()
    app.register_blueprint(bp)
