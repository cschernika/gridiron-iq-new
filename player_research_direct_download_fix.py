"""Gridiron IQ nflverse player-stat downloader.

This version does NOT call api.github.com, so GitHub API rate limits cannot
block the Player Research refresh.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Dict, List

import requests


NFLVERSE_PLAYER_RELEASE = (
    "https://github.com/nflverse/nflverse-data/releases/download/stats_player"
)


def _pr_direct_urls(season: int) -> List[str]:
    """
    Direct nflverse release assets, ordered from preferred to fallback.

    nflverse has used more than one naming convention over time. Trying these
    direct assets is inexpensive and avoids the GitHub releases API.
    """
    season = int(season)

    return [
        # Current summary-level naming conventions.
        f"{NFLVERSE_PLAYER_RELEASE}/stats_player_reg_{season}.csv",
        f"{NFLVERSE_PLAYER_RELEASE}/stats_player_reg+post_{season}.csv",
        f"{NFLVERSE_PLAYER_RELEASE}/stats_player_week_{season}.csv",

        # Alternate names retained as fallbacks.
        f"{NFLVERSE_PLAYER_RELEASE}/player_stats_reg_{season}.csv",
        f"{NFLVERSE_PLAYER_RELEASE}/player_stats_reg+post_{season}.csv",
        f"{NFLVERSE_PLAYER_RELEASE}/player_stats_week_{season}.csv",
        f"{NFLVERSE_PLAYER_RELEASE}/player_stats_{season}.csv",
    ]


def _looks_like_csv(response: requests.Response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    body_start = response.content[:250].lower()

    # GitHub error pages are HTML even when the request returns a response.
    if b"<html" in body_start or b"rate limit" in body_start:
        return False

    return (
        "csv" in content_type
        or "text/plain" in content_type
        or b"player_id" in body_start
        or b"player_name" in body_start
    )


def _normalize_player_rows(rows: List[Dict[str, str]], season: int) -> List[Dict[str, str]]:
    """
    Keep the requested season and regular-season records.

    Season-summary files normally already contain only one season. Weekly files
    are filtered and can later be aggregated by your existing snapshot builder.
    """
    normalized = []

    for row in rows:
        row_season = str(row.get("season", season)).strip()
        if row_season and row_season != str(season):
            continue

        season_type = str(row.get("season_type", "REG")).upper().strip()
        if season_type and season_type not in {"REG", "REGULAR"}:
            continue

        normalized.append(row)

    return normalized


def _pr_rows(season: int, force: bool = False):
    """
    Load nflverse player statistics without api.github.com.

    - Uses the saved CSV when force=False.
    - Uses direct release-download URLs when force=True or no cache exists.
    - Falls back to the saved CSV if every live download fails.
    """
    season = int(season)
    cache = DATA_DIR / f"player_stats_{season}.csv"

    if cache.exists() and not force:
        try:
            text = cache.read_text(encoding="utf-8")
            rows = list(csv.DictReader(io.StringIO(text)))
            rows = _normalize_player_rows(rows, season)
            if rows:
                return rows
        except Exception:
            app.logger.exception("Could not read cached %s player statistics", season)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Gridiron-IQ/1.0",
            "Accept": "text/csv,application/octet-stream;q=0.9,*/*;q=0.8",
        }
    )

    failures = []

    for url in _pr_direct_urls(season):
        try:
            response = session.get(
                url,
                timeout=(15, 90),
                allow_redirects=True,
            )

            if response.status_code == 404:
                failures.append(f"404: {url}")
                continue

            response.raise_for_status()

            if not _looks_like_csv(response):
                failures.append(f"Not CSV: {url}")
                continue

            text = response.content.decode("utf-8-sig", errors="replace")
            rows = list(csv.DictReader(io.StringIO(text)))
            rows = _normalize_player_rows(rows, season)

            if not rows:
                failures.append(f"No {season} rows: {url}")
                continue

            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(text, encoding="utf-8")
            except Exception:
                app.logger.exception(
                    "Loaded %s player stats but could not save the cache",
                    season,
                )

            app.logger.info(
                "Loaded %s player statistics directly from %s (%s rows)",
                season,
                url,
                len(rows),
            )
            return rows

        except requests.RequestException as exc:
            failures.append(f"{type(exc).__name__}: {url}: {exc}")
            app.logger.warning(
                "Direct nflverse player-stat download failed for %s: %s",
                url,
                exc,
            )

    # Do not destroy a working page because a refresh source is unavailable.
    if cache.exists():
        try:
            text = cache.read_text(encoding="utf-8")
            rows = list(csv.DictReader(io.StringIO(text)))
            rows = _normalize_player_rows(rows, season)
            if rows:
                app.logger.warning(
                    "All live %s downloads failed; using %s cached rows.",
                    season,
                    len(rows),
                )
                return rows
        except Exception:
            app.logger.exception(
                "Could not use fallback cached %s player statistics",
                season,
            )

    app.logger.error(
        "All direct nflverse downloads failed for season %s: %s",
        season,
        " | ".join(failures[-7:]),
    )
    return []
