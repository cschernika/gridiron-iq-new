"""Daily analytics refresh command for Gridiron IQ."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from fantasy_analytics_hub import (
    DATA_DIR,
    connect,
    derive_phase_1,
    derive_phase_2,
    ingest_advanced_records,
    init_database,
    now_iso,
    sync_core_players,
)

PROVIDER_DROP_DIR = DATA_DIR / "provider_drop"
PROVIDER_DROP_DIR.mkdir(parents=True, exist_ok=True)


def log_provider(
    provider: str,
    dataset: str,
    *,
    status: str,
    record_count: int = 0,
    message: str = "",
    data_date: str = "",
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO provider_payloads(
                provider, dataset, data_date, record_count,
                status, message, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                dataset,
                data_date,
                int(record_count),
                status,
                message,
                now_iso(),
            ),
        )


def fetch_json_provider(
    *,
    provider: str,
    dataset: str,
    url_env: str,
    key_env: str = "",
    timeout: int = 60,
) -> Any | None:
    """
    Generic licensed-provider fetcher.

    The exact endpoint remains configurable through environment variables so
    Gridiron IQ is not tied to an unlicensed or undocumented API URL.
    """
    url = str(os.getenv(url_env) or "").strip()
    if not url:
        log_provider(
            provider,
            dataset,
            status="not_configured",
            message=f"Set {url_env} to enable this feed.",
        )
        return None

    headers = {
        "User-Agent": "Gridiron-IQ/2026",
        "Accept": "application/json",
    }
    if key_env:
        key = str(os.getenv(key_env) or "").strip()
        if not key:
            log_provider(
                provider,
                dataset,
                status="not_configured",
                message=f"Set {key_env} to enable this feed.",
            )
            return None
        header_name = str(
            os.getenv(f"{key_env}_HEADER") or "Ocp-Apim-Subscription-Key"
        )
        headers[header_name] = key

    response = requests.get(url, headers=headers, timeout=(10, timeout))
    response.raise_for_status()
    payload = response.json()

    count = (
        len(payload)
        if isinstance(payload, list)
        else len(payload.get("items", []))
        if isinstance(payload, dict)
        else 0
    )
    log_provider(
        provider,
        dataset,
        status="success",
        record_count=count,
        data_date=datetime.now(timezone.utc).date().isoformat(),
    )
    return payload


def load_provider_drop(filename: str) -> Any | None:
    path = PROVIDER_DROP_DIR / filename
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("items", "players", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def refresh_phase_1(season: int) -> dict[str, int]:
    player_count = sync_core_players()
    analytics_count = derive_phase_1(season)

    # Optional licensed/public feeds. They are logged even when not configured.
    feed_specs = [
        (
            "SportsDataIO",
            "injuries",
            "SPORTSDATAIO_INJURIES_URL",
            "SPORTSDATAIO_API_KEY",
        ),
        (
            "SportsDataIO",
            "depth_charts",
            "SPORTSDATAIO_DEPTH_CHARTS_URL",
            "SPORTSDATAIO_API_KEY",
        ),
        (
            "SportsDataIO",
            "projections",
            "SPORTSDATAIO_PROJECTIONS_URL",
            "SPORTSDATAIO_API_KEY",
        ),
        (
            "FantasyPros",
            "rankings_adp",
            "FANTASYPROS_RANKINGS_URL",
            "FANTASYPROS_API_KEY",
        ),
        (
            "FantasyPros",
            "news",
            "FANTASYPROS_NEWS_URL",
            "FANTASYPROS_API_KEY",
        ),
    ]

    for provider, dataset, url_env, key_env in feed_specs:
        try:
            fetch_json_provider(
                provider=provider,
                dataset=dataset,
                url_env=url_env,
                key_env=key_env,
            )
        except Exception as exc:
            log_provider(
                provider,
                dataset,
                status="failed",
                message=str(exc),
            )

    return {
        "players_synced": player_count,
        "analytics_updated": analytics_count,
    }


def refresh_phase_2(season: int) -> dict[str, int]:
    # Team/schedule drops are accepted as licensed or model-generated inputs.
    for filename, provider, dataset in [
        ("team_analytics.json", "Configured File", "team_analytics"),
        ("schedule_analytics.json", "Configured File", "schedule_analytics"),
        ("weekly_player_analytics.json", "Configured File", "weekly_player"),
    ]:
        payload = load_provider_drop(filename)
        if payload is None:
            log_provider(
                provider,
                dataset,
                status="not_configured",
                message=f"Place {filename} in {PROVIDER_DROP_DIR}.",
            )
        else:
            records = normalize_records(payload)
            log_provider(
                provider,
                dataset,
                status="available",
                record_count=len(records),
            )

    return {"analytics_updated": derive_phase_2(season)}


def refresh_phase_3(season: int) -> dict[str, int]:
    payload = load_provider_drop("advanced_player_analytics.json")

    if payload is None:
        try:
            payload = fetch_json_provider(
                provider="Licensed Advanced Analytics",
                dataset="player_charting",
                url_env="ADVANCED_ANALYTICS_URL",
                key_env="ADVANCED_ANALYTICS_API_KEY",
            )
        except Exception as exc:
            log_provider(
                "Licensed Advanced Analytics",
                "player_charting",
                status="failed",
                message=str(exc),
            )
            payload = None

    records = normalize_records(payload)
    if not records:
        log_provider(
            "Licensed Advanced Analytics",
            "player_charting",
            status="not_configured",
            message=(
                "Provide ADVANCED_ANALYTICS_URL/API key or place "
                "advanced_player_analytics.json in provider_drop."
            ),
        )
        return {"inserted": 0, "failed": 0}

    result = ingest_advanced_records(
        records,
        season=season,
        source="Licensed advanced analytics feed",
    )
    log_provider(
        "Licensed Advanced Analytics",
        "player_charting",
        status="success",
        record_count=result["inserted"],
        message=f"{result['failed']} records failed identity matching.",
    )
    return result


def run_refresh(
    *,
    season: int,
    phases: list[int],
) -> dict[str, Any]:
    init_database()
    started = now_iso()

    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO refresh_runs(
                started_at, status, phases, providers
            )
            VALUES (?, 'running', ?, ?)
            """,
            (
                started,
                ",".join(str(phase) for phase in phases),
                "nflverse/current database + configured providers",
            ),
        )
        run_id = cursor.lastrowid

    details: dict[str, Any] = {}
    players_updated = 0
    records_inserted = 0
    records_failed = 0

    try:
        if 1 in phases:
            details["phase_1"] = refresh_phase_1(season)
            players_updated += details["phase_1"].get(
                "analytics_updated",
                0,
            )

        if 2 in phases:
            details["phase_2"] = refresh_phase_2(season)
            players_updated += details["phase_2"].get(
                "analytics_updated",
                0,
            )

        if 3 in phases:
            details["phase_3"] = refresh_phase_3(season)
            records_inserted += details["phase_3"].get("inserted", 0)
            records_failed += details["phase_3"].get("failed", 0)

        completed = now_iso()
        with connect() as db:
            db.execute(
                """
                UPDATE refresh_runs
                SET completed_at=?, status='success',
                    players_updated=?, records_inserted=?,
                    records_failed=?, details_json=?
                WHERE id=?
                """,
                (
                    completed,
                    players_updated,
                    records_inserted,
                    records_failed,
                    json.dumps(details, ensure_ascii=False),
                    run_id,
                ),
            )

        return {
            "ok": True,
            "run_id": run_id,
            "season": season,
            "phases": phases,
            "players_updated": players_updated,
            "records_inserted": records_inserted,
            "records_failed": records_failed,
            "details": details,
            "started_at": started,
            "completed_at": completed,
        }

    except Exception as exc:
        completed = now_iso()
        with connect() as db:
            db.execute(
                """
                UPDATE refresh_runs
                SET completed_at=?, status='failed',
                    players_updated=?, records_inserted=?,
                    records_failed=?, details_json=?,
                    error_message=?
                WHERE id=?
                """,
                (
                    completed,
                    players_updated,
                    records_inserted,
                    records_failed + 1,
                    json.dumps(details, ensure_ascii=False),
                    str(exc),
                    run_id,
                ),
            )
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument(
        "--phases",
        default="1,2,3",
        help="Comma-separated phases, for example 1,2,3.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    phases = sorted(
        {
            int(value)
            for value in args.phases.split(",")
            if value.strip() in {"1", "2", "3"}
        }
    )
    try:
        result = run_refresh(season=args.season, phases=phases)
        print(json.dumps(result, indent=2))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
