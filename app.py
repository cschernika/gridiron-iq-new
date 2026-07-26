from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
SNAPSHOT_FILE = DATA_DIR / "espn_snapshot.json"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "gridiron-iq-development-key-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    JSON_SORT_KEYS=False,
)

USER = {"id": 1, "name": "Chad", "email": "chad@totalatlantagroup.com"}

BASE_RANKINGS = [
    {"rank":1,"name":"Ja'Marr Chase","pos":"WR","team":"CIN","tier":1,"adp":1.4,"projection":312.2},
    {"rank":2,"name":"Bijan Robinson","pos":"RB","team":"ATL","tier":1,"adp":2.1,"projection":298.4},
    {"rank":3,"name":"Justin Jefferson","pos":"WR","team":"MIN","tier":1,"adp":3.2,"projection":301.1},
    {"rank":4,"name":"CeeDee Lamb","pos":"WR","team":"DAL","tier":1,"adp":4.6,"projection":294.3},
    {"rank":5,"name":"Jahmyr Gibbs","pos":"RB","team":"DET","tier":1,"adp":5.1,"projection":286.7},
    {"rank":6,"name":"Amon-Ra St. Brown","pos":"WR","team":"DET","tier":2,"adp":6.4,"projection":285.2},
    {"rank":7,"name":"Puka Nacua","pos":"WR","team":"LAR","tier":2,"adp":7.2,"projection":279.8},
    {"rank":8,"name":"Saquon Barkley","pos":"RB","team":"PHI","tier":2,"adp":8.1,"projection":276.5},
    {"rank":9,"name":"Josh Allen","pos":"QB","team":"BUF","tier":2,"adp":18.5,"projection":368.6},
    {"rank":10,"name":"Brock Bowers","pos":"TE","team":"LV","tier":2,"adp":14.8,"projection":252.0},
    {"rank":11,"name":"Nico Collins","pos":"WR","team":"HOU","tier":3,"adp":11.9,"projection":267.3},
    {"rank":12,"name":"Breece Hall","pos":"RB","team":"NYJ","tier":3,"adp":12.7,"projection":258.2},
    {"rank":13,"name":"Malik Nabers","pos":"WR","team":"NYG","tier":3,"adp":13.3,"projection":263.8},
    {"rank":14,"name":"Lamar Jackson","pos":"QB","team":"BAL","tier":3,"adp":21.4,"projection":359.1},
    {"rank":15,"name":"Trey McBride","pos":"TE","team":"ARI","tier":3,"adp":22.6,"projection":239.4},
    {"rank":16,"name":"Jonathan Taylor","pos":"RB","team":"IND","tier":3,"adp":16.5,"projection":251.7},
    {"rank":17,"name":"Drake London","pos":"WR","team":"ATL","tier":4,"adp":17.8,"projection":254.9},
    {"rank":18,"name":"De'Von Achane","pos":"RB","team":"MIA","tier":4,"adp":19.2,"projection":249.6},
    {"rank":19,"name":"Jalen Hurts","pos":"QB","team":"PHI","tier":4,"adp":27.2,"projection":348.0},
    {"rank":20,"name":"Sam LaPorta","pos":"TE","team":"DET","tier":4,"adp":35.1,"projection":218.3},
]

DEMO = {
    "team_strength": 82,
    "team_rank": 3,
    "playoff_probability": 71,
    "championship_probability": 18,
    "lineup_gain": 6.4,
    "trade_opportunities": 4,
    "top_action": {
        "title": "Connect your ESPN league",
        "reason": "Once synced, the Command Center uses your actual league settings, teams, records, and roster data when available.",
        "confidence": 100,
        "gain": 0,
    },
    "power_rankings": [],
    "waivers": [
        {"player":"Emerging RB","position":"RB","rostered":"38%","faab":"12–18%","grade":"A-","reason":"Usage and goal-line work are trending up."},
        {"player":"High-Volume WR","position":"WR","rostered":"44%","faab":"8–12%","grade":"B+","reason":"Target share supports a weekly flex floor."},
        {"player":"Streaming TE","position":"TE","rostered":"19%","faab":"3–6%","grade":"B","reason":"Strong matchup and route participation."},
    ],
    "lineup": [
        {"slot":"QB","player":"Best Available QB","projection":22.4,"confidence":88},
        {"slot":"RB1","player":"Lead Running Back","projection":18.7,"confidence":91},
        {"slot":"RB2","player":"Volume Running Back","projection":15.9,"confidence":82},
        {"slot":"WR1","player":"Alpha Receiver","projection":19.2,"confidence":90},
        {"slot":"WR2","player":"Target Leader","projection":16.8,"confidence":85},
        {"slot":"FLEX","player":"Best Flex Option","projection":14.6,"confidence":84},
        {"slot":"TE","player":"Top Route TE","projection":10.8,"confidence":77},
    ],
    "matchups": [
        {"position":"QB","opponent":"vs. ATL","grade":"A","note":"Fast pace and favorable pass efficiency allowed."},
        {"position":"RB","opponent":"vs. CAR","grade":"A-","note":"Positive game script and strong red-zone opportunity."},
        {"position":"WR","opponent":"at TB","grade":"B+","note":"High passing volume offsets a tougher perimeter matchup."},
        {"position":"TE","opponent":"vs. LAC","grade":"B","note":"Middle-of-field targets project well."},
    ],
}

def load_snapshot() -> dict[str, Any] | None:
    try:
        if SNAPSHOT_FILE.exists():
            return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None

def save_snapshot(snapshot: dict[str, Any]) -> None:
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

def league_state() -> list[dict[str, Any]]:
    snapshot = load_snapshot()
    if snapshot:
        return [snapshot["league"]]
    return session.get("connected_leagues", [])

def set_league(item: dict[str, Any]) -> None:
    leagues = [x for x in session.get("connected_leagues", []) if not (
        x.get("platform") == item.get("platform")
        and str(x.get("league_id")) == str(item.get("league_id"))
    )]
    leagues.insert(0, item)
    session["connected_leagues"] = leagues[:8]

def scoring_label(settings: Any) -> str:
    for attr in ("scoring_format", "scoring_type", "scoringFormat"):
        value = getattr(settings, attr, None)
        if value:
            text = str(value).upper()
            if "HALF" in text:
                return "Half PPR"
            if "PPR" in text:
                return "Full PPR"
            if "STD" in text or "STANDARD" in text:
                return "Standard"
            return str(value)
    return "League scoring"

def build_settings(settings: Any) -> dict[str, Any]:
    def safe(attr: str, default: Any = None):
        value = getattr(settings, attr, default)
        try:
            json.dumps(value)
            return value
        except Exception:
            return str(value)
    return {
        "name": safe("name", "ESPN League"),
        "team_count": safe("team_count"),
        "reg_season_count": safe("reg_season_count"),
        "playoff_team_count": safe("playoff_team_count"),
        "acquisition_budget": safe("acquisition_budget"),
        "trade_deadline": safe("trade_deadline"),
        "scoring": scoring_label(settings),
    }

def player_to_dict(player: Any) -> dict[str, Any]:
    return {
        "name": getattr(player, "name", "Unknown Player"),
        "position": getattr(player, "position", ""),
        "pro_team": getattr(player, "proTeam", getattr(player, "pro_team", "")),
        "projected_total": round(float(getattr(player, "projected_total_points", 0) or 0), 2),
        "total_points": round(float(getattr(player, "total_points", 0) or 0), 2),
        "injury_status": getattr(player, "injuryStatus", getattr(player, "injury_status", "")),
        "lineup_slot": getattr(player, "lineupSlot", getattr(player, "lineup_slot", "")),
    }

def team_to_dict(team: Any) -> dict[str, Any]:
    roster = getattr(team, "roster", None) or []
    return {
        "team_name": str(getattr(team, "team_name", "Unnamed Team")).strip(),
        "owner": str(getattr(team, "owner", "") or ""),
        "wins": int(getattr(team, "wins", 0) or 0),
        "losses": int(getattr(team, "losses", 0) or 0),
        "ties": int(getattr(team, "ties", 0) or 0),
        "points_for": round(float(getattr(team, "points_for", 0) or 0), 2),
        "points_against": round(float(getattr(team, "points_against", 0) or 0), 2),
        "roster_size": len(roster),
        "roster": [player_to_dict(p) for p in roster],
    }

def identify_user_team(teams: list[dict[str, Any]]) -> dict[str, Any] | None:
    for team in teams:
        if "chad" in team["team_name"].lower():
            return team
    return None

def power_rankings_from_teams(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not teams:
        return []
    max_pf = max([t["points_for"] for t in teams] + [1])
    rows = []
    for team in teams:
        games = team["wins"] + team["losses"] + team["ties"]
        win_pct = (team["wins"] + 0.5 * team["ties"]) / games if games else 0
        pf_score = team["points_for"] / max_pf if max_pf else 0
        rating = round((win_pct * 60 + pf_score * 40) if games else (50 + pf_score * 20))
        rows.append({
            "team": team["team_name"],
            "record": f'{team["wins"]}-{team["losses"]}',
            "rating": rating,
        })
    rows.sort(key=lambda x: x["rating"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
        row["playoffs"] = max(10, min(95, round(20 + (len(rows)-i+1) / max(len(rows),1) * 70)))
    return rows

def dashboard_context() -> dict[str, Any]:
    snapshot = load_snapshot()
    if not snapshot:
        return {
            "connected": False,
            "league": None,
            "settings": None,
            "teams": [],
            "user_team": None,
            "analytics": DEMO,
        }
    teams = snapshot.get("teams", [])
    rankings = power_rankings_from_teams(teams)
    user_team = identify_user_team(teams)
    user_rank = next((r["rank"] for r in rankings if user_team and r["team"] == user_team["team_name"]), None)
    strength = next((r["rating"] for r in rankings if user_team and r["team"] == user_team["team_name"]), 50)
    analytics = dict(DEMO)
    analytics["power_rankings"] = rankings
    analytics["team_strength"] = strength
    analytics["team_rank"] = user_rank or "-"
    analytics["top_action"] = {
        "title": "ESPN league connected",
        "reason": "Gridiron IQ is now reading your real league structure. Roster-based tools become more useful as ESPN populates drafted players and weekly data.",
        "confidence": 100,
        "gain": 0,
    }
    return {
        "connected": True,
        "league": snapshot.get("league"),
        "settings": snapshot.get("settings"),
        "teams": teams,
        "user_team": user_team,
        "analytics": analytics,
    }

def draft_rankings_for_scoring(scoring: str) -> list[dict[str, Any]]:
    rows = [dict(p) for p in BASE_RANKINGS]
    scoring_upper = (scoring or "").upper()
    for p in rows:
        bonus = 0.0
        if "PPR" in scoring_upper and p["pos"] == "WR":
            bonus += 4.0
        if "FULL" in scoring_upper and p["pos"] == "TE":
            bonus += 2.0
        if "STANDARD" in scoring_upper and p["pos"] == "RB":
            bonus += 4.0
        p["league_score"] = round(p["projection"] + bonus, 1)
    rows.sort(key=lambda p: p["league_score"], reverse=True)
    for i, p in enumerate(rows, 1):
        p["league_rank"] = i
    return rows

def page(template: str, **context: Any):
    dash = dashboard_context()
    return render_template(
        template,
        user=USER,
        leagues=league_state(),
        analytics=dash["analytics"],
        connected=dash["connected"],
        league=dash["league"],
        league_settings=dash["settings"],
        teams=dash["teams"],
        user_team=dash["user_team"],
        **context,
    )

@app.get("/")
def home():
    return redirect(url_for("dashboard"))

@app.get("/app")
@app.get("/dashboard")
def dashboard():
    return page("dashboard.html")

@app.get("/draft-center")
def draft_center():
    snapshot = load_snapshot()
    scoring = snapshot.get("settings", {}).get("scoring", "League scoring") if snapshot else "League scoring"
    return page("draft_center.html", players=draft_rankings_for_scoring(scoring), scoring=scoring)

@app.get("/league-sync")
@app.get("/connect-league")
def league_sync():
    return page(
        "league_sync.html",
        yahoo_configured=bool(os.getenv("YAHOO_CLIENT_ID") and os.getenv("YAHOO_CLIENT_SECRET")),
        yahoo_redirect=os.getenv("YAHOO_REDIRECT_URI", ""),
    )

@app.get("/lineup-optimizer")
def lineup_optimizer():
    return page("lineup.html")

@app.get("/waiver-assistant")
def waiver_assistant():
    return page("waivers.html")

@app.get("/trade-analyzer")
def trade_analyzer():
    return page("trade.html")

@app.get("/matchup-analyzer")
def matchup_analyzer():
    return page("matchups.html")

@app.get("/league-intelligence")
def league_intelligence():
    return page("league_intelligence.html")

@app.get("/reports")
def reports():
    return page("reports.html")

@app.get("/settings")
def settings():
    return page("settings.html")

@app.get("/help")
def help_page():
    return page("help.html")

@app.get("/health")
@app.get("/api/health")
def health():
    snapshot = load_snapshot()
    return jsonify(
        ok=True,
        service="Gridiron IQ",
        mode="single-user",
        espn_snapshot=bool(snapshot),
        time=datetime.now(timezone.utc).isoformat(),
    )

@app.post("/api/demo/connect")
def demo_connect():
    return jsonify(ok=True, message="Demo mode is available, but ESPN sync is recommended.")

@app.post("/api/league/disconnect")
def league_disconnect():
    if SNAPSHOT_FILE.exists():
        SNAPSHOT_FILE.unlink()
    session.pop("connected_leagues", None)
    return jsonify(ok=True)

@app.post("/api/espn/test")
def espn_test():
    payload = request.get_json(silent=True) or {}
    required = ["league_id", "season", "swid", "espn_s2"]
    if any(not str(payload.get(k, "")).strip() for k in required):
        return jsonify(ok=False, error="Complete League ID, season, SWID, and espn_s2."), 400
    try:
        from espn_api.football import League
        league = League(
            league_id=int(payload["league_id"]),
            year=int(payload["season"]),
            swid=str(payload["swid"]).strip(),
            espn_s2=str(payload["espn_s2"]).strip(),
        )
        return jsonify(
            ok=True,
            message="ESPN connection successful.",
            league_name=getattr(league.settings, "name", "ESPN League"),
            team_count=len(league.teams),
            current_week=getattr(league, "current_week", None),
            scoring=scoring_label(league.settings),
        )
    except Exception as exc:
        return jsonify(ok=False, error="ESPN rejected the connection.", detail=str(exc)), 400

@app.post("/api/espn/sync")
def espn_sync():
    payload = request.get_json(silent=True) or {}
    required = ["league_id", "season", "swid", "espn_s2"]
    if any(not str(payload.get(k, "")).strip() for k in required):
        return jsonify(ok=False, error="Complete all ESPN connection fields."), 400
    try:
        from espn_api.football import League
        espn = League(
            league_id=int(payload["league_id"]),
            year=int(payload["season"]),
            swid=str(payload["swid"]).strip(),
            espn_s2=str(payload["espn_s2"]).strip(),
        )
        teams = [team_to_dict(t) for t in espn.teams]
        settings = build_settings(espn.settings)
        item = {
            "platform": "ESPN",
            "league_id": str(payload["league_id"]),
            "league_name": settings["name"],
            "season": int(payload["season"]),
            "teams": len(teams),
            "current_week": getattr(espn, "current_week", None),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        snapshot = {
            "league": item,
            "settings": settings,
            "teams": teams,
        }
        save_snapshot(snapshot)
        set_league(item)
        return jsonify(
            ok=True,
            message="ESPN league synced and saved to the Gridiron IQ snapshot.",
            league=item,
            settings=settings,
            user_team=identify_user_team(teams),
            teams=teams,
        )
    except Exception as exc:
        return jsonify(ok=False, error="ESPN sync failed.", detail=str(exc)), 400

@app.get("/api/espn/snapshot")
def espn_snapshot():
    snapshot = load_snapshot()
    if not snapshot:
        return jsonify(ok=False, error="No ESPN snapshot saved yet."), 404
    return jsonify(ok=True, snapshot=snapshot)

@app.post("/api/sleeper/sync")
def sleeper_sync():
    payload = request.get_json(silent=True) or {}
    league_id = str(payload.get("league_id", "")).strip()
    if not league_id:
        return jsonify(ok=False, error="Enter a Sleeper league ID."), 400
    try:
        league_response = requests.get(f"https://api.sleeper.app/v1/league/{league_id}", timeout=20)
        league_response.raise_for_status()
        league = league_response.json()
        return jsonify(ok=True, message="Sleeper league found.", league=league)
    except Exception as exc:
        return jsonify(ok=False, error="Sleeper sync failed.", detail=str(exc)), 400

@app.get("/auth/yahoo/start")
def yahoo_start():
    client_id = os.getenv("YAHOO_CLIENT_ID", "").strip()
    redirect_uri = os.getenv("YAHOO_REDIRECT_URI", "").strip()
    if not client_id or not redirect_uri:
        return page("error.html", code=400, message="Yahoo is not configured in Render."), 400
    state = os.urandom(18).hex()
    session["yahoo_state"] = state
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "language": "en-us",
        "state": state,
    })
    return redirect("https://api.login.yahoo.com/oauth2/request_auth?" + query)

@app.get("/auth/yahoo/callback")
def yahoo_callback():
    if request.args.get("state") != session.get("yahoo_state"):
        return page("error.html", code=400, message="Yahoo authorization state did not match."), 400
    code = request.args.get("code", "")
    if not code:
        return page("error.html", code=400, message="Yahoo did not return an authorization code."), 400
    try:
        response = requests.post(
            "https://api.login.yahoo.com/oauth2/get_token",
            auth=(os.getenv("YAHOO_CLIENT_ID", ""), os.getenv("YAHOO_CLIENT_SECRET", "")),
            data={
                "grant_type": "authorization_code",
                "redirect_uri": os.getenv("YAHOO_REDIRECT_URI", ""),
                "code": code,
            },
            timeout=25,
        )
        response.raise_for_status()
        token = response.json()
        session["yahoo_access_token"] = token.get("access_token")
        session["yahoo_refresh_token"] = token.get("refresh_token")
        return redirect(url_for("league_sync", yahoo="connected"))
    except Exception as exc:
        return page("error.html", code=502, message=f"Yahoo authorization failed: {exc}"), 502

@app.post("/api/trade/analyze")
def trade_analyze():
    payload = request.get_json(silent=True) or {}
    give = str(payload.get("give", "")).strip()
    receive = str(payload.get("receive", "")).strip()
    if not give or not receive:
        return jsonify(ok=False, error="Enter players on both sides of the trade."), 400
    return jsonify(ok=True, verdict="Fair starting point", confidence=72)

@app.post("/api/lineup/optimize")
def lineup_optimize():
    return jsonify(ok=True, lineup=DEMO["lineup"], projected_total=round(sum(x["projection"] for x in DEMO["lineup"]),1))

@app.post("/api/waivers/analyze")
def waiver_analyze():
    return jsonify(ok=True, recommendations=DEMO["waivers"])

@app.post("/api/draft/recommend")
def draft_recommend():
    payload = request.get_json(silent=True) or {}
    drafted = {str(x).lower() for x in payload.get("drafted", [])}
    position = str(payload.get("position", "")).upper()
    snapshot = load_snapshot()
    scoring = snapshot.get("settings", {}).get("scoring", "League scoring") if snapshot else "League scoring"
    available = [
        p for p in draft_rankings_for_scoring(scoring)
        if p["name"].lower() not in drafted and (not position or p["pos"] == position)
    ]
    return jsonify(ok=True, scoring=scoring, recommendations=available[:5])

@app.errorhandler(404)
def not_found(_):
    return page("error.html", code=404, message="Page not found."), 404

@app.errorhandler(500)
def server_error(_):
    return page("error.html", code=500, message="Something went wrong. Check the Render logs for the traceback."), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=os.getenv("FLASK_DEBUG") == "1")
