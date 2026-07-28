from __future__ import annotations
from flask import Blueprint, jsonify, current_app
from pathlib import Path
import json

player_research_v2 = Blueprint("player_research_v2", __name__)

def _load_players() -> list[dict]:
    configured = current_app.config.get("PLAYER_RESEARCH_DATA_FILE")
    data_file = Path(configured) if configured else Path(current_app.root_path) / "data" / "player_research_v2.json"
    if not data_file.exists():
        return []
    with data_file.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, list) else payload.get("players", [])

@player_research_v2.get("/api/player-research/players")
def list_players():
    players = _load_players()
    return jsonify({"players": players, "count": len(players), "version": "2.0"})

@player_research_v2.get("/api/player-research/players/<player_id>")
def get_player(player_id: str):
    player = next((p for p in _load_players() if str(p.get("id")) == player_id), None)
    if player is None:
        return jsonify({"error": "Player not found"}), 404
    return jsonify(player)
