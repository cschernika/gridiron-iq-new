"""Refresh the current Player Research directory once per day.

The daily job uses Sleeper's public NFL player directory for current teams,
free agents and injuries, then overlays nflverse's published ESPN depth charts
when they are available. Existing projections, ADP and historical-stat blocks
in the master database are preserved.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
ESPN_NFL_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=100"
NFLVERSE_DEPTH_URL = "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.csv"
USER_AGENT = "Gridiron-IQ-Daily-Player-Research/2026"
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
POSITION_MINIMUMS = {
    "QB": 40, "RB": 100, "WR": 150, "TE": 80, "K": 10, "DEF": 20,
}
NEWS_WINDOW_HOURS = 72


def norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def team_code(value):
    value = str(value or "").strip().upper()
    return {
        "JAX": "JAC", "WSH": "WAS", "LA": "LAR", "OAK": "LV",
        "SD": "LAC", "STL": "LAR",
    }.get(value, value)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, payload, pretty=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=not pretty,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path, default=None):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {} if default is None else default


def fetch_sleeper_players():
    errors = []
    for attempt in range(3):
        try:
            request = Request(
                SLEEPER_PLAYERS_URL,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urlopen(request, timeout=90) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or len(payload) < 1000:
                raise RuntimeError("Sleeper returned an incomplete player directory")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            errors.append(str(exc))
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError("Sleeper player directory refresh failed: " + " | ".join(errors))


def fetch_espn_news():
    request = Request(
        ESPN_NFL_NEWS_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urlopen(request, timeout=45) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
        raise RuntimeError("ESPN returned an invalid NFL news response")
    return payload


def fetch_nflverse_depth_charts(season=2026):
    """Download the current nflverse/ESPN depth-chart release as CSV."""
    errors = []
    base_url = NFLVERSE_DEPTH_URL.format(season=int(season))
    for url in (base_url, base_url + ".gz"):
        try:
            request = Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"},
            )
            with urlopen(request, timeout=90) as response:
                raw = response.read()
            if url.endswith(".gz") or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            if not rows:
                raise RuntimeError("the release contained no rows")
            return rows
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, ValueError, RuntimeError) as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Published depth-chart download failed: " + " | ".join(errors))


def player_name(row):
    return str(
        row.get("full_name")
        or " ".join(value for value in (row.get("first_name"), row.get("last_name")) if value)
        or ""
    ).strip()


def fantasy_position(row):
    position = str(
        row.get("position")
        or ((row.get("fantasy_positions") or [""])[0])
        or ""
    ).upper()
    return "DEF" if position == "DST" else position


def depth_fantasy_position(value):
    position = str(value or "").strip().upper()
    return {
        "DST": "DEF", "HB": "RB", "FB": "RB",
        "LWR": "WR", "RWR": "WR", "SWR": "WR",
    }.get(position, position)


def positive_int(value):
    try:
        number = int(float(value))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def depth_record_name(row):
    return str(
        row.get("full_name")
        or row.get("football_name")
        or " ".join(
            value for value in (row.get("first_name"), row.get("last_name")) if value
        )
        or ""
    ).strip()


def build_depth_index(rows, season=2026):
    """Keep each player's latest published team depth-chart position."""
    candidates = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        row_season = positive_int(row.get("season"))
        if row_season and row_season != int(season):
            continue
        name = depth_record_name(row)
        order = positive_int(
            row.get("depth_team")
            or row.get("depth_chart_order")
            or row.get("depth")
        )
        position = depth_fantasy_position(
            row.get("position") or row.get("depth_position")
        )
        team = team_code(row.get("club_code") or row.get("team"))
        if not name or not order or not team or position not in FANTASY_POSITIONS:
            continue
        week = positive_int(row.get("week")) or 0
        recency = (
            row_season or int(season),
            str(row.get("date") or row.get("timestamp") or ""),
            week,
        )
        key = norm(name)
        current = candidates.get(key)
        if (
            not current
            or recency > current["recency"]
            or (recency == current["recency"] and order < current["depth_chart_order"])
        ):
            candidates[key] = {
                "team": team,
                "position": position,
                "depth_chart_position": str(row.get("depth_position") or position).upper(),
                "depth_chart_order": order,
                "depth_chart_source": "nflverse / ESPN published depth chart",
                "recency": recency,
            }
    for record in candidates.values():
        record.pop("recency", None)
    return candidates


def apply_published_depth_charts(directory, depth_index):
    updated = 0
    for current in directory.values():
        published = depth_index.get(norm(current.get("full_name")))
        if not published:
            continue
        if team_code(current.get("team")) != team_code(published.get("team")):
            continue
        if depth_fantasy_position(current.get("position")) != depth_fantasy_position(published.get("position")):
            continue
        current["depth_chart_position"] = published.get("depth_chart_position") or current.get("position") or ""
        current["depth_chart_order"] = published.get("depth_chart_order")
        current["depth_chart_source"] = published.get("depth_chart_source") or "Published team depth chart"
        updated += 1
    return updated


def compact_directory(raw_directory, minimum_players=500):
    compact = {}
    for player_id, row in raw_directory.items():
        if not isinstance(row, dict):
            continue
        name = player_name(row)
        position = fantasy_position(row)
        if not name or position not in FANTASY_POSITIONS:
            continue
        fantasy_positions = ["DEF" if str(value).upper() == "DST" else str(value).upper() for value in (row.get("fantasy_positions") or [position])]
        compact[str(player_id)] = {
            "player_id": str(player_id),
            "full_name": name,
            "first_name": row.get("first_name") or "",
            "last_name": row.get("last_name") or "",
            "position": position,
            "fantasy_positions": fantasy_positions,
            "team": team_code(row.get("team")) or "FA",
            "status": row.get("status") or "",
            "active": bool(row.get("active")),
            "age": row.get("age"),
            "years_exp": row.get("years_exp"),
            "college": row.get("college") or "",
            "number": row.get("number"),
            "depth_chart_position": row.get("depth_chart_position") or "",
            "depth_chart_order": row.get("depth_chart_order"),
            "depth_chart_source": "Sleeper published depth chart" if positive_int(row.get("depth_chart_order")) else "",
            "injury_status": row.get("injury_status") or "",
            "injury_body_part": row.get("injury_body_part") or "",
            "injury_start_date": row.get("injury_start_date") or "",
            "practice_participation": row.get("practice_participation") or "",
            "practice_description": row.get("practice_description") or "",
            "search_rank": row.get("search_rank"),
        }
    if len(compact) < minimum_players:
        raise RuntimeError(f"Only {len(compact)} fantasy players were returned; refusing to replace the current directory")
    position_counts = {}
    for row in compact.values():
        position = row.get("position")
        position_counts[position] = position_counts.get(position, 0) + 1
    missing = {
        position: f"{position_counts.get(position, 0)}/{minimum}"
        for position, minimum in POSITION_MINIMUMS.items()
        if position_counts.get(position, 0) < minimum
    }
    if missing:
        raise RuntimeError(
            "Player directory has incomplete position coverage; refusing to replace the current directory: "
            + json.dumps(missing, sort_keys=True)
        )
    return compact


def directory_signature(directory):
    canonical = json.dumps(directory, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def normalize_news_article(article):
    links = article.get("links") or {}
    web = links.get("web") if isinstance(links, dict) else {}
    return {
        "title": article.get("headline") or article.get("title") or "Player update",
        "summary": article.get("description") or article.get("summary") or "",
        "published": article.get("published") or article.get("lastModified") or "",
        "source": "ESPN",
        "category": "NFL",
        "url": web.get("href") if isinstance(web, dict) else article.get("url") or "",
    }


def build_news_index(news_payload, directory, checked_at, window_hours=NEWS_WINDOW_HOURS):
    now = parse_datetime(checked_at) or datetime.now(timezone.utc)
    cutoff_seconds = max(1, int(window_hours)) * 60 * 60
    candidates = []

    for article in news_payload.get("articles", []) if isinstance(news_payload, dict) else []:
        if not isinstance(article, dict):
            continue
        normalized = normalize_news_article(article)
        published = parse_datetime(normalized.get("published"))
        if not published or (now - published).total_seconds() > cutoff_seconds:
            continue
        combined = norm(f"{normalized['title']} {normalized['summary']}")
        if combined:
            candidates.append((combined, normalized))

    players = {}
    for current in directory.values():
        name = str(current.get("full_name") or "").strip()
        key = norm(name)
        if not key:
            continue
        matches = [dict(article) for text, article in candidates if key in text]
        if matches:
            matches.sort(key=lambda article: str(article.get("published") or ""), reverse=True)
            players[key] = {"name": name, "news": matches[:5]}

    return {
        "updated_at": checked_at,
        "window_hours": int(window_hours),
        "source": "ESPN NFL news and Gridiron IQ roster updates",
        "player_count": len(players),
        "article_count": sum(len(row.get("news", [])) for row in players.values()),
        "players": players,
    }


def add_roster_change_news(news_index, old_news_index, team_changes, checked_at):
    players = news_index.setdefault("players", {})

    # Keep yesterday's still-recent roster notices so a signing badge remains
    # visible for the full news window instead of disappearing the next day.
    cutoff = (parse_datetime(checked_at) or datetime.now(timezone.utc)).timestamp() - NEWS_WINDOW_HOURS * 3600
    for key, old_row in (old_news_index.get("players", {}) if isinstance(old_news_index, dict) else {}).items():
        for article in old_row.get("news", []) if isinstance(old_row, dict) else []:
            if article.get("source") != "Gridiron IQ roster update":
                continue
            published = parse_datetime(article.get("published"))
            if not published or published.timestamp() < cutoff:
                continue
            target = players.setdefault(key, {"name": old_row.get("name") or key, "news": []})
            if not any(item.get("title") == article.get("title") for item in target["news"]):
                target["news"].append(dict(article))

    for change in team_changes or []:
        name = str(change.get("name") or "").strip()
        key = norm(name)
        if not key:
            continue
        title = f"{name} team updated: {change.get('from') or 'FA'} to {change.get('to') or 'FA'}"
        article = {
            "title": title,
            "summary": "Gridiron IQ detected this change in the daily current-player directory.",
            "published": checked_at,
            "source": "Gridiron IQ roster update",
            "category": "Roster move",
            "url": "",
        }
        target = players.setdefault(key, {"name": name, "news": []})
        if not any(item.get("title") == title for item in target["news"]):
            target["news"].insert(0, article)

    for row in players.values():
        row["news"] = sorted(
            row.get("news", []),
            key=lambda article: str(article.get("published") or ""),
            reverse=True,
        )[:5]
    news_index["player_count"] = len(players)
    news_index["article_count"] = sum(len(row.get("news", [])) for row in players.values())
    return news_index


def current_stats(output_dir):
    for name in ("nfl_player_stats_2026.json", "nfl_player_stats_2025.json"):
        payload = read_json(Path(output_dir) / name)
        if isinstance(payload.get("players"), dict) and payload["players"]:
            return payload
    return {}


def build_master(directory, old_master, stats_payload, signature, checked_at):
    old_players = old_master.get("players", {}) if isinstance(old_master, dict) else {}
    stats_players = stats_payload.get("players", {}) if isinstance(stats_payload, dict) else {}
    stats_season = int(stats_payload.get("season") or 0) if stats_payload else 0
    merged = {}
    team_changes = []
    injury_changes = []

    for player_id, current in directory.items():
        name = current["full_name"]
        key = norm(name)
        if not key:
            continue
        old = dict(old_players.get(key) or {})
        old_team = team_code(old.get("team")) or "FA"
        new_team = current.get("team") or "FA"
        old_injury = str(old.get("injury_status") or "")
        new_injury = str(current.get("injury_status") or "")

        item = old
        item.update({
            "name": name,
            "position": current["position"],
            "team": new_team,
            "season": 2026,
            "sleeper_id": player_id,
            "status": current.get("status") or "",
            "active": current.get("active"),
            "age": current.get("age"),
            "years_exp": current.get("years_exp"),
            "college": current.get("college") or "",
            "number": current.get("number"),
            "depth_chart_position": current.get("depth_chart_position") or "",
            "depth_chart_order": current.get("depth_chart_order"),
            "depth_chart_source": current.get("depth_chart_source") or "",
            "fantasy_positions": current.get("fantasy_positions") or [current["position"]],
            "injury_status": new_injury,
            "injury_body_part": current.get("injury_body_part") or "",
            "injury_start_date": current.get("injury_start_date") or "",
            "practice_participation": current.get("practice_participation") or "",
            "practice_description": current.get("practice_description") or "",
            "source_player": "Sleeper daily player directory",
            "last_roster_refresh": checked_at,
        })
        try:
            item["rookie"] = int(current.get("years_exp")) == 0
        except (TypeError, ValueError):
            item["rookie"] = bool(old.get("rookie"))

        stats = stats_players.get(key)
        if isinstance(stats, dict) and stats_season:
            item[f"stats_{stats_season}"] = dict(stats)

        if old and old_team != new_team:
            team_changes.append({"name": name, "from": old_team, "to": new_team})
        if old and old_injury != new_injury:
            injury_changes.append({"name": name, "from": old_injury, "to": new_injury})
        merged[key] = item

    return {
        "season": 2026,
        "updated_at": checked_at,
        "daily_refresh": True,
        "count": len(merged),
        "rookie_count": sum(1 for player in merged.values() if player.get("rookie")),
        "sources": [
            "Sleeper public NFL player directory — daily",
            "nflverse / ESPN published depth charts — daily when available",
        ],
        "team_resolution_priority": ["Sleeper daily player directory", "FA when no current team is published"],
        "roster_signature": signature,
        "team_change_count": len(team_changes),
        "injury_change_count": len(injury_changes),
        "team_changes": team_changes[:100],
        "injury_changes": injury_changes[:100],
        "players": merged,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--input-json", type=Path, help="Use a local Sleeper-shaped fixture instead of downloading")
    parser.add_argument("--news-json", type=Path, help="Use a local ESPN-shaped news fixture instead of downloading")
    parser.add_argument("--depth-json", type=Path, help="Use a local nflverse-shaped depth-chart fixture instead of downloading")
    parser.add_argument(
        "--minimum-players",
        type=int,
        default=500,
        help="Safety threshold; lower only when running a small local fixture test",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    raw = read_json(args.input_json) if args.input_json else fetch_sleeper_players()
    directory = compact_directory(raw, max(1, args.minimum_players))
    depth_warning = ""
    published_depth_count = 0
    try:
        if args.depth_json:
            depth_payload = read_json(args.depth_json, default=[])
            depth_rows = depth_payload if isinstance(depth_payload, list) else depth_payload.get("rows", [])
        elif args.input_json:
            depth_rows = []
        else:
            depth_rows = fetch_nflverse_depth_charts(2026)
        depth_index = build_depth_index(depth_rows, 2026)
        published_depth_count = apply_published_depth_charts(directory, depth_index)
        print(f"Applied {published_depth_count} published depth-chart positions")
    except Exception as exc:
        depth_warning = str(exc)
        print(f"Published depth-chart refresh warning: {depth_warning}")
    signature = directory_signature(directory)
    checked_at = utc_now()

    cache_path = args.output_dir / "sleeper_players_cache.json"
    master_path = args.output_dir / "nfl_players_2026.json"
    status_path = args.output_dir / "player_research_daily_status.json"
    news_index_path = args.output_dir / "player_news_index.json"
    old_master = read_json(master_path)
    old_news_index = read_json(news_index_path)
    old_signature = str(old_master.get("roster_signature") or "")
    changed = signature != old_signature or not cache_path.exists() or not master_path.exists()

    if changed:
        master = build_master(directory, old_master, current_stats(args.output_dir), signature, checked_at)
        atomic_json(cache_path, directory)
        atomic_json(master_path, master, pretty=True)
        print(
            f"Updated {len(directory)} current players; "
            f"team changes={master['team_change_count']}, injury changes={master['injury_change_count']}"
        )
    else:
        master = old_master
        print(f"Checked {len(directory)} current players; no roster or injury changes")

    news_warning = ""
    try:
        if args.news_json:
            news_payload = read_json(args.news_json)
        elif args.input_json:
            news_payload = {"articles": []}
        else:
            news_payload = fetch_espn_news()
        news_index = build_news_index(news_payload, directory, checked_at)
        news_index = add_roster_change_news(
            news_index,
            old_news_index,
            master.get("team_changes", []) if changed else [],
            checked_at,
        )
        old_news_players = old_news_index.get("players", {}) if isinstance(old_news_index, dict) else {}
        news_changed = news_index.get("players", {}) != old_news_players
        atomic_json(news_index_path, news_index, pretty=True)
        print(f"Indexed recent news for {news_index['player_count']} players")
    except Exception as exc:
        news_warning = str(exc)
        news_changed = False
        news_index = old_news_index if isinstance(old_news_index, dict) else {}
        if not news_index_path.exists():
            news_index = build_news_index({"articles": []}, directory, checked_at)
            atomic_json(news_index_path, news_index, pretty=True)
        print(f"Player news refresh warning: {news_warning}")

    status = {
        "ok": True,
        "season": 2026,
        "checked_at": checked_at,
        "data_changed": bool(changed or news_changed),
        "player_count": len(directory),
        "team_change_count": int(master.get("team_change_count") or 0) if changed else 0,
        "injury_change_count": int(master.get("injury_change_count") or 0) if changed else 0,
        "source": "Sleeper public NFL player directory",
        "depth_chart_source": "nflverse / ESPN published depth charts plus client-side team projection",
        "published_depth_count": published_depth_count,
        "depth_chart_warning": depth_warning,
        "news_source": news_index.get("source", ""),
        "news_player_count": int(news_index.get("player_count") or 0),
        "news_article_count": int(news_index.get("article_count") or 0),
        "news_warning": news_warning,
        "next_scheduled_refresh": "Daily at 6:37 AM America/New_York",
    }
    atomic_json(status_path, status, pretty=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
