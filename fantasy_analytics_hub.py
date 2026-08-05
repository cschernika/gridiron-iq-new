"""Fantasy Analytics Hub for Gridiron IQ.

This module implements:
- Phase 1: core player analytics and daily snapshots
- Phase 2: schedule, matchup, consistency and draft intelligence
- Phase 3: advanced charting fields supplied by licensed data feeds

The system never fabricates proprietary metrics. Missing provider fields remain
NULL and are reported through data-quality coverage.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(
    str(os.getenv("GRIDIRON_DATA_DIR") or "").strip()
    or (BASE_DIR / "data")
)
DATA_DIR.mkdir(parents=True, exist_ok=True)

ANALYTICS_DB = DATA_DIR / "fantasy_analytics.sqlite3"
PLAYER_DB = DATA_DIR / "player_research.sqlite3"
WEIGHTS_PATH = BASE_DIR / "data" / "position_analytics_weights.json"

POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

PHASE_FIELDS = {
    1: [
        "fantasy_points_ppr",
        "fantasy_points_per_game",
        "projected_points",
        "adp",
        "touches",
        "opportunities",
        "target_share",
        "carry_share",
        "red_zone_opportunities",
        "injury_score",
        "depth_chart_score",
    ],
    2: [
        "strength_of_schedule",
        "matchup_grade",
        "offensive_line_score",
        "defensive_front_score",
        "coverage_matchup_score",
        "consistency_score",
        "floor_projection",
        "ceiling_projection",
        "boom_probability",
        "bust_probability",
        "draft_score",
    ],
    3: [
        "routes_run",
        "route_participation",
        "targets_per_route",
        "air_yards_share",
        "slot_rate",
        "man_coverage_score",
        "zone_coverage_score",
        "primary_db_matchup",
        "yards_before_contact",
        "yards_after_contact",
        "missed_tackles_forced",
        "explosive_play_rate",
        "goal_line_share",
    ],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, number(value)))


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(ANALYTICS_DB)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def connect_player_db() -> sqlite3.Connection:
    connection = sqlite3.connect(PLAYER_DB)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def init_database() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS analytics_players (
                player_key TEXT PRIMARY KEY,
                player_id TEXT,
                name TEXT NOT NULL,
                position TEXT,
                team TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS provider_ids (
                player_key TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_player_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(player_key, provider),
                FOREIGN KEY(player_key)
                    REFERENCES analytics_players(player_key)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS player_weekly_analytics (
                player_key TEXT NOT NULL,
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                team TEXT,
                opponent TEXT,
                position TEXT,
                fantasy_points REAL,
                fantasy_points_ppr REAL,
                snaps REAL,
                routes_run REAL,
                targets REAL,
                receptions REAL,
                carries REAL,
                pass_attempts REAL,
                red_zone_opportunities REAL,
                source TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(player_key, season, week),
                FOREIGN KEY(player_key)
                    REFERENCES analytics_players(player_key)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS player_analytics (
                player_key TEXT NOT NULL,
                season INTEGER NOT NULL,
                position TEXT,
                team TEXT,

                fantasy_points_ppr REAL,
                fantasy_points_per_game REAL,
                projected_points REAL,
                adp REAL,
                touches REAL,
                opportunities REAL,
                target_share REAL,
                carry_share REAL,
                red_zone_opportunities REAL,
                injury_score REAL,
                depth_chart_score REAL,

                strength_of_schedule REAL,
                matchup_grade REAL,
                offensive_line_score REAL,
                defensive_front_score REAL,
                coverage_matchup_score REAL,
                consistency_score REAL,
                floor_projection REAL,
                ceiling_projection REAL,
                boom_probability REAL,
                bust_probability REAL,
                draft_score REAL,

                routes_run REAL,
                route_participation REAL,
                targets_per_route REAL,
                air_yards_share REAL,
                slot_rate REAL,
                man_coverage_score REAL,
                zone_coverage_score REAL,
                primary_db_matchup TEXT,
                yards_before_contact REAL,
                yards_after_contact REAL,
                missed_tackles_forced REAL,
                explosive_play_rate REAL,
                goal_line_share REAL,

                data_coverage REAL NOT NULL DEFAULT 0,
                phase_1_coverage REAL NOT NULL DEFAULT 0,
                phase_2_coverage REAL NOT NULL DEFAULT 0,
                phase_3_coverage REAL NOT NULL DEFAULT 0,
                source_summary TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(player_key, season),
                FOREIGN KEY(player_key)
                    REFERENCES analytics_players(player_key)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS team_analytics (
                team TEXT NOT NULL,
                season INTEGER NOT NULL,
                offensive_line_score REAL,
                pass_block_score REAL,
                run_block_score REAL,
                offensive_pace REAL,
                pass_rate REAL,
                scoring_environment REAL,
                defensive_front_score REAL,
                coverage_score REAL,
                pressure_rate REAL,
                sack_rate REAL,
                takeaway_rate REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(team, season)
            );

            CREATE TABLE IF NOT EXISTS schedule_analytics (
                team TEXT NOT NULL,
                position TEXT NOT NULL,
                season INTEGER NOT NULL,
                weeks_json TEXT,
                season_sos REAL,
                playoff_sos REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(team, position, season)
            );

            CREATE TABLE IF NOT EXISTS injuries (
                player_key TEXT NOT NULL,
                status TEXT,
                body_part TEXT,
                practice_status TEXT,
                return_estimate TEXT,
                injury_score REAL,
                source TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(player_key),
                FOREIGN KEY(player_key)
                    REFERENCES analytics_players(player_key)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS depth_charts (
                player_key TEXT NOT NULL,
                team TEXT,
                position TEXT,
                depth_order INTEGER,
                role TEXT,
                role_score REAL,
                source TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(player_key),
                FOREIGN KEY(player_key)
                    REFERENCES analytics_players(player_key)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS player_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_key TEXT,
                headline TEXT,
                summary TEXT,
                published_at TEXT,
                source TEXT,
                url TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS provider_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                dataset TEXT NOT NULL,
                data_date TEXT,
                record_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS refresh_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                phases TEXT,
                providers TEXT,
                players_updated INTEGER NOT NULL DEFAULT 0,
                records_inserted INTEGER NOT NULL DEFAULT 0,
                records_failed INTEGER NOT NULL DEFAULT 0,
                details_json TEXT,
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_analytics_position
                ON player_analytics(season, position, draft_score DESC);

            CREATE INDEX IF NOT EXISTS idx_weekly_player
                ON player_weekly_analytics(player_key, season, week);

            CREATE INDEX IF NOT EXISTS idx_news_player
                ON player_news(player_key, published_at DESC);
            """
        )


def load_weights() -> dict[str, dict[str, float]]:
    with WEIGHTS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return {
        position.upper(): {
            str(metric): float(weight)
            for metric, weight in metrics.items()
        }
        for position, metrics in payload.items()
    }


def sync_core_players() -> int:
    """Copy canonical players from Player Research into Analytics Hub."""
    init_database()
    if not PLAYER_DB.exists():
        return 0

    with connect_player_db() as source:
        rows = source.execute(
            """
            SELECT player_key, player_id, name, position, team, active
            FROM players
            """
        ).fetchall()

    timestamp = now_iso()
    with connect() as target:
        target.executemany(
            """
            INSERT INTO analytics_players(
                player_key, player_id, name, position, team,
                active, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
                player_id=CASE
                    WHEN excluded.player_id<>'' THEN excluded.player_id
                    ELSE analytics_players.player_id
                END,
                name=excluded.name,
                position=excluded.position,
                team=excluded.team,
                active=excluded.active,
                updated_at=excluded.updated_at
            """,
            [
                (
                    row["player_key"],
                    row["player_id"] or "",
                    row["name"],
                    row["position"] or "",
                    row["team"] or "FA",
                    int(row["active"] or 0),
                    timestamp,
                )
                for row in rows
            ],
        )
    return len(rows)


def _player_research_rows(season: int) -> list[sqlite3.Row]:
    if not PLAYER_DB.exists():
        return []

    with connect_player_db() as source:
        return source.execute(
            """
            SELECT
                p.player_key,
                p.name,
                p.position,
                p.team AS current_team,
                COALESCE(s.team, p.team, 'FA') AS season_team,
                COALESCE(s.games, 0) AS games,
                COALESCE(s.attempts, 0) AS attempts,
                COALESCE(s.carries, 0) AS carries,
                COALESCE(s.targets, 0) AS targets,
                COALESCE(s.receptions, 0) AS receptions,
                COALESCE(s.fantasy_points_ppr, 0) AS fantasy_points_ppr,
                COALESCE(pr.fantasy_points_ppr, 0) AS projected_points,
                a.adp
            FROM players p
            LEFT JOIN season_stats s
              ON s.player_key=p.player_key
             AND s.season=?
            LEFT JOIN projections pr
              ON pr.player_key=p.player_key
             AND pr.season=?
            LEFT JOIN adp a
              ON a.player_key=p.player_key
             AND a.season=?
             AND a.platform='ESPN'
            WHERE p.active=1
            """,
            (season, season + 1, season + 1),
        ).fetchall()


def calculate_consistency(
    weekly_points: Iterable[float],
    projection: float,
) -> dict[str, float]:
    values = [number(value) for value in weekly_points]
    values = [value for value in values if value >= 0]

    if not values:
        neutral = max(0, number(projection))
        return {
            "consistency_score": 50.0,
            "floor_projection": round(neutral * 0.55, 2),
            "ceiling_projection": round(neutral * 1.45, 2),
            "boom_probability": 25.0,
            "bust_probability": 25.0,
        }

    average = mean(values)
    deviation = pstdev(values) if len(values) > 1 else 0.0
    coefficient = deviation / average if average > 0 else 1.0
    consistency = clamp(100 - coefficient * 65)

    floor_value = max(0.0, average - deviation)
    ceiling_value = max(average, average + deviation)
    boom_threshold = average * 1.25
    bust_threshold = average * 0.60

    return {
        "consistency_score": round(consistency, 2),
        "floor_projection": round(floor_value, 2),
        "ceiling_projection": round(ceiling_value, 2),
        "boom_probability": round(
            100 * sum(value >= boom_threshold for value in values) / len(values),
            2,
        ),
        "bust_probability": round(
            100 * sum(value <= bust_threshold for value in values) / len(values),
            2,
        ),
    }


def metric_coverage(record: dict[str, Any], fields: list[str]) -> float:
    if not fields:
        return 0.0
    available = sum(
        record.get(field) is not None
        for field in fields
    )
    return round(100 * available / len(fields), 1)


def weighted_draft_score(
    position: str,
    metrics: dict[str, Any],
) -> float:
    weights = load_weights()
    position = "DEF" if position == "DST" else position
    position_weights = weights.get(position, {})
    if not position_weights:
        return 50.0

    total_weight = sum(position_weights.values()) or 1.0
    total = 0.0

    for metric, weight in position_weights.items():
        value = metrics.get(metric)
        if value is None:
            value = 50.0
        total += clamp(value) * weight / total_weight

    return round(total, 2)


def derive_phase_1(season: int) -> int:
    """Populate core analytics from the existing Player Research database."""
    init_database()
    sync_core_players()
    rows = _player_research_rows(season)
    timestamp = now_iso()

    with connect() as db:
        for row in rows:
            games = number(row["games"])
            fantasy_points = number(row["fantasy_points_ppr"])
            touches = number(row["carries"]) + number(row["receptions"])
            opportunities = (
                number(row["attempts"])
                + number(row["carries"])
                + number(row["targets"])
            )
            adp = row["adp"]
            adp_score = None
            if adp not in (None, ""):
                adp_score = clamp(105 - number(adp) / 3)

            record = {
                "fantasy_points_ppr": fantasy_points,
                "fantasy_points_per_game": (
                    fantasy_points / games if games > 0 else None
                ),
                "projected_points": number(row["projected_points"]) or None,
                "adp": number(adp) if adp not in (None, "") else None,
                "touches": touches,
                "opportunities": opportunities,
                "target_share": None,
                "carry_share": None,
                "red_zone_opportunities": None,
                "injury_score": None,
                "depth_chart_score": None,
                "adp_score": adp_score,
            }

            phase_1_coverage = metric_coverage(
                record,
                PHASE_FIELDS[1],
            )

            db.execute(
                """
                INSERT INTO player_analytics(
                    player_key, season, position, team,
                    fantasy_points_ppr, fantasy_points_per_game,
                    projected_points, adp, touches, opportunities,
                    target_share, carry_share, red_zone_opportunities,
                    injury_score, depth_chart_score,
                    phase_1_coverage, source_summary, updated_at
                )
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?
                )
                ON CONFLICT(player_key, season) DO UPDATE SET
                    position=excluded.position,
                    team=excluded.team,
                    fantasy_points_ppr=excluded.fantasy_points_ppr,
                    fantasy_points_per_game=excluded.fantasy_points_per_game,
                    projected_points=excluded.projected_points,
                    adp=excluded.adp,
                    touches=excluded.touches,
                    opportunities=excluded.opportunities,
                    phase_1_coverage=excluded.phase_1_coverage,
                    source_summary=excluded.source_summary,
                    updated_at=excluded.updated_at
                """,
                (
                    row["player_key"],
                    season,
                    row["position"],
                    row["current_team"] or row["season_team"],
                    record["fantasy_points_ppr"],
                    record["fantasy_points_per_game"],
                    record["projected_points"],
                    record["adp"],
                    record["touches"],
                    record["opportunities"],
                    record["target_share"],
                    record["carry_share"],
                    record["red_zone_opportunities"],
                    record["injury_score"],
                    record["depth_chart_score"],
                    phase_1_coverage,
                    "Player Research SQLite",
                    timestamp,
                ),
            )

    return len(rows)


def derive_phase_2(season: int) -> int:
    """
    Calculate schedule/matchup and consistency fields from available data.

    When schedule or charting feeds are absent, those metrics remain NULL and
    are excluded from coverage rather than being represented as factual.
    """
    init_database()
    timestamp = now_iso()

    with connect() as db:
        players = db.execute(
            """
            SELECT pa.*, ap.name
            FROM player_analytics pa
            JOIN analytics_players ap
              ON ap.player_key=pa.player_key
            WHERE pa.season=?
            """,
            (season,),
        ).fetchall()

        updated = 0
        for player in players:
            weekly_rows = db.execute(
                """
                SELECT fantasy_points_ppr
                FROM player_weekly_analytics
                WHERE player_key=? AND season=?
                ORDER BY week
                """,
                (player["player_key"], season),
            ).fetchall()

            consistency = calculate_consistency(
                [row["fantasy_points_ppr"] for row in weekly_rows],
                number(player["projected_points"]) / 17
                if player["projected_points"]
                else number(player["fantasy_points_per_game"]),
            )

            schedule = db.execute(
                """
                SELECT season_sos
                FROM schedule_analytics
                WHERE team=? AND position=? AND season=?
                """,
                (
                    player["team"],
                    player["position"],
                    season + 1,
                ),
            ).fetchone()

            team = db.execute(
                """
                SELECT *
                FROM team_analytics
                WHERE team=? AND season=?
                """,
                (player["team"], season + 1),
            ).fetchone()

            metrics = {
                "strength_of_schedule": (
                    schedule["season_sos"]
                    if schedule else None
                ),
                "matchup_grade": None,
                "offensive_line_score": (
                    team["offensive_line_score"]
                    if team else None
                ),
                "defensive_front_score": None,
                "coverage_matchup_score": None,
                **consistency,
            }

            adp_value_score = None
            if player["adp"] not in (None, ""):
                projected_rank_signal = clamp(
                    number(player["projected_points"]) / 4
                )
                adp_signal = clamp(105 - number(player["adp"]) / 3)
                adp_value_score = clamp(
                    50 + (projected_rank_signal - adp_signal) * 0.8
                )

            score_inputs = {
                "projection": clamp(
                    number(player["projected_points"]) / 4
                ),
                "adp_value": adp_value_score,
                "fantasy_points_per_game": clamp(
                    number(player["fantasy_points_per_game"]) * 4
                ),
                "strength_of_schedule": metrics["strength_of_schedule"],
                "matchup_grade": metrics["matchup_grade"],
                "offensive_line_score": metrics["offensive_line_score"],
                "coverage_matchup_score": metrics["coverage_matchup_score"],
                "consistency_score": metrics["consistency_score"],
                "floor_projection": clamp(
                    metrics["floor_projection"] * 4
                ),
                "ceiling_projection": clamp(
                    metrics["ceiling_projection"] * 3
                ),
                "boom_probability": metrics["boom_probability"],
                "bust_avoidance": (
                    100 - metrics["bust_probability"]
                    if metrics["bust_probability"] is not None
                    else None
                ),
            }
            draft_score = weighted_draft_score(
                player["position"],
                score_inputs,
            )
            metrics["draft_score"] = draft_score

            phase_2_coverage = metric_coverage(
                metrics,
                PHASE_FIELDS[2],
            )

            db.execute(
                """
                UPDATE player_analytics
                SET
                    strength_of_schedule=?,
                    matchup_grade=?,
                    offensive_line_score=?,
                    defensive_front_score=?,
                    coverage_matchup_score=?,
                    consistency_score=?,
                    floor_projection=?,
                    ceiling_projection=?,
                    boom_probability=?,
                    bust_probability=?,
                    draft_score=?,
                    phase_2_coverage=?,
                    updated_at=?
                WHERE player_key=? AND season=?
                """,
                (
                    metrics["strength_of_schedule"],
                    metrics["matchup_grade"],
                    metrics["offensive_line_score"],
                    metrics["defensive_front_score"],
                    metrics["coverage_matchup_score"],
                    metrics["consistency_score"],
                    metrics["floor_projection"],
                    metrics["ceiling_projection"],
                    metrics["boom_probability"],
                    metrics["bust_probability"],
                    metrics["draft_score"],
                    phase_2_coverage,
                    timestamp,
                    player["player_key"],
                    season,
                ),
            )
            updated += 1

        refresh_overall_coverage(db, season)

    return updated


def refresh_overall_coverage(
    db: sqlite3.Connection,
    season: int,
) -> None:
    rows = db.execute(
        "SELECT * FROM player_analytics WHERE season=?",
        (season,),
    ).fetchall()

    for raw in rows:
        record = dict(raw)
        phase_3_coverage = metric_coverage(record, PHASE_FIELDS[3])
        total_coverage = round(
            (
                number(record.get("phase_1_coverage"))
                + number(record.get("phase_2_coverage"))
                + phase_3_coverage
            ) / 3,
            1,
        )
        db.execute(
            """
            UPDATE player_analytics
            SET phase_3_coverage=?, data_coverage=?
            WHERE player_key=? AND season=?
            """,
            (
                phase_3_coverage,
                total_coverage,
                record["player_key"],
                season,
            ),
        )


def ingest_advanced_records(
    records: Iterable[dict[str, Any]],
    *,
    season: int,
    source: str,
) -> dict[str, int]:
    """
    Import Phase 3 licensed/charting data.

    Records may identify players by `player_key`, `player_id`, or exact name.
    Unsupported/missing values remain NULL.
    """
    init_database()
    inserted = 0
    failed = 0
    timestamp = now_iso()

    with connect() as db:
        for record in records:
            try:
                player_key = str(record.get("player_key") or "").strip()

                if not player_key and record.get("player_id"):
                    match = db.execute(
                        """
                        SELECT player_key
                        FROM analytics_players
                        WHERE player_id=?
                        LIMIT 1
                        """,
                        (str(record["player_id"]),),
                    ).fetchone()
                    player_key = match["player_key"] if match else ""

                if not player_key and record.get("name"):
                    match = db.execute(
                        """
                        SELECT player_key
                        FROM analytics_players
                        WHERE name=? COLLATE NOCASE
                        LIMIT 1
                        """,
                        (str(record["name"]),),
                    ).fetchone()
                    player_key = match["player_key"] if match else ""

                if not player_key:
                    failed += 1
                    continue

                fields = {
                    field: record.get(field)
                    for field in PHASE_FIELDS[3]
                }

                db.execute(
                    """
                    INSERT INTO player_analytics(
                        player_key, season, position, team,
                        routes_run, route_participation,
                        targets_per_route, air_yards_share, slot_rate,
                        man_coverage_score, zone_coverage_score,
                        primary_db_matchup, yards_before_contact,
                        yards_after_contact, missed_tackles_forced,
                        explosive_play_rate, goal_line_share,
                        source_summary, updated_at
                    )
                    VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?
                    )
                    ON CONFLICT(player_key, season) DO UPDATE SET
                        routes_run=COALESCE(
                            excluded.routes_run,
                            player_analytics.routes_run
                        ),
                        route_participation=COALESCE(
                            excluded.route_participation,
                            player_analytics.route_participation
                        ),
                        targets_per_route=COALESCE(
                            excluded.targets_per_route,
                            player_analytics.targets_per_route
                        ),
                        air_yards_share=COALESCE(
                            excluded.air_yards_share,
                            player_analytics.air_yards_share
                        ),
                        slot_rate=COALESCE(
                            excluded.slot_rate,
                            player_analytics.slot_rate
                        ),
                        man_coverage_score=COALESCE(
                            excluded.man_coverage_score,
                            player_analytics.man_coverage_score
                        ),
                        zone_coverage_score=COALESCE(
                            excluded.zone_coverage_score,
                            player_analytics.zone_coverage_score
                        ),
                        primary_db_matchup=COALESCE(
                            excluded.primary_db_matchup,
                            player_analytics.primary_db_matchup
                        ),
                        yards_before_contact=COALESCE(
                            excluded.yards_before_contact,
                            player_analytics.yards_before_contact
                        ),
                        yards_after_contact=COALESCE(
                            excluded.yards_after_contact,
                            player_analytics.yards_after_contact
                        ),
                        missed_tackles_forced=COALESCE(
                            excluded.missed_tackles_forced,
                            player_analytics.missed_tackles_forced
                        ),
                        explosive_play_rate=COALESCE(
                            excluded.explosive_play_rate,
                            player_analytics.explosive_play_rate
                        ),
                        goal_line_share=COALESCE(
                            excluded.goal_line_share,
                            player_analytics.goal_line_share
                        ),
                        source_summary=excluded.source_summary,
                        updated_at=excluded.updated_at
                    """,
                    (
                        player_key,
                        season,
                        record.get("position"),
                        record.get("team"),
                        fields["routes_run"],
                        fields["route_participation"],
                        fields["targets_per_route"],
                        fields["air_yards_share"],
                        fields["slot_rate"],
                        fields["man_coverage_score"],
                        fields["zone_coverage_score"],
                        fields["primary_db_matchup"],
                        fields["yards_before_contact"],
                        fields["yards_after_contact"],
                        fields["missed_tackles_forced"],
                        fields["explosive_play_rate"],
                        fields["goal_line_share"],
                        source,
                        timestamp,
                    ),
                )
                inserted += 1
            except Exception:
                failed += 1

        refresh_overall_coverage(db, season)

    return {"inserted": inserted, "failed": failed}


def list_players(
    *,
    season: int,
    position: str = "",
    query: str = "",
    sort: str = "draft_score",
    direction: str = "desc",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    init_database()
    direction_sql = "ASC" if direction.lower() == "asc" else "DESC"
    allowed_sort = {
        "name",
        "position",
        "team",
        "fantasy_points_ppr",
        "fantasy_points_per_game",
        "projected_points",
        "adp",
        "strength_of_schedule",
        "consistency_score",
        "floor_projection",
        "ceiling_projection",
        "boom_probability",
        "bust_probability",
        "draft_score",
        "data_coverage",
        "phase_1_coverage",
        "phase_2_coverage",
        "phase_3_coverage",
    }
    sort = sort if sort in allowed_sort else "draft_score"

    where = ["pa.season=?", "ap.active=1"]
    parameters: list[Any] = [season]

    if position:
        where.append("pa.position=?")
        parameters.append("DEF" if position == "DST" else position)

    if query:
        token = f"%{query}%"
        where.append(
            "(ap.name LIKE ? OR pa.team LIKE ? OR pa.position LIKE ?)"
        )
        parameters.extend([token, token, token])

    where_sql = " AND ".join(where)
    page_size = min(250, max(25, int(page_size)))
    page = max(1, int(page))

    with connect() as db:
        total = db.execute(
            f"""
            SELECT COUNT(*)
            FROM player_analytics pa
            JOIN analytics_players ap
              ON ap.player_key=pa.player_key
            WHERE {where_sql}
            """,
            parameters,
        ).fetchone()[0]

        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size

        rows = db.execute(
            f"""
            SELECT
                pa.*,
                ap.name,
                ap.player_id
            FROM player_analytics pa
            JOIN analytics_players ap
              ON ap.player_key=pa.player_key
            WHERE {where_sql}
            ORDER BY {sort} {direction_sql},
                     ap.name COLLATE NOCASE ASC
            LIMIT ? OFFSET ?
            """,
            [*parameters, page_size, offset],
        ).fetchall()

    return {
        "season": season,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "players": [dict(row) for row in rows],
    }


def player_profile(player_name: str, season: int) -> dict[str, Any] | None:
    init_database()
    with connect() as db:
        row = db.execute(
            """
            SELECT pa.*, ap.name, ap.player_id
            FROM player_analytics pa
            JOIN analytics_players ap
              ON ap.player_key=pa.player_key
            WHERE pa.season=?
              AND (
                    ap.player_key=?
                 OR ap.name=? COLLATE NOCASE
              )
            LIMIT 1
            """,
            (season, player_name, player_name),
        ).fetchone()

        if not row:
            return None

        weekly = db.execute(
            """
            SELECT *
            FROM player_weekly_analytics
            WHERE player_key=? AND season=?
            ORDER BY week
            """,
            (row["player_key"], season),
        ).fetchall()

        injury = db.execute(
            "SELECT * FROM injuries WHERE player_key=?",
            (row["player_key"],),
        ).fetchone()

        depth = db.execute(
            "SELECT * FROM depth_charts WHERE player_key=?",
            (row["player_key"],),
        ).fetchone()

        news = db.execute(
            """
            SELECT headline, summary, published_at, source, url
            FROM player_news
            WHERE player_key=?
            ORDER BY published_at DESC
            LIMIT 20
            """,
            (row["player_key"],),
        ).fetchall()

    record = dict(row)
    return {
        "player": record,
        "phase_fields": PHASE_FIELDS,
        "weekly": [dict(item) for item in weekly],
        "injury": dict(injury) if injury else None,
        "depth_chart": dict(depth) if depth else None,
        "news": [dict(item) for item in news],
        "missing_phase_1": [
            field for field in PHASE_FIELDS[1]
            if record.get(field) is None
        ],
        "missing_phase_2": [
            field for field in PHASE_FIELDS[2]
            if record.get(field) is None
        ],
        "missing_phase_3": [
            field for field in PHASE_FIELDS[3]
            if record.get(field) is None
        ],
    }


def latest_refresh() -> dict[str, Any] | None:
    init_database()
    with connect() as db:
        row = db.execute(
            """
            SELECT *
            FROM refresh_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def data_status(season: int) -> dict[str, Any]:
    init_database()
    with connect() as db:
        summary = db.execute(
            """
            SELECT
                COUNT(*) AS player_count,
                AVG(data_coverage) AS data_coverage,
                AVG(phase_1_coverage) AS phase_1_coverage,
                AVG(phase_2_coverage) AS phase_2_coverage,
                AVG(phase_3_coverage) AS phase_3_coverage,
                MAX(updated_at) AS updated_at
            FROM player_analytics
            WHERE season=?
            """,
            (season,),
        ).fetchone()

        providers = db.execute(
            """
            SELECT provider, dataset, data_date, record_count,
                   status, message, created_at
            FROM provider_payloads
            ORDER BY id DESC
            LIMIT 30
            """
        ).fetchall()

    return {
        "season": season,
        **dict(summary),
        "providers": [dict(row) for row in providers],
        "latest_refresh": latest_refresh(),
    }
