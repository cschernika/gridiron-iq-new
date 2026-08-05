"""Example routes to paste into or adapt for your Flask app."""

from flask import Blueprint, jsonify, request
from engines import DecisionEngine

decision_api = Blueprint("decision_api", __name__, url_prefix="/api/decision")
engine = DecisionEngine()


@decision_api.post("/draft-score")
def draft_score():
    payload = request.get_json(silent=True) or {}
    required = ("player", "league")
    missing = [key for key in required if key not in payload]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    result = engine.draft_score(
        player=payload["player"],
        league=payload["league"],
        roster=payload.get("roster", {}),
        draft_context=payload.get("draft_context", {}),
        team=payload.get("team", {}),
    )
    return jsonify(result)


@decision_api.post("/weekly-score")
def weekly_score():
    payload = request.get_json(silent=True) or {}
    required = ("player", "defense", "league")
    missing = [key for key in required if key not in payload]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    result = engine.weekly_score(
        player=payload["player"],
        defense=payload["defense"],
        league=payload["league"],
        context=payload.get("context", {}),
        team=payload.get("team", {}),
    )
    return jsonify(result)


@decision_api.post("/rank-draft")
def rank_draft():
    payload = request.get_json(silent=True) or {}
    results = engine.rank_draft_candidates(
        players=payload.get("players", []),
        league=payload.get("league", {}),
        roster=payload.get("roster", {}),
        contexts=payload.get("contexts", {}),
    )
    return jsonify({"results": results})


# In your app factory or app.py:
# from flask_integration_example import decision_api
# app.register_blueprint(decision_api)
