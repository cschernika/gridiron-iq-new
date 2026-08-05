"""Flask routes for the Fantasy Analytics Hub."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from fantasy_analytics_hub import (
    PHASE_FIELDS,
    data_status,
    init_database,
    list_players,
    load_weights,
    player_profile,
)
from fantasy_analytics_refresh import run_refresh

bp = Blueprint("fantasy_analytics", __name__)


@bp.get("/fantasy-analytics")
def analytics_page():
    return render_template("fantasy_analytics_hub.html")


@bp.get("/api/fantasy-analytics/players")
def analytics_players_api():
    try:
        season = int(request.args.get("season", 2025))
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 100))
    except Exception:
        return jsonify(ok=False, error="Invalid numeric parameter."), 400

    result = list_players(
        season=season,
        position=str(request.args.get("position") or "").upper(),
        query=str(request.args.get("q") or "").strip(),
        sort=str(request.args.get("sort") or "draft_score"),
        direction=str(request.args.get("direction") or "desc"),
        page=page,
        page_size=page_size,
    )
    return jsonify(ok=True, **result)


@bp.get("/api/fantasy-analytics/player/<path:player_name>")
def analytics_player_api(player_name: str):
    try:
        season = int(request.args.get("season", 2025))
    except Exception:
        season = 2025

    result = player_profile(player_name, season)
    if not result:
        return jsonify(ok=False, error="Player analytics were not found."), 404
    return jsonify(ok=True, **result)


@bp.get("/api/fantasy-analytics/status")
def analytics_status_api():
    try:
        season = int(request.args.get("season", 2025))
    except Exception:
        season = 2025
    return jsonify(ok=True, **data_status(season))


@bp.get("/api/fantasy-analytics/config")
def analytics_config_api():
    return jsonify(
        ok=True,
        position_weights=load_weights(),
        phase_fields=PHASE_FIELDS,
    )


@bp.post("/api/fantasy-analytics/refresh")
def analytics_refresh_api():
    payload = request.get_json(silent=True) or {}

    try:
        season = int(payload.get("season", 2025))
    except Exception:
        return jsonify(ok=False, error="Invalid season."), 400

    phases = payload.get("phases") or [1, 2, 3]
    try:
        phases = sorted(
            {
                int(phase)
                for phase in phases
                if int(phase) in {1, 2, 3}
            }
        )
    except Exception:
        return jsonify(ok=False, error="Invalid phases."), 400

    try:
        return jsonify(run_refresh(season=season, phases=phases))
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500


def register(app) -> None:
    init_database()
    app.register_blueprint(bp)
