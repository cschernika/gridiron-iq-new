
from __future__ import annotations

import csv
import gzip
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
from html.parser import HTMLParser
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



_SUFFIX_PATTERN = re.compile(
    r"(?:\b(?:jr|sr|ii|iii|iv|v)\b\.?)$",
    re.IGNORECASE,
)


def _identity_base_name(value: Any) -> str:
    """
    Return a suffix-free display name for controlled identity comparisons.

    This is not used as the universal database key because doing that would
    incorrectly combine different generations of players. It is only used by
    the guarded alias-repair routine below.
    """
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = _SUFFIX_PATTERN.sub("", text).strip(" ,.-")
    return text


def _identity_base_key(value: Any) -> str:
    return _norm(_identity_base_name(value))


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

        # Add richer ADP source fields to existing databases without requiring
        # the persistent SQLite file to be deleted.
        existing_adp_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(adp)").fetchall()
        }
        if "adp_type" not in existing_adp_columns:
            db.execute("ALTER TABLE adp ADD COLUMN adp_type TEXT")
        if "platform_adp" not in existing_adp_columns:
            db.execute("ALTER TABLE adp ADD COLUMN platform_adp REAL")
        if "consensus_adp" not in existing_adp_columns:
            db.execute("ALTER TABLE adp ADD COLUMN consensus_adp REAL")


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




def repair_exact_player_duplicates() -> dict[str, Any]:
    """
    Merge duplicate records whose display names differ only by punctuation,
    spacing, or capitalization, while requiring the same fantasy position.

    Examples:
      C.J. Stroud
      CJ Stroud
      C J Stroud

    Statistics, ADP, projections and current bio data are consolidated onto
    one canonical player record.
    """
    init_database()
    now = datetime.now(timezone.utc).isoformat()
    merged: list[dict[str, Any]] = []

    with connect() as connection:
        players = connection.execute(
            """
            SELECT
                p.*,
                (SELECT COUNT(*) FROM season_stats s
                 WHERE s.player_key=p.player_key) AS stats_count,
                (SELECT COUNT(*) FROM adp a
                 WHERE a.player_key=p.player_key AND a.season=2026) AS adp_count,
                (SELECT COUNT(*) FROM projections pr
                 WHERE pr.player_key=p.player_key AND pr.season=2026) AS projection_count
            FROM players p
            WHERE p.position IN ('QB','RB','WR','TE','K','DEF')
            """
        ).fetchall()

        groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for player in players:
            compact_name = _norm(player["name"])
            if compact_name:
                groups[(compact_name, player["position"])].append(player)

        for (compact_name, position), candidates in groups.items():
            if len(candidates) < 2:
                continue

            def canonical_score(row: sqlite3.Row) -> tuple[int, int, int, int, int]:
                team = str(row["team"] or "").upper()
                current_team = int(bool(team and team != "FA"))
                current_bio = int(
                    bool(row["player_id"])
                    or row["years_exp"] is not None
                    or row["age"] is not None
                    or bool(row["status"])
                )
                data_total = int(row["stats_count"] or 0) + int(
                    row["adp_count"] or 0
                ) + int(row["projection_count"] or 0)
                has_adp = int((row["adp_count"] or 0) > 0)
                clean_display = int("." not in str(row["name"] or ""))
                return (
                    current_bio,
                    has_adp,
                    current_team,
                    data_total,
                    clean_display,
                )

            canonical = max(candidates, key=canonical_score)
            canonical_key = canonical["player_key"]

            for duplicate in candidates:
                duplicate_key = duplicate["player_key"]
                if duplicate_key == canonical_key:
                    continue

                # Merge the strongest available bio/current-team fields first.
                connection.execute(
                    """
                    UPDATE players
                    SET
                        player_id=CASE
                            WHEN player_id IS NULL OR player_id=''
                            THEN ? ELSE player_id END,
                        team=CASE
                            WHEN (team IS NULL OR team='' OR team='FA')
                                 AND ?<>'' AND ?<>'FA'
                            THEN ? ELSE team END,
                        age=COALESCE(age, ?),
                        college=CASE
                            WHEN college IS NULL OR college=''
                            THEN ? ELSE college END,
                        years_exp=COALESCE(years_exp, ?),
                        status=CASE
                            WHEN status IS NULL OR status=''
                            THEN ? ELSE status END,
                        injury_status=CASE
                            WHEN injury_status IS NULL OR injury_status=''
                            THEN ? ELSE injury_status END,
                        rookie=MAX(rookie, ?),
                        active=MAX(active, ?),
                        updated_at=?
                    WHERE player_key=?
                    """,
                    (
                        duplicate["player_id"] or "",
                        duplicate["team"] or "",
                        duplicate["team"] or "",
                        duplicate["team"] or "",
                        duplicate["age"],
                        duplicate["college"] or "",
                        duplicate["years_exp"],
                        duplicate["status"] or "",
                        duplicate["injury_status"] or "",
                        int(duplicate["rookie"] or 0),
                        int(duplicate["active"] or 0),
                        now,
                        canonical_key,
                    ),
                )

                connection.execute(
                    """
                    INSERT INTO season_stats(
                        player_key, season, team, position,
                        games, completions, attempts, passing_yards,
                        passing_tds, interceptions, carries, rushing_yards,
                        rushing_tds, targets, receptions, receiving_yards,
                        receiving_tds, fantasy_points, fantasy_points_ppr,
                        source, updated_at
                    )
                    SELECT
                        ?, season, team, position,
                        games, completions, attempts, passing_yards,
                        passing_tds, interceptions, carries, rushing_yards,
                        rushing_tds, targets, receptions, receiving_yards,
                        receiving_tds, fantasy_points, fantasy_points_ppr,
                        source, ?
                    FROM season_stats
                    WHERE player_key=?
                    ON CONFLICT(player_key, season) DO UPDATE SET
                        team=CASE
                            WHEN excluded.games >= season_stats.games
                            THEN excluded.team ELSE season_stats.team END,
                        position=excluded.position,
                        games=MAX(season_stats.games, excluded.games),
                        completions=MAX(season_stats.completions, excluded.completions),
                        attempts=MAX(season_stats.attempts, excluded.attempts),
                        passing_yards=MAX(season_stats.passing_yards, excluded.passing_yards),
                        passing_tds=MAX(season_stats.passing_tds, excluded.passing_tds),
                        interceptions=MAX(season_stats.interceptions, excluded.interceptions),
                        carries=MAX(season_stats.carries, excluded.carries),
                        rushing_yards=MAX(season_stats.rushing_yards, excluded.rushing_yards),
                        rushing_tds=MAX(season_stats.rushing_tds, excluded.rushing_tds),
                        targets=MAX(season_stats.targets, excluded.targets),
                        receptions=MAX(season_stats.receptions, excluded.receptions),
                        receiving_yards=MAX(season_stats.receiving_yards, excluded.receiving_yards),
                        receiving_tds=MAX(season_stats.receiving_tds, excluded.receiving_tds),
                        fantasy_points=MAX(season_stats.fantasy_points, excluded.fantasy_points),
                        fantasy_points_ppr=MAX(season_stats.fantasy_points_ppr, excluded.fantasy_points_ppr),
                        source=excluded.source,
                        updated_at=excluded.updated_at
                    """,
                    (canonical_key, now, duplicate_key),
                )

                connection.execute(
                    """
                    INSERT INTO adp(
                        player_key, season, platform, adp, position_adp,
                        rank_value, source, updated_at, adp_type,
                        platform_adp, consensus_adp
                    )
                    SELECT
                        ?, season, platform, adp, position_adp,
                        rank_value, source, ?, adp_type,
                        platform_adp, consensus_adp
                    FROM adp
                    WHERE player_key=?
                    ON CONFLICT(player_key, season, platform) DO UPDATE SET
                        adp=MIN(adp.adp, excluded.adp),
                        position_adp=CASE
                            WHEN adp.position_adp IS NULL OR adp.position_adp=''
                            THEN excluded.position_adp
                            ELSE adp.position_adp
                        END,
                        rank_value=COALESCE(adp.rank_value, excluded.rank_value),
                        source=CASE
                            WHEN excluded.updated_at >= adp.updated_at
                            THEN excluded.source ELSE adp.source END,
                        updated_at=MAX(adp.updated_at, excluded.updated_at),
                        adp_type=COALESCE(excluded.adp_type, adp.adp_type),
                        platform_adp=COALESCE(
                            excluded.platform_adp,
                            adp.platform_adp
                        ),
                        consensus_adp=COALESCE(
                            excluded.consensus_adp,
                            adp.consensus_adp
                        )
                    """,
                    (canonical_key, now, duplicate_key),
                )

                connection.execute(
                    """
                    INSERT INTO projections(
                        player_key, season, games, passing_yards, passing_tds,
                        interceptions, carries, rushing_yards, rushing_tds,
                        targets, receptions, receiving_yards, receiving_tds,
                        fantasy_points_ppr, method, source, updated_at
                    )
                    SELECT
                        ?, season, games, passing_yards, passing_tds,
                        interceptions, carries, rushing_yards, rushing_tds,
                        targets, receptions, receiving_yards, receiving_tds,
                        fantasy_points_ppr, method, source, ?
                    FROM projections
                    WHERE player_key=?
                    ON CONFLICT(player_key, season) DO UPDATE SET
                        games=MAX(projections.games, excluded.games),
                        passing_yards=MAX(projections.passing_yards, excluded.passing_yards),
                        passing_tds=MAX(projections.passing_tds, excluded.passing_tds),
                        interceptions=MAX(projections.interceptions, excluded.interceptions),
                        carries=MAX(projections.carries, excluded.carries),
                        rushing_yards=MAX(projections.rushing_yards, excluded.rushing_yards),
                        rushing_tds=MAX(projections.rushing_tds, excluded.rushing_tds),
                        targets=MAX(projections.targets, excluded.targets),
                        receptions=MAX(projections.receptions, excluded.receptions),
                        receiving_yards=MAX(projections.receiving_yards, excluded.receiving_yards),
                        receiving_tds=MAX(projections.receiving_tds, excluded.receiving_tds),
                        fantasy_points_ppr=MAX(
                            projections.fantasy_points_ppr,
                            excluded.fantasy_points_ppr
                        ),
                        method=excluded.method,
                        source=excluded.source,
                        updated_at=excluded.updated_at
                    """,
                    (canonical_key, now, duplicate_key),
                )

                connection.execute(
                    "DELETE FROM season_stats WHERE player_key=?",
                    (duplicate_key,),
                )
                connection.execute(
                    "DELETE FROM adp WHERE player_key=?",
                    (duplicate_key,),
                )
                connection.execute(
                    "DELETE FROM projections WHERE player_key=?",
                    (duplicate_key,),
                )
                connection.execute(
                    "DELETE FROM players WHERE player_key=?",
                    (duplicate_key,),
                )

                seasons = connection.execute(
                    """
                    SELECT MIN(season), MAX(season)
                    FROM season_stats
                    WHERE player_key=?
                    """,
                    (canonical_key,),
                ).fetchone()

                connection.execute(
                    """
                    UPDATE players
                    SET first_season=?, last_season=?, updated_at=?
                    WHERE player_key=?
                    """,
                    (seasons[0], seasons[1], now, canonical_key),
                )

                merged.append(
                    {
                        "canonical": canonical["name"],
                        "duplicate": duplicate["name"],
                        "position": position,
                        "career_rows_moved": int(duplicate["stats_count"] or 0),
                        "adp_rows_moved": int(duplicate["adp_count"] or 0),
                    }
                )

        _set_status(
            connection,
            "exact_duplicate_repair",
            {
                "merged_count": len(merged),
                "records": merged[:100],
            },
        )

    return {
        "ok": True,
        "merged_count": len(merged),
        "records": merged,
    }


def repair_recent_player_aliases() -> dict[str, Any]:
    """
    Merge recent suffix/name variants that represent the same NFL player.

    Examples:
      Kenneth Walker / Kenneth Walker III
      Brian Robinson / Brian Robinson Jr.

    Safety rules:
      - same fantasy position
      - historical record must include 2020 or later
      - career window must be compatible with current years_exp
      - aliases are never merged solely because their suffix-free names match

    These rules prevent old-generation collisions such as Marvin Harrison and
    Marvin Harrison Jr.
    """
    init_database()
    now = datetime.now(timezone.utc).isoformat()
    merged_pairs: list[dict[str, Any]] = []

    with connect() as connection:
        players = connection.execute(
            """
            SELECT
                p.*,
                (
                    SELECT MIN(s.season)
                    FROM season_stats s
                    WHERE s.player_key=p.player_key
                ) AS stats_first_season,
                (
                    SELECT MAX(s.season)
                    FROM season_stats s
                    WHERE s.player_key=p.player_key
                ) AS stats_last_season,
                (
                    SELECT COUNT(*)
                    FROM season_stats s
                    WHERE s.player_key=p.player_key
                ) AS stats_count
            FROM players p
            WHERE p.position IN ('QB','RB','WR','TE','K','DEF')
            """
        ).fetchall()

        grouped: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for player in players:
            base_key = _identity_base_key(player["name"])
            if base_key:
                grouped[(base_key, player["position"])].append(player)

        for (base_key, position), candidates in grouped.items():
            if len(candidates) < 2:
                continue

            recent_history = [
                row for row in candidates
                if row["stats_last_season"] is not None
                and int(row["stats_last_season"]) >= 2020
            ]
            if not recent_history:
                continue

            # Prefer the row carrying current roster/bio information. A record
            # with years_exp, age, injury status, or a team different from its
            # latest historical team is usually the modern directory record.
            def current_score(row: sqlite3.Row) -> tuple[int, int, int, int]:
                team = str(row["team"] or "").upper()
                has_current_team = int(bool(team and team != "FA"))
                has_bio = int(
                    row["years_exp"] is not None
                    or row["age"] is not None
                    or bool(row["injury_status"])
                    or bool(row["status"])
                )
                suffix = int(
                    _identity_base_key(row["name"]) != _norm(row["name"])
                )
                no_history = int((row["stats_count"] or 0) == 0)
                return (has_bio, no_history, suffix, has_current_team)

            canonical = max(candidates, key=current_score)
            canonical_key = canonical["player_key"]

            years_exp = _number(canonical["years_exp"])
            expected_first = (
                max(2020, 2026 - int(math.ceil(years_exp)) - 1)
                if years_exp > 0
                else 2020
            )

            for alias in candidates:
                alias_key = alias["player_key"]
                if alias_key == canonical_key:
                    continue

                alias_last = alias["stats_last_season"]
                alias_first = alias["stats_first_season"]
                alias_count = int(alias["stats_count"] or 0)

                if alias_count <= 0 or alias_last is None:
                    continue
                if int(alias_last) < 2020:
                    continue
                if alias_first is not None and int(alias_first) < expected_first:
                    continue

                # Only merge a true suffix difference or a punctuation-only
                # variation. Do not merge arbitrary players sharing a base.
                canonical_base = _identity_base_name(canonical["name"]).lower()
                alias_base = _identity_base_name(alias["name"]).lower()
                if canonical_base != alias_base:
                    continue

                connection.execute(
                    """
                    INSERT INTO season_stats(
                        player_key, season, team, position,
                        games, completions, attempts, passing_yards,
                        passing_tds, interceptions, carries, rushing_yards,
                        rushing_tds, targets, receptions, receiving_yards,
                        receiving_tds, fantasy_points, fantasy_points_ppr,
                        source, updated_at
                    )
                    SELECT
                        ?, season, team, position,
                        games, completions, attempts, passing_yards,
                        passing_tds, interceptions, carries, rushing_yards,
                        rushing_tds, targets, receptions, receiving_yards,
                        receiving_tds, fantasy_points, fantasy_points_ppr,
                        source, ?
                    FROM season_stats
                    WHERE player_key=?
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
                    (canonical_key, now, alias_key),
                )

                connection.execute(
                    """
                    INSERT INTO adp(
                        player_key, season, platform, adp, position_adp,
                        rank_value, source, updated_at, adp_type,
                        platform_adp, consensus_adp
                    )
                    SELECT
                        ?, season, platform, adp, position_adp,
                        rank_value, source, ?, adp_type,
                        platform_adp, consensus_adp
                    FROM adp
                    WHERE player_key=?
                    ON CONFLICT(player_key, season, platform) DO UPDATE SET
                        adp=excluded.adp,
                        position_adp=CASE
                            WHEN excluded.position_adp<>'' THEN excluded.position_adp
                            ELSE adp.position_adp
                        END,
                        rank_value=COALESCE(excluded.rank_value, adp.rank_value),
                        source=excluded.source,
                        updated_at=excluded.updated_at
                    """,
                    (canonical_key, now, alias_key),
                )

                connection.execute(
                    """
                    INSERT INTO projections(
                        player_key, season, games, passing_yards, passing_tds,
                        interceptions, carries, rushing_yards, rushing_tds,
                        targets, receptions, receiving_yards, receiving_tds,
                        fantasy_points_ppr, method, source, updated_at
                    )
                    SELECT
                        ?, season, games, passing_yards, passing_tds,
                        interceptions, carries, rushing_yards, rushing_tds,
                        targets, receptions, receiving_yards, receiving_tds,
                        fantasy_points_ppr, method, source, ?
                    FROM projections
                    WHERE player_key=?
                    ON CONFLICT(player_key, season) DO UPDATE SET
                        games=excluded.games,
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
                        fantasy_points_ppr=excluded.fantasy_points_ppr,
                        method=excluded.method,
                        source=excluded.source,
                        updated_at=excluded.updated_at
                    """,
                    (canonical_key, now, alias_key),
                )

                connection.execute(
                    "DELETE FROM season_stats WHERE player_key=?",
                    (alias_key,),
                )
                connection.execute(
                    "DELETE FROM adp WHERE player_key=?",
                    (alias_key,),
                )
                connection.execute(
                    "DELETE FROM projections WHERE player_key=?",
                    (alias_key,),
                )

                seasons = connection.execute(
                    """
                    SELECT MIN(season), MAX(season)
                    FROM season_stats
                    WHERE player_key=?
                    """,
                    (canonical_key,),
                ).fetchone()

                connection.execute(
                    """
                    UPDATE players
                    SET
                        first_season=?,
                        last_season=?,
                        updated_at=?
                    WHERE player_key=?
                    """,
                    (seasons[0], seasons[1], now, canonical_key),
                )

                # Remove the empty duplicate player row only after all related
                # data has moved successfully.
                connection.execute(
                    "DELETE FROM players WHERE player_key=?",
                    (alias_key,),
                )

                merged_pairs.append(
                    {
                        "canonical": canonical["name"],
                        "alias": alias["name"],
                        "position": position,
                        "first_season": seasons[0],
                        "last_season": seasons[1],
                    }
                )

        _set_status(
            connection,
            "player_alias_repair",
            {
                "merged_count": len(merged_pairs),
                "pairs": merged_pairs[:100],
            },
        )

    return {
        "ok": True,
        "merged_count": len(merged_pairs),
        "pairs": merged_pairs,
    }


def import_current_players() -> int:
    """
    Import current teams and player bio data.

    Source priority:
      1. Sleeper current player directory
      2. 2026 master player file
      3. saved ESPN/Yahoo ADP datasets

    Newer team sources are applied after historical imports, so a player's
    current team is never replaced by the last team from an older season.
    """
    init_database()
    now = datetime.now(timezone.utc).isoformat()
    merged: dict[str, dict[str, Any]] = {}

    def merge_player(
        name: str,
        *,
        source_priority: int,
        player_id: str = "",
        position: str = "",
        team: str = "",
        age: Any = None,
        college: str = "",
        years_exp: Any = None,
        status: str = "",
        injury_status: str = "",
        rookie: bool = False,
        active: bool = True,
    ) -> None:
        name = str(name or "").strip()
        if not name:
            return

        key = _norm(name)
        pos = _position(position)
        team_value = str(team or "").upper().strip()
        if team_value in {"N/A", "NONE", "NULL"}:
            team_value = ""

        record = merged.setdefault(
            key,
            {
                "player_key": key,
                "player_id": "",
                "name": name,
                "position": "",
                "team": "",
                "age": None,
                "college": "",
                "years_exp": None,
                "status": "",
                "injury_status": "",
                "rookie": False,
                "active": True,
                "_team_priority": -1,
                "_position_priority": -1,
                "_bio_priority": -1,
            },
        )

        record["name"] = name

        if player_id and source_priority >= record["_bio_priority"]:
            record["player_id"] = str(player_id)

        if pos and source_priority >= record["_position_priority"]:
            record["position"] = pos
            record["_position_priority"] = source_priority

        if (
            team_value
            and team_value != "FA"
            and source_priority >= record["_team_priority"]
        ):
            record["team"] = team_value
            record["_team_priority"] = source_priority
        elif not record["team"] and team_value:
            record["team"] = team_value

        if source_priority >= record["_bio_priority"]:
            if age not in (None, ""):
                record["age"] = _number(age) or None
            if college:
                record["college"] = str(college)
            if years_exp not in (None, ""):
                record["years_exp"] = _number(years_exp) or None
            if status:
                record["status"] = str(status)
            if injury_status:
                record["injury_status"] = str(injury_status)
            record["rookie"] = bool(rookie)
            record["active"] = bool(active)
            record["_bio_priority"] = source_priority

    # Sleeper current player directory.
    cache_path = DATA_DIR / "sleeper_players_cache.json"
    sleeper_payload: dict[str, Any] = {}

    try:
        if cache_path.exists():
            sleeper_payload = _load_json(cache_path)
    except Exception:
        sleeper_payload = {}

    try:
        response = requests.get(
            "https://api.sleeper.app/v1/players/nfl",
            headers={"User-Agent": "Gridiron-IQ/2026"},
            timeout=(10, 45),
        )
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict) and result:
            sleeper_payload = result
            cache_path.write_text(
                json.dumps(sleeper_payload, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception:
        pass

    for player_id, player in sleeper_payload.items():
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

        team = str(player.get("team") or "").upper()
        status = str(player.get("status") or "")
        active = (
            player.get("active") is True
            or bool(team)
            or status.lower() in {
                "active",
                "injured reserve",
                "pup",
                "suspended",
                "non-football injury",
            }
        )

        if not active:
            continue

        merge_player(
            name,
            source_priority=30,
            player_id=str(player_id),
            position=position,
            team=team,
            age=player.get("age"),
            college=player.get("college") or "",
            years_exp=player.get("years_exp"),
            status=status,
            injury_status=player.get("injury_status") or "",
            rookie=bool(player.get("rookie")),
            active=True,
        )

    # 2026 master player database can contain newer team assignments.
    master_path = DATA_DIR / "nfl_players_2026.json"
    master_payload = _load_json(master_path)
    for _, player in (master_payload.get("players", {}) or {}).items():
        if not isinstance(player, dict):
            continue
        name = str(player.get("name") or player.get("full_name") or "").strip()
        position = _position(player.get("position"))
        if not name or not position:
            continue

        merge_player(
            name,
            source_priority=40,
            player_id=str(
                player.get("sleeper_id")
                or player.get("player_id")
                or ""
            ),
            position=position,
            team=player.get("team") or "",
            age=player.get("age"),
            college=player.get("college") or "",
            years_exp=player.get("years_exp"),
            status=player.get("status") or "",
            injury_status=player.get("injury_status") or "",
            rookie=bool(player.get("rookie")),
            active=True,
        )

    # Authenticated ESPN ADP is the strongest available current team signal.
    for platform, priority in (("ESPN", 60), ("YAHOO", 50)):
        for candidate in _adp_candidates(platform):
            payload = _load_json(candidate)
            if not payload.get("players"):
                continue
            for _, player in payload.get("players", {}).items():
                if not isinstance(player, dict):
                    continue
                name = str(
                    player.get("name")
                    or player.get("player_name")
                    or ""
                ).strip()
                position = _position(
                    player.get("position")
                    or player.get("pos")
                )
                if not name or not position:
                    continue

                merge_player(
                    name,
                    source_priority=priority,
                    player_id=str(player.get("player_id") or ""),
                    position=position,
                    team=player.get("team") or "",
                    active=True,
                )
            break

    rows = []
    for record in merged.values():
        rows.append(
            (
                record["player_key"],
                record["player_id"],
                record["name"],
                record["position"],
                record["team"] or "FA",
                record["age"],
                record["college"],
                record["years_exp"],
                record["status"],
                record["injury_status"],
                1 if record["rookie"] else 0,
                1 if record["active"] else 0,
                now,
            )
        )

    with connect() as connection:
        connection.executemany(
            """
            INSERT INTO players(
                player_key, player_id, name, position, team, age, college,
                years_exp, status, injury_status, rookie, active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                player_id=CASE
                    WHEN excluded.player_id<>'' THEN excluded.player_id
                    ELSE players.player_id
                END,
                name=excluded.name,
                position=CASE
                    WHEN excluded.position<>'' THEN excluded.position
                    ELSE players.position
                END,
                team=CASE
                    WHEN excluded.team<>'' AND excluded.team<>'FA'
                    THEN excluded.team
                    ELSE players.team
                END,
                age=COALESCE(excluded.age, players.age),
                college=CASE
                    WHEN excluded.college<>'' THEN excluded.college
                    ELSE players.college
                END,
                years_exp=COALESCE(excluded.years_exp, players.years_exp),
                status=CASE
                    WHEN excluded.status<>'' THEN excluded.status
                    ELSE players.status
                END,
                injury_status=CASE
                    WHEN excluded.injury_status<>'' THEN excluded.injury_status
                    ELSE players.injury_status
                END,
                rookie=excluded.rookie,
                active=excluded.active,
                updated_at=excluded.updated_at
            """,
            rows,
        )
        _set_status(
            connection,
            "current_players",
            {"count": len(rows), "source": "Sleeper + 2026 master + saved ADP"},
        )

    # Consolidate punctuation variants, then suffix variants.
    repair_exact_player_duplicates()
    repair_recent_player_aliases()
    return len(rows)


def _season_asset_candidates(season: int) -> list[dict[str, Any]]:
    """Return direct nflverse release assets without calling api.github.com.

    Render services can share outbound IP addresses, so unauthenticated GitHub
    API discovery can be rate-limited even when this app made few requests.
    These stable release-download URLs avoid the API entirely.
    """
    season_text = str(int(season))
    release_base = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "stats_player"
    )
    names = [
        f"stats_player_reg_{season_text}.csv",
        f"stats_player_reg_{season_text}.csv.gz",
        f"stats_player_week_{season_text}.csv",
        f"stats_player_week_{season_text}.csv.gz",
    ]
    return [
        {
            "name": name,
            "url": f"{release_base}/{name}",
            "size": 0,
        }
        for name in names
    ]

def _valid_stats_headers(fieldnames: list[str] | None) -> bool:
    fields = {str(field or "").strip() for field in (fieldnames or [])}
    has_name = bool(
        fields.intersection(
            {"player_display_name", "player_name", "full_name", "name"}
        )
    )
    has_stats = bool(
        fields.intersection(
            {
                "passing_yards",
                "rushing_yards",
                "receiving_yards",
                "fantasy_points",
                "fantasy_points_ppr",
            }
        )
    )
    return has_name and has_stats


def _decode_stats_asset(content: bytes, filename: str) -> str:
    if filename.lower().endswith(".gz"):
        content = gzip.decompress(content)
    return content.decode("utf-8-sig", errors="replace")


def _read_cached_stats(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size < 500:
        return []

    try:
        text = path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text))
        if not _valid_stats_headers(reader.fieldnames):
            return []
        rows = list(reader)
        return rows if rows else []
    except Exception:
        return []


def _download_season_rows(season: int) -> list[dict[str, str]]:
    cache_path = DATA_DIR / f"player_stats_{season}.csv"
    cached_rows = _read_cached_stats(cache_path)
    if cached_rows:
        return cached_rows

    # Remove an invalid HTML/error/cache file so it cannot be reused.
    try:
        if cache_path.exists():
            cache_path.unlink()
    except Exception:
        pass

    candidates = _season_asset_candidates(season)
    if not candidates:
        raise RuntimeError(
            f"No official nflverse Player Summary Stats CSV asset was found for {season}."
        )

    errors = []

    for asset in candidates:
        try:
            response = requests.get(
                asset["url"],
                headers={"User-Agent": "Gridiron-IQ/2026"},
                timeout=(10, 120),
            )
            response.raise_for_status()

            text = _decode_stats_asset(response.content, asset["name"])
            reader = csv.DictReader(io.StringIO(text))

            if not _valid_stats_headers(reader.fieldnames):
                errors.append(
                    f"{asset['name']}: required player-stat columns were missing"
                )
                continue

            rows = list(reader)
            if not rows:
                errors.append(f"{asset['name']}: no rows")
                continue

            cache_path.write_text(text, encoding="utf-8")
            return rows
        except Exception as exc:
            errors.append(f"{asset['name']}: {exc}")

    raise RuntimeError(
        f"Unable to import {season} nflverse player statistics: "
        + " | ".join(errors[-6:])
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

    result = {field: 0.0 for field in STAT_FIELDS}

    # Summary assets normally contain one row per player/season. Weekly assets
    # contain one row per week and must be summed.
    weekly_data = any(
        row.get("week") not in (None, "")
        for row in rows
    )

    for field in STAT_FIELDS:
        values = [_number(row.get(field)) for row in rows]

        if field == "games":
            if weekly_data:
                result[field] = sum(
                    1
                    for row in rows
                    if (
                        _number(row.get("snap_count")) > 0
                        or _number(row.get("attempts")) > 0
                        or _number(row.get("carries")) > 0
                        or _number(row.get("targets")) > 0
                        or _number(row.get("fantasy_points_ppr")) != 0
                    )
                )
                if result[field] <= 0:
                    result[field] = len(
                        {
                            row.get("week")
                            for row in rows
                            if row.get("week") not in (None, "")
                        }
                    )
            else:
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

    # A season import may introduce punctuation or suffix variants.
    repair_exact_player_duplicates()
    repair_recent_player_aliases()
    return len(stat_rows)



def _official_regular_season_url(season: int) -> str:
    return (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"stats_player/stats_player_reg_{int(season)}.csv"
    )


def _download_official_regular_season(
    season: int,
    *,
    force_refresh: bool = False,
) -> list[dict[str, str]]:
    """
    Download the official nflverse regular-season player summary for one year.
    """
    cache_path = DATA_DIR / f"stats_player_reg_{int(season)}.csv"

    if force_refresh and cache_path.exists():
        try:
            cache_path.unlink()
        except Exception:
            pass

    cached_rows = _read_cached_stats(cache_path)
    if cached_rows:
        cached_seasons = {
            int(float(row.get("season") or season))
            for row in cached_rows
            if str(row.get("season") or season).strip()
        }
        if cached_seasons == {int(season)}:
            return cached_rows

    url = _official_regular_season_url(season)
    response = requests.get(
        url,
        headers={
            "User-Agent": "Gridiron-IQ/2026",
            "Accept": "text/csv,*/*",
            "Cache-Control": "no-cache",
        },
        timeout=(15, 120),
    )
    response.raise_for_status()

    text = response.content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    if not _valid_stats_headers(reader.fieldnames):
        raise RuntimeError(
            f"{season}: nflverse file did not contain player-stat columns"
        )

    rows = list(reader)
    if not rows:
        raise RuntimeError(f"{season}: nflverse file contained no rows")

    wrong_seasons = {
        int(float(row.get("season") or season))
        for row in rows
        if str(row.get("season") or season).strip()
    }
    if wrong_seasons != {int(season)}:
        raise RuntimeError(
            f"{season}: downloaded file contained seasons "
            f"{sorted(wrong_seasons)}"
        )

    cache_path.write_text(text, encoding="utf-8")
    return rows


def _historical_identity_key(row: dict[str, Any]) -> str:
    """
    Prefer nflverse's stable GSIS player ID for grouping within an import.
    Fall back to the normalized display name when an ID is unavailable.
    """
    player_id = str(
        row.get("player_id")
        or row.get("gsis_id")
        or ""
    ).strip()
    if player_id:
        return f"id:{player_id}"

    return f"name:{_norm(_row_name(row))}"


def import_complete_history(
    start_season: int = 1999,
    end_season: int = 2025,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Import each official nflverse regular-season summary file independently.

    Success is not reported unless more than one season is stored when the
    requested range contains more than one season.
    """
    init_database()
    start_season = max(1999, int(start_season))
    end_season = min(2025, int(end_season))

    imported: dict[str, int] = {}
    failures: dict[str, str] = {}
    all_rows: list[tuple[int, dict[str, Any]]] = []

    for season in range(start_season, end_season + 1):
        try:
            rows = _download_official_regular_season(
                season,
                force_refresh=force_refresh,
            )
            imported[str(season)] = len(rows)
            all_rows.extend((season, row) for row in rows)
        except Exception as exc:
            failures[str(season)] = str(exc)

    if not all_rows:
        raise RuntimeError(
            "No official nflverse regular-season files were imported. "
            + json.dumps(failures, ensure_ascii=False)
        )

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    identity_names: dict[str, str] = {}
    identity_ids: dict[str, str] = {}

    for season, row in all_rows:
        name = _row_name(row)
        if not name:
            continue

        identity = _historical_identity_key(row)
        grouped[(identity, season)].append(row)
        identity_names[identity] = name

        player_id = str(
            row.get("player_id")
            or row.get("gsis_id")
            or ""
        ).strip()
        if player_id:
            identity_ids[identity] = player_id

    now = datetime.now(timezone.utc).isoformat()
    player_accumulator: dict[str, dict[str, Any]] = {}
    stat_rows = []

    # Map GSIS IDs already present in players to their current canonical keys.
    with connect() as connection:
        existing_by_id = {
            str(row["player_id"]): str(row["player_key"])
            for row in connection.execute(
                """
                SELECT player_id, player_key
                FROM players
                WHERE player_id IS NOT NULL AND player_id<>''
                """
            ).fetchall()
        }

    for (identity, season), matches in grouped.items():
        first = matches[0]
        name = identity_names.get(identity) or _row_name(first)
        player_id = identity_ids.get(identity, "")

        canonical_key = (
            existing_by_id.get(player_id)
            if player_id
            else None
        ) or _norm(name)

        position = _position(
            first.get("position")
            or first.get("position_group")
        )

        teams = [
            str(
                row.get("team")
                or row.get("recent_team")
                or ""
            ).upper().strip()
            for row in matches
            if str(
                row.get("team")
                or row.get("recent_team")
                or ""
            ).strip()
        ]
        team = teams[-1] if teams else "FA"
        stats = _aggregate_rows(matches, name)

        stat_rows.append(
            (
                canonical_key,
                season,
                team,
                position,
                *[stats[field] for field in STAT_FIELDS],
                f"nflverse stats_player_reg_{season}.csv",
                now,
            )
        )

        current = player_accumulator.get(canonical_key)
        if current is None:
            player_accumulator[canonical_key] = {
                "player_key": canonical_key,
                "player_id": player_id,
                "name": name,
                "position": position,
                "team": team,
                "first_season": season,
                "last_season": season,
            }
        else:
            current["first_season"] = min(
                current["first_season"],
                season,
            )
            if season >= current["last_season"]:
                current["last_season"] = season
                if position:
                    current["position"] = position
            if not current["player_id"] and player_id:
                current["player_id"] = player_id

    player_rows = [
        (
            row["player_key"],
            row["player_id"],
            row["name"],
            row["position"],
            row["team"] or "FA",
            1,
            row["first_season"],
            row["last_season"],
            now,
        )
        for row in player_accumulator.values()
    ]

    with connect() as connection:
        connection.executemany(
            """
            INSERT INTO players(
                player_key, player_id, name, position, team, active,
                first_season, last_season, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                player_id=CASE
                    WHEN excluded.player_id<>'' THEN excluded.player_id
                    ELSE players.player_id
                END,
                name=excluded.name,
                position=CASE
                    WHEN excluded.position<>'' THEN excluded.position
                    ELSE players.position
                END,
                active=MAX(players.active, excluded.active),
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

        connection.executemany(
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

        stored = connection.execute(
            """
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT player_key) AS player_count,
                COUNT(DISTINCT season) AS season_count,
                MIN(season) AS first_season,
                MAX(season) AS last_season
            FROM season_stats
            """
        ).fetchone()

        season_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT season, COUNT(*) AS player_count
                FROM season_stats
                GROUP BY season
                ORDER BY season
                """
            ).fetchall()
        ]

        _set_status(
            connection,
            "complete_history",
            {
                "downloaded_seasons": sorted(int(x) for x in imported),
                "failed_seasons": failures,
                "stored_rows": stored["row_count"],
                "stored_players": stored["player_count"],
                "stored_seasons": stored["season_count"],
                "first_season": stored["first_season"],
                "last_season": stored["last_season"],
                "season_rows": season_rows,
            },
        )

    exact_result = repair_exact_player_duplicates()
    suffix_result = repair_recent_player_aliases()

    requested_count = end_season - start_season + 1
    enough_seasons = (
        stored["season_count"] > 1
        if requested_count > 1
        else stored["season_count"] == 1
    )

    return {
        "ok": bool(stat_rows) and enough_seasons,
        "imported_file_count": len(imported),
        "imported_files": imported,
        "failures": failures,
        "stored_rows": stored["row_count"],
        "stored_players": stored["player_count"],
        "stored_seasons": stored["season_count"],
        "first_stored_season": stored["first_season"],
        "last_stored_season": stored["last_season"],
        "season_rows": season_rows,
        "exact_duplicate_merges": exact_result.get("merged_count", 0),
        "suffix_merges": suffix_result.get("merged_count", 0),
        "message": (
            f"Imported {stored['season_count']} seasons and "
            f"{stored['row_count']} player-season rows."
            if enough_seasons
            else "Import completed but SQLite still contains only one season."
        ),
    }



def import_all_history(start_season: int = 1999, end_season: int = 2025) -> dict[str, Any]:
    try:
        complete = import_complete_history(start_season, end_season)
        return {
            "imported": {
                "complete_history": complete.get("imported_rows", 0)
            },
            "failures": {},
            "season_count": complete.get("stored_seasons", 0),
            "complete_history": complete,
        }
    except Exception as complete_exc:
        imported = {}
        failures = {
            "complete_history": str(complete_exc)
        }

        # Retain the old per-season importer as a fallback.
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




class _PublicAdpTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"} and self._cell_parts is not None:
            value = re.sub(r"\s+", " ", " ".join(self._cell_parts)).strip()
            if self._row is not None:
                self._row.append(value)
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            if self._table is not None and any(cell.strip() for cell in self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def _clean_public_name(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b[A-Z]\.\s+(?=[A-Z][a-z])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # FantasyPros repeats an abbreviated version after the full name.
    # Keep the first name sequence before a duplicate initial/surname pattern.
    duplicate = re.search(r"\s+[A-Z]\.\s+[A-Z][A-Za-z'’-]+(?:\s|$)", text)
    if duplicate:
        text = text[:duplicate.start()].strip()

    return text


def _parse_adp_number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if text in {"", "-", "—", "–", "NR", "N/A"}:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0))
        return number if 0 < number < 999 else None
    except Exception:
        return None


def _find_header_column(header: list[str], *names: str) -> int | None:
    normalized = [re.sub(r"\s+", " ", cell).strip().upper() for cell in header]
    for name in names:
        wanted = name.upper()
        for index, value in enumerate(normalized):
            if value == wanted or value.startswith(wanted + " "):
                return index
    return None


def _parse_public_adp_html(
    html_text: str,
    *,
    platform: str,
    source_name: str,
) -> dict[str, Any]:
    parser = _PublicAdpTableParser()
    parser.feed(html_text)

    platform = platform.upper()
    platform_headers = (
        ("ESPN",)
        if platform == "ESPN"
        else ("Y!", "YAHOO", "YAHOO!")
    )

    selected = None
    header_index = None
    header = None

    for table in parser.tables:
        for index, row in enumerate(table[:10]):
            player_col = _find_header_column(row, "PLAYER")
            platform_col = _find_header_column(row, *platform_headers)
            if player_col is not None and platform_col is not None:
                selected = table
                header_index = index
                header = row
                break
        if selected is not None:
            break

    if selected is None or header is None or header_index is None:
        raise RuntimeError(
            f"{source_name} did not contain a recognizable {platform} ADP table."
        )

    player_col = _find_header_column(header, "PLAYER")
    platform_col = _find_header_column(header, *platform_headers)
    position_col = _find_header_column(header, "POS", "POSITION")
    team_col = _find_header_column(header, "TEAM")
    rank_col = _find_header_column(header, "RANK")
    consensus_col = _find_header_column(
        header,
        "AVG",
        "ADP",
        "CONSENSUS",
        "AVERAGE",
    )

    if player_col is None:
        raise RuntimeError("The player column was missing.")

    if platform_col is None and consensus_col is None:
        raise RuntimeError(
            "Neither a platform-specific nor consensus ADP column was found."
        )

    players: dict[str, dict[str, Any]] = {}

    for row in selected[header_index + 1:]:
        if len(row) <= max(player_col, platform_col):
            continue

        name = _clean_public_name(row[player_col])

        platform_adp = (
            _parse_adp_number(row[platform_col])
            if platform_col is not None and len(row) > platform_col
            else None
        )
        consensus_adp = (
            _parse_adp_number(row[consensus_col])
            if consensus_col is not None and len(row) > consensus_col
            else None
        )

        # Prefer the actual ESPN/Yahoo value. When that platform has not ranked
        # a deeper player, retain the published consensus PPR ADP instead of
        # incorrectly displaying NR.
        adp_value = (
            platform_adp
            if platform_adp is not None
            else consensus_adp
        )

        if not name or adp_value is None:
            continue

        position_text = (
            str(row[position_col]).upper().strip()
            if position_col is not None and len(row) > position_col
            else ""
        )
        match = re.match(r"(QB|RB|WR|TE|K|DST|DEF)[-\s]?(\d+)?", position_text)
        position = ""
        position_adp = ""
        if match:
            position = "DEF" if match.group(1) == "DST" else match.group(1)
            if match.group(2):
                position_adp = f"{position}{match.group(2)}"

        team = (
            str(row[team_col]).upper().strip()
            if team_col is not None and len(row) > team_col
            else ""
        )

        players[_norm(name)] = {
            "name": name,
            "position": position,
            "position_adp": position_adp,
            "team": team,
            "adp": adp_value,
            "platform_adp": platform_adp,
            "consensus_adp": consensus_adp,
            "adp_type": (
                f"{platform} specific"
                if platform_adp is not None
                else "consensus fallback"
            ),
            "rank": (
                _parse_adp_number(row[rank_col])
                if rank_col is not None and len(row) > rank_col
                else None
            ),
        }

    if len(players) < 50:
        raise RuntimeError(
            f"{source_name} returned only {len(players)} usable {platform} rows."
        )

    return {
        "season": 2026,
        "platform": platform,
        "source": source_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "players": players,
    }


def fetch_public_adp(platform: str = "ESPN") -> dict[str, Any]:
    platform = str(platform or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        raise ValueError("Platform must be ESPN or YAHOO.")

    sources = []

    if platform == "ESPN":
        sources.append(
            (
                "FantasyPros public 2026 PPR ESPN ADP",
                "https://www.fantasypros.com/nfl/adp/ppr-overall.php",
            )
        )
    else:
        sources.append(
            (
                "FantasyPros public 2026 Half-PPR Yahoo ADP",
                "https://www.fantasypros.com/nfl/adp/half-point-ppr-overall.php",
            )
        )

    sources.append(
        (
            f"4for4 public 2026 {platform} ADP",
            "https://www.4for4.com/adp",
        )
    )

    errors = []
    for source_name, url in sources:
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/150 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
                timeout=(10, 45),
            )
            response.raise_for_status()

            payload = _parse_public_adp_html(
                response.text,
                platform=platform,
                source_name=source_name,
            )
            return payload
        except Exception as exc:
            errors.append(f"{source_name}: {exc}")

    raise RuntimeError(" | ".join(errors))


def import_public_adp(platform: str = "ESPN") -> dict[str, Any]:
    payload = fetch_public_adp(platform)
    return import_adp_payload(
        platform,
        payload,
        source_name=payload.get("source") or f"{platform} public ADP",
        replace_existing=False,
        minimum_rows=50,
    )


def import_adp_payload(
    platform: str,
    payload: dict[str, Any],
    *,
    source_name: str = "",
    replace_existing: bool = True,
    minimum_rows: int = 1,
) -> dict[str, Any]:
    """
    Insert an already-fetched ADP payload directly into SQLite.

    This avoids a fragile JSON-file handoff between ESPN League Sync and the
    Player Research database.
    """
    init_database()
    platform = str(platform or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        raise ValueError("Platform must be ESPN or YAHOO.")

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "platform": platform,
            "count": 0,
            "message": "The ADP payload was not a JSON object.",
        }

    raw_players = payload.get("players") or {}
    if isinstance(raw_players, list):
        raw_players = {
            _norm(
                row.get("name")
                or row.get("player_name")
                or row.get("fullName")
            ): row
            for row in raw_players
            if isinstance(row, dict)
        }

    if not isinstance(raw_players, dict) or not raw_players:
        return {
            "ok": False,
            "platform": platform,
            "count": 0,
            "message": "The ADP payload contained no players.",
        }

    now = datetime.now(timezone.utc).isoformat()
    prepared: list[dict[str, Any]] = []

    for fallback_key, row in raw_players.items():
        if not isinstance(row, dict):
            continue

        name = str(
            row.get("name")
            or row.get("player_name")
            or row.get("fullName")
            or ""
        ).strip()
        if not name:
            continue

        adp_raw = (
            row.get("adp")
            if row.get("adp") not in (None, "")
            else row.get("averageDraftPosition")
        )
        if adp_raw in (None, ""):
            adp_raw = row.get("rank") or row.get("rank_value")

        try:
            adp_value = float(adp_raw)
        except Exception:
            continue

        if not (0 < adp_value < 999):
            continue

        position = _position(
            row.get("position")
            or row.get("pos")
            or row.get("positionAbbreviation")
        )
        team = str(
            row.get("team")
            or row.get("proTeamAbbreviation")
            or ""
        ).upper().strip()

        prepared.append(
            {
                "player_key": _norm(name),
                "player_id": str(
                    row.get("player_id")
                    or row.get("playerId")
                    or row.get("id")
                    or ""
                ),
                "name": name,
                "position": position,
                "team": team,
                "adp": round(adp_value, 2),
                "platform_adp": (
                    _number(row.get("platform_adp"))
                    if row.get("platform_adp") not in (None, "")
                    else (
                        round(adp_value, 2)
                        if str(row.get("adp_type") or "").lower().startswith(
                            platform.lower()
                        )
                        else None
                    )
                ),
                "consensus_adp": (
                    _number(row.get("consensus_adp"))
                    if row.get("consensus_adp") not in (None, "")
                    else (
                        round(adp_value, 2)
                        if str(row.get("adp_type") or "").lower().startswith(
                            "consensus"
                        )
                        else None
                    )
                ),
                "adp_type": str(
                    row.get("adp_type")
                    or f"{platform} specific"
                ),
                "position_adp": str(
                    row.get("position_adp")
                    or row.get("positional_rank")
                    or row.get("positionRank")
                    or ""
                ).strip(),
                "rank_value": (
                    _number(row.get("rank") or row.get("rank_value"))
                    or None
                ),
            }
        )

    if len(prepared) < max(1, int(minimum_rows)):
        return {
            "ok": False,
            "platform": platform,
            "count": 0,
            "received_count": len(raw_players),
            "usable_count": len(prepared),
            "message": (
                f"Rejected incomplete {platform} ADP payload: "
                f"only {len(prepared)} usable rows."
            ),
        }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        if row["position"]:
            grouped[row["position"]].append(row)

    for position, rows in grouped.items():
        rows.sort(key=lambda item: (item["adp"], item["name"].lower()))
        for number, row in enumerate(rows, start=1):
            if not row["position_adp"]:
                row["position_adp"] = f"{position}{number}"

    player_rows = [
        (
            row["player_key"],
            row["player_id"],
            row["name"],
            row["position"],
            row["team"] or "FA",
            1,
            now,
        )
        for row in prepared
    ]

    adp_rows = [
        (
            row["player_key"],
            2026,
            platform,
            row["adp"],
            row["position_adp"],
            row["rank_value"],
            source_name
            or payload.get("source")
            or f"{platform} direct sync",
            payload.get("updated_at") or now,
            row.get("adp_type") or f"{platform} specific",
            row.get("platform_adp"),
            row.get("consensus_adp"),
        )
        for row in prepared
    ]

    with connect() as connection:
        connection.executemany(
            """
            INSERT INTO players(
                player_key, player_id, name, position, team, active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                player_id=CASE
                    WHEN excluded.player_id<>'' THEN excluded.player_id
                    ELSE players.player_id
                END,
                name=excluded.name,
                position=CASE
                    WHEN excluded.position<>'' THEN excluded.position
                    ELSE players.position
                END,
                team=CASE
                    WHEN excluded.team<>'' AND excluded.team<>'FA'
                    THEN excluded.team
                    ELSE players.team
                END,
                active=1,
                updated_at=excluded.updated_at
            """,
            player_rows,
        )

        if replace_existing:
            connection.execute(
                "DELETE FROM adp WHERE season=2026 AND platform=?",
                (platform,),
            )

        connection.executemany(
            """
            INSERT INTO adp(
                player_key, season, platform, adp, position_adp,
                rank_value, source, updated_at, adp_type,
                platform_adp, consensus_adp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key, season, platform) DO UPDATE SET
                adp=excluded.adp,
                position_adp=CASE
                    WHEN excluded.position_adp<>'' THEN excluded.position_adp
                    ELSE adp.position_adp
                END,
                rank_value=COALESCE(excluded.rank_value, adp.rank_value),
                source=excluded.source,
                updated_at=excluded.updated_at,
                adp_type=excluded.adp_type,
                platform_adp=COALESCE(
                    excluded.platform_adp,
                    adp.platform_adp
                ),
                consensus_adp=COALESCE(
                    excluded.consensus_adp,
                    adp.consensus_adp
                )
            """,
            adp_rows,
        )

        inserted_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM adp
            WHERE season=2026 AND platform=?
            """,
            (platform,),
        ).fetchone()[0]

        _set_status(
            connection,
            f"adp_{platform.lower()}_2026",
            {
                "count": inserted_count,
                "source": source_name
                or payload.get("source")
                or f"{platform} direct sync",
                "direct_import": True,
            },
        )

    exact_repair = repair_exact_player_duplicates()
    alias_repair = repair_recent_player_aliases()

    return {
        "ok": inserted_count > 0,
        "platform": platform,
        "count": inserted_count,
        "received_count": len(raw_players),
        "usable_count": len(prepared),
        "source": source_name
        or payload.get("source")
        or f"{platform} direct sync",
        "exact_duplicate_merges": exact_repair.get("merged_count", 0),
        "alias_merges": alias_repair.get("merged_count", 0),
        "message": (
            f"Inserted {inserted_count} {platform} ADP rows into SQLite."
            if inserted_count
            else "No usable ADP rows were found in the payload."
        ),
    }


def import_adp(platform: str = "ESPN") -> dict[str, Any]:
    """
    Import ADP from the newest saved platform JSON file.
    """
    init_database()
    platform = str(platform or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        raise ValueError("Platform must be ESPN or YAHOO.")

    for candidate in _adp_candidates(platform):
        payload = _load_json(candidate)
        if payload.get("players"):
            result = import_adp_payload(
                platform,
                payload,
                source_name=payload.get("source") or candidate.name,
            )
            result["file"] = str(candidate)
            return result

    return {
        "ok": False,
        "platform": platform,
        "count": 0,
        "message": (
            f"No saved {platform} ADP dataset was found in "
            f"{', '.join(str(path) for path in _adp_candidates(platform))}."
        ),
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

    # Historical teams are imported first. Current teams and 2026 sources are
    # applied afterward so old season data cannot overwrite current rosters.
    result["history"] = import_all_history(start_season, end_season)
    result["current_players"] = import_current_players()
    result["projections_2026"] = import_projections()
    result["adp_espn"] = import_adp("ESPN")
    result["adp_yahoo"] = import_adp("YAHOO")

    # Apply current teams once more after projection/ADP imports.
    result["current_players_final"] = import_current_players()
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


@bp.get("/api/player-research-db/duplicate-status")
def duplicate_status_api():
    init_database()

    with connect() as connection:
        players = connection.execute(
            """
            SELECT
                p.player_key,
                p.name,
                p.position,
                p.team,
                (SELECT COUNT(*) FROM season_stats s
                 WHERE s.player_key=p.player_key) AS career_rows,
                (SELECT COUNT(*) FROM adp a
                 WHERE a.player_key=p.player_key AND a.season=2026) AS adp_rows
            FROM players p
            WHERE p.active=1
            ORDER BY p.name COLLATE NOCASE
            """
        ).fetchall()

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        grouped[(_norm(player["name"]), player["position"])].append(dict(player))

    duplicates = [
        {
            "normalized_name": key[0],
            "position": key[1],
            "records": records,
        }
        for key, records in grouped.items()
        if len(records) > 1
    ]

    return jsonify(
        ok=not duplicates,
        duplicate_group_count=len(duplicates),
        duplicates=duplicates,
    )


@bp.get("/api/player-research-db/adp-player/<path:player_name>")
def adp_player_api(player_name: str):
    init_database()
    platform = str(request.args.get("platform") or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                p.name,
                p.team,
                p.position,
                a.adp,
                a.position_adp,
                a.adp_type,
                a.platform_adp,
                a.consensus_adp,
                a.source,
                a.updated_at
            FROM players p
            LEFT JOIN adp a
              ON a.player_key=p.player_key
             AND a.season=2026
             AND a.platform=?
            WHERE p.player_key=? OR p.name=? COLLATE NOCASE
            LIMIT 1
            """,
            (platform, _norm(player_name), player_name),
        ).fetchone()

    if not row:
        return jsonify(ok=False, error="Player was not found."), 404

    return jsonify(ok=row["adp"] is not None, **dict(row))


@bp.get("/api/player-research-db/player-history-status/<path:player_name>")
def player_history_status_api(player_name: str):
    init_database()
    key = _norm(player_name)

    with connect() as connection:
        player = connection.execute(
            """
            SELECT player_key, name, team, position, player_id
            FROM players
            WHERE player_key=? OR name=? COLLATE NOCASE
            LIMIT 1
            """,
            (key, player_name),
        ).fetchone()

        if not player:
            return jsonify(ok=False, error="Player was not found."), 404

        seasons = connection.execute(
            """
            SELECT
                season, team, games, fantasy_points,
                fantasy_points_ppr, source
            FROM season_stats
            WHERE player_key=?
            ORDER BY season
            """,
            (player["player_key"],),
        ).fetchall()

    return jsonify(
        ok=bool(seasons),
        player=dict(player),
        season_count=len(seasons),
        seasons=[dict(row) for row in seasons],
    )


@bp.get("/api/player-research-db/history-status")
def history_status_api():
    init_database()

    with connect() as connection:
        summary = connection.execute(
            """
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT player_key) AS player_count,
                COUNT(DISTINCT season) AS season_count,
                MIN(season) AS first_season,
                MAX(season) AS last_season
            FROM season_stats
            """
        ).fetchone()

        seasons = connection.execute(
            """
            SELECT season, COUNT(*) AS player_count
            FROM season_stats
            GROUP BY season
            ORDER BY season DESC
            """
        ).fetchall()

        missing_current = connection.execute(
            """
            SELECT p.name, p.team, p.position
            FROM players p
            LEFT JOIN season_stats s ON s.player_key=p.player_key
            WHERE p.active=1
            GROUP BY p.player_key
            HAVING COUNT(s.season)=0
            ORDER BY p.name COLLATE NOCASE
            LIMIT 50
            """
        ).fetchall()

    return jsonify(
        ok=bool(summary["row_count"]),
        row_count=summary["row_count"],
        player_count=summary["player_count"],
        season_count=summary["season_count"],
        first_season=summary["first_season"],
        last_season=summary["last_season"],
        seasons=[dict(row) for row in seasons],
        current_players_without_history=[dict(row) for row in missing_current],
    )


@bp.get("/api/player-research-db/adp-status")
def adp_status_api():
    init_database()
    platform = str(request.args.get("platform") or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    with connect() as connection:
        summary = connection.execute(
            """
            SELECT
                COUNT(*) AS row_count,
                SUM(CASE WHEN adp_type LIKE '%specific%' THEN 1 ELSE 0 END)
                    AS platform_specific_count,
                SUM(CASE WHEN adp_type='consensus fallback' THEN 1 ELSE 0 END)
                    AS consensus_fallback_count,
                MIN(adp) AS best_adp,
                MAX(adp) AS worst_adp,
                MAX(updated_at) AS updated_at
            FROM adp
            WHERE season=2026 AND platform=?
            """,
            (platform,),
        ).fetchone()

        samples = connection.execute(
            """
            SELECT
                p.name,
                p.team,
                p.position,
                a.adp,
                a.position_adp,
                a.adp_type,
                a.platform_adp,
                a.consensus_adp
            FROM adp a
            JOIN players p ON p.player_key=a.player_key
            WHERE a.season=2026 AND a.platform=?
            ORDER BY a.adp ASC
            LIMIT 10
            """,
            (platform,),
        ).fetchall()

    return jsonify(
        ok=bool(summary["row_count"]),
        platform=platform,
        row_count=summary["row_count"],
        platform_specific_count=summary["platform_specific_count"] or 0,
        consensus_fallback_count=summary["consensus_fallback_count"] or 0,
        best_adp=summary["best_adp"],
        worst_adp=summary["worst_adp"],
        updated_at=summary["updated_at"],
        samples=[dict(row) for row in samples],
    )


@bp.post("/api/player-research-db/repair-identities")
def repair_identities_api():
    try:
        exact = repair_exact_player_duplicates()
        suffixes = repair_recent_player_aliases()
        return jsonify(
            ok=True,
            exact_duplicate_merges=exact.get("merged_count", 0),
            suffix_merges=suffixes.get("merged_count", 0),
            exact_records=exact.get("records", []),
            suffix_records=suffixes.get("pairs", []),
        )
    except Exception as exc:
        current_app.logger.exception("Player identity repair failed")
        return jsonify(ok=False, error=str(exc)), 500


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
        result = import_public_adp(platform)
    except Exception as public_exc:
        current_app.logger.warning(
            "Public %s ADP import failed: %s",
            platform,
            public_exc,
        )
        result = import_adp(platform)
        if not result.get("ok"):
            result["public_error"] = str(public_exc)

    if result.get("ok"):
        result["current_player_count"] = import_current_players()
        result["message"] = (
            f"SQLite now contains {result.get('count', 0)} imported "
            f"{platform} ADP rows from {result.get('source', 'the data source')}."
        )

    return jsonify(result), 200 if result.get("ok") else 409


@bp.post("/api/player-research-db/import-projections")
def import_projection_api():
    try:
        count = import_projections()
        return jsonify(ok=True, projection_count=count)
    except Exception as exc:
        current_app.logger.exception("Player database projection import failed")
        return jsonify(ok=False, error=str(exc)), 500


@bp.post("/api/player-research-db/import-complete-history")
def import_complete_history_api():
    body = request.get_json(silent=True) or {}
    start_season = _int_or_none(body.get("start_season")) or 1999
    end_season = _int_or_none(body.get("end_season")) or 2025

    try:
        result = import_complete_history(
            start_season,
            end_season,
            force_refresh=bool(body.get("force_refresh", True)),
        )
        return jsonify(result), 200 if result.get("ok") else 409
    except Exception as exc:
        current_app.logger.exception(
            "Complete multi-season history import failed"
        )
        return jsonify(ok=False, error=str(exc)), 500


@bp.post("/api/player-research-db/import-career-history")
def import_career_history_api():
    body = request.get_json(silent=True) or {}
    start_season = _int_or_none(body.get("start_season")) or 1999
    end_season = _int_or_none(body.get("end_season")) or 2025

    start_season = max(1999, start_season)
    end_season = min(2025, end_season)

    if start_season > end_season:
        return jsonify(
            ok=False,
            error="The starting season must be before the ending season.",
        ), 400

    try:
        result = import_all_history(start_season, end_season)
        exact_result = repair_exact_player_duplicates()
        identity_result = repair_recent_player_aliases()
        status = database_status()
        return jsonify(
            ok=(
                not bool(result.get("failures"))
                and status.get("season_rows", 0) > 0
            ),
            start_season=start_season,
            end_season=end_season,
            imported=result.get("imported", {}),
            failures=result.get("failures", {}),
            season_count=result.get("season_count", 0),
            stored_season_rows=status.get("season_rows", 0),
            stored_seasons=status.get("seasons", 0),
            first_stored_season=status.get("first_season"),
            last_stored_season=status.get("last_season"),
            exact_duplicate_merges=exact_result.get("merged_count", 0),
            identity_merges=identity_result.get("merged_count", 0),
        )
    except Exception as exc:
        current_app.logger.exception("Complete career-history import failed")
        return jsonify(ok=False, error=str(exc)), 500


@bp.post("/api/player-research-db/import-season/<int:season>")
def import_season_api(season: int):
    try:
        count = import_season(season)
        return jsonify(ok=True, season=season, player_count=count)
    except Exception as exc:
        current_app.logger.exception("Season %s database import failed", season)
        return jsonify(ok=False, season=season, error=str(exc)), 500


@bp.get("/api/player-analytics/table")
def player_analytics_table_api():
    """
    Return sortable player-season analytics derived from the SQLite statistics.

    This endpoint uses only fields stored in Gridiron IQ. It does not invent
    proprietary tracking metrics such as route participation, missed tackles
    forced, yards before contact, or defensive coverage grades.
    """
    init_database()

    position = _position(request.args.get("position"))
    season_raw = str(request.args.get("season") or "2025").strip()
    query = str(request.args.get("q") or "").strip()
    scope = str(request.args.get("scope") or "season").lower()
    direction = (
        "ASC"
        if str(request.args.get("direction") or "desc").lower() == "asc"
        else "DESC"
    )

    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1

    try:
        page_size = min(
            250,
            max(25, int(request.args.get("page_size", 100))),
        )
    except Exception:
        page_size = 100

    with connect() as connection:
        available_seasons = [
            int(row["season"])
            for row in connection.execute(
                """
                SELECT DISTINCT season
                FROM season_stats
                ORDER BY season DESC
                """
            ).fetchall()
        ]

    try:
        selected_season = int(season_raw)
    except Exception:
        selected_season = (
            available_seasons[0]
            if available_seasons
            else 2025
        )

    where = ["p.active=1"]
    parameters: list[Any] = []

    if position:
        where.append("p.position=?")
        parameters.append(position)

    if query:
        token = f"%{query}%"
        where.append(
            "(p.name LIKE ? OR p.team LIKE ? OR p.position LIKE ?)"
        )
        parameters.extend([token, token, token])

    where_sql = " AND ".join(where)

    if scope == "career":
        season_filter = ""
        season_parameters: list[Any] = []
        grouping = "GROUP BY p.player_key"
        season_expression = "'Career'"
        team_expression = "'All teams'"
    else:
        season_filter = "AND s.season=?"
        season_parameters = [selected_season]
        grouping = "GROUP BY p.player_key, s.season"
        season_expression = "s.season"
        team_expression = "COALESCE(s.team, p.team, 'FA')"

    base_query = f"""
        FROM players p
        JOIN season_stats s
          ON s.player_key=p.player_key
        WHERE {where_sql}
          {season_filter}
        {grouping}
    """

    metric_expressions = {
        "name": "p.name",
        "team": team_expression,
        "position": "p.position",
        "season": season_expression,
        "games": "SUM(s.games)",
        "fantasy_points": "SUM(s.fantasy_points)",
        "fantasy_points_ppr": "SUM(s.fantasy_points_ppr)",
        "fppg": (
            "CASE WHEN SUM(s.games)>0 "
            "THEN SUM(s.fantasy_points_ppr)/SUM(s.games) ELSE 0 END"
        ),
        "opportunities": (
            "SUM(s.carries)+SUM(s.targets)+SUM(s.attempts)"
        ),
        "touches": "SUM(s.carries)+SUM(s.receptions)",
        "completions": "SUM(s.completions)",
        "attempts": "SUM(s.attempts)",
        "completion_pct": (
            "CASE WHEN SUM(s.attempts)>0 "
            "THEN 100.0*SUM(s.completions)/SUM(s.attempts) ELSE 0 END"
        ),
        "passing_yards": "SUM(s.passing_yards)",
        "passing_tds": "SUM(s.passing_tds)",
        "interceptions": "SUM(s.interceptions)",
        "yards_per_attempt": (
            "CASE WHEN SUM(s.attempts)>0 "
            "THEN SUM(s.passing_yards)/SUM(s.attempts) ELSE 0 END"
        ),
        "pass_td_rate": (
            "CASE WHEN SUM(s.attempts)>0 "
            "THEN 100.0*SUM(s.passing_tds)/SUM(s.attempts) ELSE 0 END"
        ),
        "int_rate": (
            "CASE WHEN SUM(s.attempts)>0 "
            "THEN 100.0*SUM(s.interceptions)/SUM(s.attempts) ELSE 0 END"
        ),
        "carries": "SUM(s.carries)",
        "rushing_yards": "SUM(s.rushing_yards)",
        "rushing_tds": "SUM(s.rushing_tds)",
        "yards_per_carry": (
            "CASE WHEN SUM(s.carries)>0 "
            "THEN SUM(s.rushing_yards)/SUM(s.carries) ELSE 0 END"
        ),
        "rush_yards_per_game": (
            "CASE WHEN SUM(s.games)>0 "
            "THEN SUM(s.rushing_yards)/SUM(s.games) ELSE 0 END"
        ),
        "rush_td_rate": (
            "CASE WHEN SUM(s.carries)>0 "
            "THEN 100.0*SUM(s.rushing_tds)/SUM(s.carries) ELSE 0 END"
        ),
        "targets": "SUM(s.targets)",
        "receptions": "SUM(s.receptions)",
        "receiving_yards": "SUM(s.receiving_yards)",
        "receiving_tds": "SUM(s.receiving_tds)",
        "catch_rate": (
            "CASE WHEN SUM(s.targets)>0 "
            "THEN 100.0*SUM(s.receptions)/SUM(s.targets) ELSE 0 END"
        ),
        "yards_per_target": (
            "CASE WHEN SUM(s.targets)>0 "
            "THEN SUM(s.receiving_yards)/SUM(s.targets) ELSE 0 END"
        ),
        "yards_per_reception": (
            "CASE WHEN SUM(s.receptions)>0 "
            "THEN SUM(s.receiving_yards)/SUM(s.receptions) ELSE 0 END"
        ),
        "rec_yards_per_game": (
            "CASE WHEN SUM(s.games)>0 "
            "THEN SUM(s.receiving_yards)/SUM(s.games) ELSE 0 END"
        ),
        "rec_td_rate": (
            "CASE WHEN SUM(s.targets)>0 "
            "THEN 100.0*SUM(s.receiving_tds)/SUM(s.targets) ELSE 0 END"
        ),
        "total_yards": (
            "SUM(s.passing_yards)+SUM(s.rushing_yards)+"
            "SUM(s.receiving_yards)"
        ),
        "total_tds": (
            "SUM(s.passing_tds)+SUM(s.rushing_tds)+"
            "SUM(s.receiving_tds)"
        ),
    }

    sort_key = str(request.args.get("sort") or "fantasy_points_ppr")
    sort_expression = metric_expressions.get(
        sort_key,
        metric_expressions["fantasy_points_ppr"],
    )

    selected_fields = ",\n".join(
        f"{expression} AS {name}"
        for name, expression in metric_expressions.items()
    )

    count_parameters = [*parameters, *season_parameters]

    with connect() as connection:
        total = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT p.player_key
                {base_query}
            ) analytics_rows
            """,
            count_parameters,
        ).fetchone()[0]

        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size

        rows = connection.execute(
            f"""
            SELECT
                p.player_key,
                {selected_fields}
            {base_query}
            ORDER BY {sort_expression} {direction},
                     p.name COLLATE NOCASE ASC
            LIMIT ? OFFSET ?
            """,
            [*count_parameters, page_size, offset],
        ).fetchall()

    formatted_rows = []
    for raw in rows:
        row = dict(raw)

        integer_fields = {
            "games",
            "opportunities",
            "touches",
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
            "total_yards",
            "total_tds",
        }

        for field in integer_fields:
            row[field] = round(_number(row.get(field)))

        for field, value in list(row.items()):
            if field not in integer_fields and isinstance(
                value,
                (int, float),
            ):
                row[field] = round(float(value), 2)

        formatted_rows.append(row)

    return jsonify(
        ok=True,
        scope=scope,
        selected_season=selected_season,
        available_seasons=available_seasons,
        selected_position=position or "ALL",
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        players=formatted_rows,
        available_metrics=list(metric_expressions.keys()),
        unavailable_metrics=[
            "route participation",
            "targets per route run",
            "air-yards share",
            "yards before contact",
            "yards after contact",
            "missed tackles forced",
            "goal-line carry share",
            "man versus zone splits",
            "defensive-back assignments",
            "coverage grades",
            "explosive-play percentages",
            "weekly consistency and boom rates",
        ],
        source="Gridiron IQ SQLite season_stats",
    )


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
                COALESCE(a.adp_type, '') AS adp_type,
                a.platform_adp,
                a.consensus_adp,
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



def hydrate_player_career(player_key: str) -> dict[str, Any]:
    """
    Import missing completed seasons for one player when their profile opens.

    This avoids depending on a long all-player import. Matching prefers the
    stable nflverse player ID and falls back to normalized name matching.
    """
    init_database()

    with connect() as connection:
        player = connection.execute(
            "SELECT * FROM players WHERE player_key=?",
            (player_key,),
        ).fetchone()

        if not player:
            return {
                "ok": False,
                "imported_seasons": [],
                "error": "Player was not found.",
            }

        stored_seasons = {
            int(row["season"])
            for row in connection.execute(
                """
                SELECT season
                FROM season_stats
                WHERE player_key=?
                """,
                (player_key,),
            ).fetchall()
        }

    years_exp = int(_number(player["years_exp"]))
    first_season_value = (
        int(player["first_season"])
        if player["first_season"] is not None
        else None
    )

    # Estimate the first NFL season from experience when the existing database
    # incorrectly says the career began in 2025.
    experience_first = (
        max(1999, 2026 - years_exp - 1)
        if years_exp > 0
        else 2025
    )

    start_season = min(
        value
        for value in (first_season_value, experience_first)
        if value is not None
    )
    start_season = max(1999, min(start_season, 2025))

    expected_seasons = set(range(start_season, 2026))
    missing_seasons = sorted(expected_seasons - stored_seasons)

    if not missing_seasons:
        return {
            "ok": True,
            "imported_seasons": [],
            "stored_seasons": sorted(stored_seasons),
        }

    player_id = str(player["player_id"] or "").strip()
    target_names = {
        _norm(player["name"]),
        _identity_base_key(player["name"]),
    }

    now = datetime.now(timezone.utc).isoformat()
    inserted = []
    failures = {}

    for season in missing_seasons:
        try:
            rows = _download_official_regular_season(season)
            matches = []

            for row in rows:
                row_id = str(
                    row.get("player_id")
                    or row.get("gsis_id")
                    or ""
                ).strip()
                row_name = _row_name(row)

                id_match = bool(
                    player_id
                    and row_id
                    and row_id == player_id
                )
                name_match = (
                    _norm(row_name) in target_names
                    or _identity_base_key(row_name) in target_names
                )

                if id_match or name_match:
                    matches.append(row)

            if not matches:
                failures[str(season)] = "Player was not present in that season file."
                continue

            first = matches[0]
            position = _position(
                first.get("position")
                or first.get("position_group")
                or player["position"]
            )

            team_values = [
                str(
                    row.get("team")
                    or row.get("recent_team")
                    or ""
                ).upper().strip()
                for row in matches
                if str(
                    row.get("team")
                    or row.get("recent_team")
                    or ""
                ).strip()
            ]
            team = team_values[-1] if team_values else "FA"
            stats = _aggregate_rows(matches, player["name"])

            with connect() as connection:
                connection.execute(
                    """
                    INSERT INTO season_stats(
                        player_key, season, team, position,
                        games, completions, attempts, passing_yards,
                        passing_tds, interceptions, carries, rushing_yards,
                        rushing_tds, targets, receptions, receiving_yards,
                        receiving_tds, fantasy_points, fantasy_points_ppr,
                        source, updated_at
                    )
                    VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
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
                    (
                        player_key,
                        season,
                        team,
                        position,
                        *[stats[field] for field in STAT_FIELDS],
                        f"nflverse on-demand stats_player_reg_{season}.csv",
                        now,
                    ),
                )

                discovered_id = str(
                    first.get("player_id")
                    or first.get("gsis_id")
                    or ""
                ).strip()

                connection.execute(
                    """
                    UPDATE players
                    SET
                        player_id=CASE
                            WHEN (player_id IS NULL OR player_id='')
                                 AND ?<>''
                            THEN ?
                            ELSE player_id
                        END,
                        first_season=CASE
                            WHEN first_season IS NULL
                            THEN ?
                            ELSE MIN(first_season, ?)
                        END,
                        last_season=CASE
                            WHEN last_season IS NULL
                            THEN ?
                            ELSE MAX(last_season, ?)
                        END,
                        updated_at=?
                    WHERE player_key=?
                    """,
                    (
                        discovered_id,
                        discovered_id,
                        season,
                        season,
                        season,
                        season,
                        now,
                        player_key,
                    ),
                )

            if not player_id:
                player_id = str(
                    first.get("player_id")
                    or first.get("gsis_id")
                    or ""
                ).strip()

            inserted.append(season)

        except Exception as exc:
            failures[str(season)] = str(exc)

    repair_exact_player_duplicates()
    repair_recent_player_aliases()

    with connect() as connection:
        final_seasons = [
            int(row["season"])
            for row in connection.execute(
                """
                SELECT season
                FROM season_stats
                WHERE player_key=?
                ORDER BY season
                """,
                (player_key,),
            ).fetchall()
        ]

    return {
        "ok": bool(final_seasons),
        "imported_seasons": inserted,
        "stored_seasons": final_seasons,
        "failures": failures,
    }


@bp.post("/api/player-research-db/refresh-player-career/<path:player_name>")
def refresh_player_career_api(player_name: str):
    init_database()
    with connect() as connection:
        player = connection.execute(
            """
            SELECT player_key
            FROM players
            WHERE player_key=? OR name=? COLLATE NOCASE
            LIMIT 1
            """,
            (_norm(player_name), player_name),
        ).fetchone()

    if not player:
        return jsonify(ok=False, error="Player was not found."), 404

    result = hydrate_player_career(player["player_key"])
    return jsonify(result), 200 if result.get("ok") else 409


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

    # Import missing career seasons before reading the profile history.
    hydration = hydrate_player_career(player_key)

    with connect() as db:
        player = db.execute(
            "SELECT * FROM players WHERE player_key=?",
            (player_key,),
        ).fetchone()

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

    history_dicts = [dict(row) for row in history]
    career_totals = {
        field: round(
            sum(_number(row.get(field)) for row in history_dicts),
            2,
        )
        for field in STAT_FIELDS
    }

    seasons_played = len(history_dicts)
    career_games = career_totals.get("games", 0) or 0

    career_per_season = {
        field: round(
            career_totals.get(field, 0) / seasons_played,
            2,
        ) if seasons_played else 0
        for field in STAT_FIELDS
    }

    career_per_game = {
        field: round(
            career_totals.get(field, 0) / career_games,
            2,
        ) if career_games else 0
        for field in STAT_FIELDS
    }

    teams_by_season = [
        {
            "season": row.get("season"),
            "team": row.get("team") or "FA",
        }
        for row in history_dicts
    ]

    return jsonify(
        ok=True,
        profile={
            "bio": {
                **dict(player),
                "adp": adp["adp"] if adp else 999,
                "position_adp": adp["position_adp"] if adp else "",
                "adp_type": adp["adp_type"] if adp and "adp_type" in adp.keys() else "",
                "platform_adp": adp["platform_adp"] if adp and "platform_adp" in adp.keys() else None,
                "consensus_adp": adp["consensus_adp"] if adp and "consensus_adp" in adp.keys() else None,
            },
            "previous_year": previous_year,
            "history": [
                {
                    **row,
                    "season_team": row.get("team"),
                    "current_team": player["team"],
                }
                for row in history_dicts
            ],
            "career": {
                "seasons_played": seasons_played,
                "first_season": (
                    history_dicts[0].get("season")
                    if history_dicts else None
                ),
                "last_season": (
                    history_dicts[-1].get("season")
                    if history_dicts else None
                ),
                "teams_by_season": teams_by_season,
                "totals": career_totals,
                "per_season": career_per_season,
                "per_game": career_per_game,
            },
            "career_hydration": hydration,
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
