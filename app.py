from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "gridiron-iq-development-key-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    JSON_SORT_KEYS=False,
)

USER = {"id": 1, "name": "Chad", "email": "chad@totalatlantagroup.com"}

RANKINGS = [
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
        "title": "Start the higher-volume FLEX option",
        "reason": "The recommended player projects for more touches, a stronger red-zone role, and a safer weekly floor.",
        "confidence": 84,
        "gain": 4.4,
    },
    "power_rankings": [
        {"rank":1,"team":"Sunday Crushers","record":"7-2","rating":91,"playoffs":84},
        {"rank":2,"team":"Fourth & Long","record":"6-3","rating":87,"playoffs":78},
        {"rank":3,"team":"Chad's Team","record":"6-3","rating":82,"playoffs":71},
        {"rank":4,"team":"Gridiron Kings","record":"5-4","rating":79,"playoffs":63},
        {"rank":5,"team":"Red Zone Rebels","record":"5-4","rating":76,"playoffs":57},
    ],
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

def league_state() -> list[dict[str, Any]]:
    return session.get("connected_leagues", [])

def set_league(item: dict[str, Any]) -> None:
    leagues = [x for x in league_state() if not (
        x.get("platform") == item.get("platform") and
        str(x.get("league_id")) == str(item.get("league_id"))
    )]
    leagues.insert(0, item)
    session["connected_leagues"] = leagues[:8]

def page(template: str, **context: Any):
    return render_template(template, user=USER, leagues=league_state(), analytics=DEMO, **context)

@app.get("/")
def home():
    return redirect(url_for("dashboard"))

@app.get("/app")
@app.get("/dashboard")
def dashboard():
    return page("dashboard.html")

@app.get("/draft-center")
def draft_center():
    return page("draft_center.html", players=RANKINGS)

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
    return jsonify(
        ok=True,
        service="Gridiron IQ",
        mode="single-user",
        python=os.sys.version.split()[0],
        time=datetime.now(timezone.utc).isoformat(),
    )

@app.post("/api/demo/connect")
def demo_connect():
    item = {
        "platform": "Demo",
        "league_id": "demo-2026",
        "league_name": "Gridiron IQ Demo League",
        "season": 2026,
        "teams": 12,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    set_league(item)
    return jsonify(ok=True, message="Demo league connected.", league=item)

@app.post("/api/league/disconnect")
def league_disconnect():
    payload = request.get_json(silent=True) or {}
    platform = str(payload.get("platform", "")).lower()
    league_id = str(payload.get("league_id", ""))
    session["connected_leagues"] = [
        x for x in league_state()
        if not (str(x.get("platform", "")).lower() == platform and str(x.get("league_id", "")) == league_id)
    ]
    return jsonify(ok=True)

@app.post("/api/espn/test")
def espn_test():
    payload = request.get_json(silent=True) or {}
    required = ["league_id", "season", "swid", "espn_s2"]
    missing = [k for k in required if not str(payload.get(k, "")).strip()]
    if missing:
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
        )
    except Exception as exc:
        return jsonify(
            ok=False,
            error="ESPN rejected the connection.",
            detail=str(exc),
            suggestion="Refresh both ESPN cookies and confirm the league ID and season.",
        ), 400

@app.post("/api/espn/sync")
def espn_sync():
    payload = request.get_json(silent=True) or {}
    required = ["league_id", "season", "swid", "espn_s2"]
    missing = [k for k in required if not str(payload.get(k, "")).strip()]
    if missing:
        return jsonify(ok=False, error="Complete all ESPN connection fields."), 400
    try:
        from espn_api.football import League
        league = League(
            league_id=int(payload["league_id"]),
            year=int(payload["season"]),
            swid=str(payload["swid"]).strip(),
            espn_s2=str(payload["espn_s2"]).strip(),
        )
        teams = []
        for team in league.teams:
            teams.append({
                "team_name": getattr(team, "team_name", "Unnamed Team"),
                "owner": getattr(team, "owner", ""),
                "wins": getattr(team, "wins", 0),
                "losses": getattr(team, "losses", 0),
                "points_for": round(float(getattr(team, "points_for", 0) or 0), 2),
                "roster_size": len(getattr(team, "roster", []) or []),
            })
        item = {
            "platform": "ESPN",
            "league_id": str(payload["league_id"]),
            "league_name": getattr(league.settings, "name", "ESPN League"),
            "season": int(payload["season"]),
            "teams": len(teams),
            "current_week": getattr(league, "current_week", None),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        set_league(item)
        return jsonify(ok=True, message="ESPN league synced.", league=item, teams=teams)
    except Exception as exc:
        return jsonify(ok=False, error="ESPN sync failed.", detail=str(exc)), 400

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
        rosters_response = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/rosters", timeout=20)
        rosters_response.raise_for_status()
        rosters = rosters_response.json()
        item = {
            "platform": "Sleeper",
            "league_id": league_id,
            "league_name": league.get("name", "Sleeper League"),
            "season": int(league.get("season") or 2026),
            "teams": int(league.get("total_rosters") or len(rosters)),
            "status": league.get("status", ""),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        set_league(item)
        return jsonify(ok=True, message="Sleeper league synced.", league=item)
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
        session["yahoo_connected"] = True
        return redirect(url_for("league_sync", yahoo="connected"))
    except Exception as exc:
        return page("error.html", code=502, message=f"Yahoo authorization failed: {exc}"), 502

@app.post("/api/trade/analyze")
def trade_analyze():
    payload = request.get_json(silent=True) or {}
    give = str(payload.get("give", "")).strip()
    receive = str(payload.get("receive", "")).strip()
    scoring = str(payload.get("scoring", "Half-PPR"))
    if not give or not receive:
        return jsonify(ok=False, error="Enter players on both sides of the trade."), 400

    give_count = len([x for x in give.split(",") if x.strip()])
    receive_count = len([x for x in receive.split(",") if x.strip()])
    balance = 76 - abs(give_count - receive_count) * 8
    return jsonify(
        ok=True,
        verdict="Fair starting point" if balance >= 65 else "Needs additional value",
        confidence=max(48, min(88, balance)),
        scoring=scoring,
        summary=f"In {scoring}, compare role stability, target or touch volume, injury risk, and positional scarcity before accepting.",
        recommendation="Use this as a screening result, then confirm with live projections after connecting your league.",
    )

@app.post("/api/lineup/optimize")
def lineup_optimize():
    payload = request.get_json(silent=True) or {}
    risk = str(payload.get("risk", "balanced"))
    lineup = [dict(x) for x in DEMO["lineup"]]
    adjustment = {"safe": -0.7, "balanced": 0.0, "upside": 1.2}.get(risk, 0.0)
    for row in lineup:
        row["projection"] = round(row["projection"] + adjustment, 1)
    return jsonify(ok=True, risk=risk, projected_total=round(sum(x["projection"] for x in lineup), 1), lineup=lineup)

@app.post("/api/waivers/analyze")
def waiver_analyze():
    payload = request.get_json(silent=True) or {}
    budget = int(payload.get("budget", 100) or 100)
    items = []
    for x in DEMO["waivers"]:
        item = dict(x)
        item["max_bid"] = round(budget * {"A-":0.18,"B+":0.12,"B":0.06}.get(x["grade"],0.05))
        items.append(item)
    return jsonify(ok=True, budget=budget, recommendations=items)

@app.post("/api/draft/recommend")
def draft_recommend():
    payload = request.get_json(silent=True) or {}
    drafted = {str(x).lower() for x in payload.get("drafted", [])}
    position = str(payload.get("position", "")).upper()
    available = [p for p in RANKINGS if p["name"].lower() not in drafted and (not position or p["pos"] == position)]
    return jsonify(ok=True, recommendations=available[:5])

@app.errorhandler(404)
def not_found(_):
    return page("error.html", code=404, message="Page not found."), 404

@app.errorhandler(500)
def server_error(_):
    return page("error.html", code=500, message="Something went wrong. Check the Render logs for the full traceback."), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=os.getenv("FLASK_DEBUG") == "1")
