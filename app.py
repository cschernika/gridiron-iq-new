from __future__ import annotations

import json, os, uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from math import exp
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from draft_evaluation_engine import (
    baseline_metrics as position_baseline_metrics,
    evaluate_player as evaluate_position_player,
    load_position_weights,
)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Set GRIDIRON_DATA_DIR=/var/data on Render when a persistent disk is mounted.
# Without the environment variable, local development continues to use ./data.
_data_dir_setting = str(os.getenv("GRIDIRON_DATA_DIR", "") or "").strip()
DATA_DIR = Path(_data_dir_setting) if _data_dir_setting else (BASE_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
ESPN_SNAPSHOT = DATA_DIR / "espn_snapshot.json"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

USER = {"id": 1, "name": "Chad"}

DEMO = {
    "team_strength": 86, "team_rank": 3, "playoff_probability": 74,
    "championship_probability": 18, "lineup_gain": 7.1, "trade_opportunities": 4,
    "power_rankings": [
        {"rank":1,"team":"Sunday Crushers","rating":91,"playoffs":82},
        {"rank":2,"team":"Fourth & Long","rating":88,"playoffs":77},
        {"rank":3,"team":"Chad's Team","rating":86,"playoffs":74},
        {"rank":4,"team":"Gridiron Gurus","rating":84,"playoffs":69},
        {"rank":5,"team":"Red Zone Renegades","rating":82,"playoffs":63},
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
    "waivers": [
        {"player":"Emerging RB","position":"RB","rostered":"38%","faab":"12–18%","grade":"A-","reason":"Usage is trending up."},
        {"player":"High-Volume WR","position":"WR","rostered":"44%","faab":"8–12%","grade":"B+","reason":"Strong target share."},
        {"player":"Streaming TE","position":"TE","rostered":"19%","faab":"3–6%","grade":"B","reason":"Favorable matchup."},
    ],
}

PLAYERS = [
    {"rank":1,"name":"Ja'Marr Chase","pos":"WR","team":"CIN","tier":1,"adp":1.4,"projection":312.2},
    {"rank":2,"name":"Bijan Robinson","pos":"RB","team":"ATL","tier":1,"adp":2.1,"projection":298.4},
    {"rank":3,"name":"Justin Jefferson","pos":"WR","team":"MIN","tier":1,"adp":3.2,"projection":301.1},
    {"rank":4,"name":"CeeDee Lamb","pos":"WR","team":"DAL","tier":1,"adp":4.6,"projection":294.3},
    {"rank":5,"name":"Jahmyr Gibbs","pos":"RB","team":"DET","tier":1,"adp":5.1,"projection":286.7},
    {"rank":6,"name":"Amon-Ra St. Brown","pos":"WR","team":"DET","tier":2,"adp":6.4,"projection":285.2},
    {"rank":7,"name":"Puka Nacua","pos":"WR","team":"LAR","tier":2,"adp":7.2,"projection":279.8},
    {"rank":8,"name":"Saquon Barkley","pos":"RB","team":"PHI","tier":2,"adp":8.1,"projection":276.5},
    {"rank":9,"name":"Malik Nabers","pos":"WR","team":"NYG","tier":2,"adp":9.8,"projection":274.7},
    {"rank":10,"name":"Nico Collins","pos":"WR","team":"HOU","tier":2,"adp":11.5,"projection":269.8},
    {"rank":11,"name":"Drake London","pos":"WR","team":"ATL","tier":3,"adp":13.8,"projection":263.1},
    {"rank":12,"name":"Breece Hall","pos":"RB","team":"NYJ","tier":3,"adp":12.7,"projection":258.2},
    {"rank":13,"name":"Jonathan Taylor","pos":"RB","team":"IND","tier":3,"adp":16.5,"projection":251.7},
    {"rank":14,"name":"De'Von Achane","pos":"RB","team":"MIA","tier":3,"adp":17.8,"projection":249.6},
    {"rank":15,"name":"Brock Bowers","pos":"TE","team":"LV","tier":2,"adp":14.8,"projection":252.0},
    {"rank":16,"name":"Trey McBride","pos":"TE","team":"ARI","tier":3,"adp":22.6,"projection":239.4},
    {"rank":17,"name":"Josh Allen","pos":"QB","team":"BUF","tier":2,"adp":18.5,"projection":368.6},
    {"rank":18,"name":"Lamar Jackson","pos":"QB","team":"BAL","tier":3,"adp":21.4,"projection":359.1},
    {"rank":19,"name":"Jalen Hurts","pos":"QB","team":"PHI","tier":3,"adp":27.2,"projection":348.0},
    {"rank":20,"name":"Sam LaPorta","pos":"TE","team":"DET","tier":4,"adp":35.1,"projection":218.3},
]


MOCK_EXTRA_PLAYERS = [
    {"rank":21,"name":"A.J. Brown","pos":"WR","team":"PHI","tier":4,"adp":20.4,"projection":245.0},
    {"rank":22,"name":"Garrett Wilson","pos":"WR","team":"NYJ","tier":4,"adp":23.3,"projection":242.0},
    {"rank":23,"name":"Kyren Williams","pos":"RB","team":"LAR","tier":4,"adp":24.5,"projection":238.0},
    {"rank":24,"name":"Marvin Harrison Jr.","pos":"WR","team":"ARI","tier":4,"adp":25.6,"projection":240.0},
    {"rank":25,"name":"James Cook","pos":"RB","team":"BUF","tier":4,"adp":26.5,"projection":234.0},
    {"rank":26,"name":"Brian Thomas Jr.","pos":"WR","team":"JAX","tier":4,"adp":28.2,"projection":236.0},
    {"rank":27,"name":"Josh Jacobs","pos":"RB","team":"GB","tier":4,"adp":29.1,"projection":231.0},
    {"rank":28,"name":"Mike Evans","pos":"WR","team":"TB","tier":4,"adp":30.2,"projection":229.0},
    {"rank":29,"name":"Davante Adams","pos":"WR","team":"LAR","tier":4,"adp":31.4,"projection":226.0},
    {"rank":30,"name":"Kenneth Walker III","pos":"RB","team":"SEA","tier":4,"adp":32.5,"projection":224.0},
    {"rank":31,"name":"Jayden Daniels","pos":"QB","team":"WAS","tier":4,"adp":33.0,"projection":340.0},
    {"rank":32,"name":"Terry McLaurin","pos":"WR","team":"WAS","tier":5,"adp":34.3,"projection":222.0},
    {"rank":33,"name":"DJ Moore","pos":"WR","team":"CHI","tier":5,"adp":36.4,"projection":218.0},
    {"rank":34,"name":"Isiah Pacheco","pos":"RB","team":"KC","tier":5,"adp":37.6,"projection":216.0},
    {"rank":35,"name":"George Kittle","pos":"TE","team":"SF","tier":5,"adp":38.8,"projection":205.0},
    {"rank":36,"name":"Chris Olave","pos":"WR","team":"NO","tier":5,"adp":39.6,"projection":214.0},
    {"rank":37,"name":"Joe Burrow","pos":"QB","team":"CIN","tier":5,"adp":40.5,"projection":332.0},
    {"rank":38,"name":"DK Metcalf","pos":"WR","team":"PIT","tier":5,"adp":41.3,"projection":211.0},
    {"rank":39,"name":"Alvin Kamara","pos":"RB","team":"NO","tier":5,"adp":42.7,"projection":208.0},
    {"rank":40,"name":"Xavier Worthy","pos":"WR","team":"KC","tier":5,"adp":44.0,"projection":207.0},
    {"rank":41,"name":"Rashee Rice","pos":"WR","team":"KC","tier":5,"adp":45.2,"projection":205.0},
    {"rank":42,"name":"David Montgomery","pos":"RB","team":"DET","tier":5,"adp":46.0,"projection":201.0},
    {"rank":43,"name":"Zay Flowers","pos":"WR","team":"BAL","tier":5,"adp":47.4,"projection":203.0},
    {"rank":44,"name":"George Pickens","pos":"WR","team":"DAL","tier":5,"adp":48.7,"projection":201.0},
    {"rank":45,"name":"James Conner","pos":"RB","team":"ARI","tier":5,"adp":49.4,"projection":198.0},
    {"rank":46,"name":"Rome Odunze","pos":"WR","team":"CHI","tier":6,"adp":50.8,"projection":199.0},
    {"rank":47,"name":"DeVonta Smith","pos":"WR","team":"PHI","tier":6,"adp":52.1,"projection":197.0},
    {"rank":48,"name":"Travis Kelce","pos":"TE","team":"KC","tier":6,"adp":53.0,"projection":191.0},
    {"rank":49,"name":"Aaron Jones","pos":"RB","team":"MIN","tier":6,"adp":54.5,"projection":194.0},
    {"rank":50,"name":"Calvin Ridley","pos":"WR","team":"TEN","tier":6,"adp":55.4,"projection":193.0},
    {"rank":51,"name":"Tee Higgins","pos":"WR","team":"CIN","tier":6,"adp":56.2,"projection":191.0},
    {"rank":52,"name":"D'Andre Swift","pos":"RB","team":"CHI","tier":6,"adp":57.6,"projection":189.0},
    {"rank":53,"name":"Patrick Mahomes","pos":"QB","team":"KC","tier":6,"adp":58.1,"projection":326.0},
    {"rank":54,"name":"Jaylen Waddle","pos":"WR","team":"MIA","tier":6,"adp":59.5,"projection":188.0},
    {"rank":55,"name":"Tony Pollard","pos":"RB","team":"TEN","tier":6,"adp":60.7,"projection":186.0},
    {"rank":56,"name":"Mark Andrews","pos":"TE","team":"BAL","tier":6,"adp":62.0,"projection":184.0},
    {"rank":57,"name":"Jordan Addison","pos":"WR","team":"MIN","tier":6,"adp":63.2,"projection":185.0},
    {"rank":58,"name":"Rhamondre Stevenson","pos":"RB","team":"NE","tier":6,"adp":64.8,"projection":181.0},
    {"rank":59,"name":"Ladd McConkey","pos":"WR","team":"LAC","tier":6,"adp":65.5,"projection":183.0},
    {"rank":60,"name":"Kyler Murray","pos":"QB","team":"ARI","tier":6,"adp":66.7,"projection":318.0},
    {"rank":61,"name":"Ricky Pearsall","pos":"WR","team":"SF","tier":7,"adp":68.1,"projection":178.0},
    {"rank":62,"name":"Najee Harris","pos":"RB","team":"LAC","tier":7,"adp":69.4,"projection":176.0},
    {"rank":63,"name":"David Njoku","pos":"TE","team":"CLE","tier":7,"adp":70.2,"projection":172.0},
    {"rank":64,"name":"Chris Godwin","pos":"WR","team":"TB","tier":7,"adp":71.8,"projection":176.0},
    {"rank":65,"name":"Bo Nix","pos":"QB","team":"DEN","tier":7,"adp":73.0,"projection":311.0},
    {"rank":66,"name":"Javonte Williams","pos":"RB","team":"DAL","tier":7,"adp":74.5,"projection":171.0},
    {"rank":67,"name":"Jerry Jeudy","pos":"WR","team":"CLE","tier":7,"adp":75.8,"projection":173.0},
    {"rank":68,"name":"Evan Engram","pos":"TE","team":"DEN","tier":7,"adp":77.2,"projection":168.0},
    {"rank":69,"name":"Dak Prescott","pos":"QB","team":"DAL","tier":7,"adp":78.4,"projection":306.0},
    {"rank":70,"name":"Tyjae Spears","pos":"RB","team":"TEN","tier":7,"adp":79.6,"projection":169.0},
    {"rank":71,"name":"Jakobi Meyers","pos":"WR","team":"LV","tier":7,"adp":81.0,"projection":170.0},
    {"rank":72,"name":"Tucker Kraft","pos":"TE","team":"GB","tier":7,"adp":82.5,"projection":164.0},
    {"rank":73,"name":"Rachaad White","pos":"RB","team":"TB","tier":7,"adp":84.0,"projection":165.0},
    {"rank":74,"name":"Jordan Love","pos":"QB","team":"GB","tier":7,"adp":85.4,"projection":302.0},
    {"rank":75,"name":"Keon Coleman","pos":"WR","team":"BUF","tier":7,"adp":86.9,"projection":166.0},
    {"rank":76,"name":"Zach Charbonnet","pos":"RB","team":"SEA","tier":8,"adp":88.1,"projection":161.0},
    {"rank":77,"name":"Christian Kirk","pos":"WR","team":"HOU","tier":8,"adp":89.7,"projection":163.0},
    {"rank":78,"name":"Dallas Goedert","pos":"TE","team":"PHI","tier":8,"adp":91.0,"projection":158.0},
    {"rank":79,"name":"Trevor Lawrence","pos":"QB","team":"JAX","tier":8,"adp":92.5,"projection":297.0},
    {"rank":80,"name":"Jaylen Warren","pos":"RB","team":"PIT","tier":8,"adp":94.0,"projection":159.0},
]

MOCK_PLAYER_POOL = PLAYERS + MOCK_EXTRA_PLAYERS

CONTEXTS = {
    "espn-gramps":{"key":"espn-gramps","league_name":"Gramp's Gridiron","platform":"ESPN","scoring":"Full PPR","teams":12,"draft_type":"Snake","draft_slot":7,"round":1,"pick_in_round":7,"starters":{"QB":1,"RB":2,"WR":2,"TE":1,"FLEX":1}},
    "yahoo-westrockers":{"key":"yahoo-westrockers","league_name":"WestRockers","platform":"Yahoo","scoring":"Half PPR","teams":12,"draft_type":"Snake","draft_slot":7,"round":1,"pick_in_round":7,"starters":{"QB":1,"RB":2,"WR":2,"TE":1,"FLEX":1}},
}

def load_snapshot():
    try:
        return json.loads(ESPN_SNAPSHOT.read_text()) if ESPN_SNAPSHOT.exists() else None
    except Exception:
        return None

def save_snapshot(data):
    ESPN_SNAPSHOT.write_text(json.dumps(data, indent=2), encoding="utf-8")

def short_scoring(settings):
    for attr in ("scoring_format","scoring_type","scoringFormat"):
        value = getattr(settings, attr, None)
        if value and not isinstance(value, (dict,list,tuple,set)):
            text = str(value).upper()
            if "HALF" in text and "PPR" in text: return "Half PPR"
            if "PPR" in text: return "Full PPR"
            if "STD" in text or "STANDARD" in text: return "Standard"
    return "Full PPR"

def player_dict(player):
    return {
        "player_id": str(getattr(player, "playerId", "") or getattr(player, "player_id", "") or ""),
        "name": str(getattr(player, "name", "") or "").strip(),
        "position": str(getattr(player, "position", "") or "").upper(),
        "pro_team": str(getattr(player, "proTeam", "") or getattr(player, "pro_team", "") or ""),
        "lineup_slot": str(getattr(player, "slot_position", "") or getattr(player, "lineupSlot", "") or ""),
        "projected_points": round(float(getattr(player, "projected_points", 0) or 0), 2),
        "total_points": round(float(getattr(player, "total_points", 0) or 0), 2),
        "injury_status": str(getattr(player, "injuryStatus", "") or getattr(player, "injury_status", "") or ""),
    }

def team_dict(team):
    roster = getattr(team, "roster", None) or []
    return {
        "team_id": str(getattr(team, "team_id", "") or getattr(team, "teamId", "") or ""),
        "team_name": str(getattr(team,"team_name","Unnamed Team")).strip(),
        "owner": str(getattr(team,"owner","") or ""),
        "wins": int(getattr(team,"wins",0) or 0),
        "losses": int(getattr(team,"losses",0) or 0),
        "ties": int(getattr(team,"ties",0) or 0),
        "points_for": round(float(getattr(team,"points_for",0) or 0),2),
        "roster_size": len(roster),
        "roster": [player_dict(p) for p in roster],
    }

def user_team(teams):
    # Prefer Chad's named team, then any owner/team containing Chad.
    for t in teams:
        if "chad" in str(t.get("team_name","")).lower():
            return t
    for t in teams:
        if "chad" in str(t.get("owner","")).lower():
            return t
    return None

def dashboard_analytics_with_actual_teams(
    teams,
    expected_team_count=None,
):
    """
    Preserve the dashboard's existing analytics schema while showing every
    configured league slot.

    ESPN can return fewer team objects than the configured league size when a
    slot is unclaimed or a manager has not joined yet. Missing slots are shown
    as Open Team Slot rather than disappearing from Power Rankings.
    """
    analytics = {
        key: (
            [dict(item) for item in value]
            if isinstance(value, list)
            else value
        )
        for key, value in DEMO.items()
    }

    actual_teams = [
        dict(team)
        for team in (teams or [])
        if isinstance(team, dict)
    ]

    try:
        configured_count = int(expected_team_count or 0)
    except (TypeError, ValueError):
        configured_count = 0

    total_slots = max(configured_count, len(actual_teams))

    if total_slots <= 0:
        return analytics

    # Keep every ESPN team exactly once. Empty or duplicate names receive a
    # stable fallback label rather than being omitted.
    ranking_rows = []
    seen_names = {}

    for index in range(1, total_slots + 1):
        team = actual_teams[index - 1] if index <= len(actual_teams) else {}

        raw_name = str(
            team.get("team_name")
            or team.get("name")
            or ""
        ).strip()

        if raw_name:
            base_name = raw_name
            duplicate_number = seen_names.get(base_name.lower(), 0) + 1
            seen_names[base_name.lower()] = duplicate_number
            name = (
                base_name
                if duplicate_number == 1
                else f"{base_name} ({duplicate_number})"
            )
        else:
            name = f"Open Team Slot {index}"

        rating = max(50, 92 - ((index - 1) * 3))
        playoffs = max(5, 85 - ((index - 1) * 6))

        ranking_rows.append(
            {
                "rank": index,
                "team": name,
                "rating": rating,
                "playoffs": playoffs,
            }
        )

    analytics["power_rankings"] = ranking_rows

    selected = user_team(actual_teams)
    if selected:
        selected_name = str(
            selected.get("team_name")
            or selected.get("name")
            or ""
        ).strip().lower()

        for row in ranking_rows:
            if str(row["team"]).strip().lower() == selected_name:
                analytics["team_rank"] = row["rank"]
                analytics["team_strength"] = row["rating"]
                analytics["playoff_probability"] = row["playoffs"]
                break

    analytics["championship_probability"] = max(
        1,
        min(
            50,
            round(
                analytics.get("playoff_probability", 50)
                / max(2, total_slots)
            ),
        ),
    )

    return analytics



def page(template, **ctx):
    snap = load_snapshot()
    connected = bool(snap)
    league = snap.get("league") if snap else None
    settings = snap.get("settings") if snap else None
    teams = snap.get("teams", []) if snap else []

    # This helper cannot take down the dashboard. It preserves the exact
    # original analytics structure expected by the existing template.
    try:
        expected_team_count = (
            (league or {}).get("teams")
            or (settings or {}).get("team_count")
            or len(teams)
        )
        analytics = dashboard_analytics_with_actual_teams(
            teams,
            expected_team_count,
        )
    except Exception:
        app.logger.exception(
            "Unable to replace demo power-ranking team names"
        )
        analytics = DEMO

    return render_template(
        template,
        user=USER,
        connected=connected,
        league=league,
        league_settings=settings,
        teams=teams,
        user_team=user_team(teams),
        analytics=analytics,
        **ctx,
    )

def draft_state(key):
    return session.get(f"draft_{key}", {"drafted":[],"roster":[],"draft_log":[]})

def save_draft_state(key, state):
    session[f"draft_{key}"] = state

def snake_pick(round_no, slot, teams):
    return slot if round_no % 2 else teams-slot+1

def next_picks(slot, teams, start_round, count=5):
    return [f"{r}.{snake_pick(r,slot,teams):02d}" for r in range(start_round,start_round+count)]

def position_counts(roster):
    lookup = {p["name"]:p["pos"] for p in PLAYERS}
    return Counter(lookup.get(x,"") for x in roster if lookup.get(x))

def need_score(pos, counts, context):
    target = context["starters"].get(pos,0) + (1 if pos in ("RB","WR") else 0)
    cur = counts.get(pos,0)
    return 25 if cur >= target else min(100,45+(target-cur)*25)

def scarcity(pos, drafted):
    avail = [p for p in PLAYERS if p["name"] not in drafted and p["pos"]==pos and p["tier"]<=3]
    n = len(avail)
    return ("High",90) if n<=4 else ("Medium",60) if n<=7 else ("Low",35)

def scoring_bonus(player, scoring):
    s = scoring.upper()
    if "FULL" in s: return {"WR":5,"TE":3,"RB":2}.get(player["pos"],0)
    if "HALF" in s: return {"WR":3,"TE":1.5,"RB":1}.get(player["pos"],0)
    return 4 if player["pos"]=="RB" else 0

def strategy_bonus(player, strategy, round_no):
    pos=player["pos"]
    if strategy=="zero-rb":
        return 7 if pos=="WR" and round_no<=5 else -6 if pos=="RB" and round_no<=4 else 0
    if strategy=="hero-rb":
        return 7 if pos=="RB" and round_no<=2 else 4 if pos=="WR" and 2<=round_no<=6 else 0
    if strategy=="robust-rb" and pos=="RB" and round_no<=4: return 6
    if strategy=="late-qb" and pos=="QB" and round_no<=5: return -8
    return 0

def player_score(player, context, state, round_no, pick_no, strategy):
    overall=(round_no-1)*context["teams"]+pick_no
    counts=position_counts(state["roster"])
    need=need_score(player["pos"],counts,context)
    scarcity_label, scarcity_num=scarcity(player["pos"],set(state["drafted"]))
    adp_val=round(player["adp"]-overall,1)
    score=90-max(0,player["rank"]-overall)*1.2+max(-10,min(12,adp_val))*.8+need*.1+scarcity_num*.06+scoring_bonus(player,context["scoring"])+strategy_bonus(player,strategy,round_no)
    fit="Excellent" if need>=80 else "Good" if need>=55 else "Depth"
    return {**player,"iq_score":round(max(45,min(99,score))),"adp_value":f"{adp_val:+.1f}","roster_fit":fit,"scarcity":scarcity_label}

def recommendation(context,state,round_no,pick_no,strategy):
    scored=[player_score(p,context,state,round_no,pick_no,strategy) for p in PLAYERS if p["name"] not in set(state["drafted"])]
    scored.sort(key=lambda x:(x["iq_score"],-x["rank"]),reverse=True)
    if not scored:
        return {"player":{"name":"No players","pos":"—","team":"—","tier":"—"},"score":0,"confidence":0,"adp_value":"0","roster_fit":"—","scarcity":"—","tier_risk":"—","survival_probability":0,"rationale":"No players remain.","next_best":[]}
    best=scored[0]
    same=[p for p in scored if p["pos"]==best["pos"] and p["tier"]==best["tier"]]
    tier_risk="High" if len(same)<=2 else "Medium" if len(same)<=4 else "Low"
    next_round=round_no+1
    next_overall=(next_round-1)*context["teams"]+snake_pick(next_round,context["draft_slot"],context["teams"])
    gap=max(0,next_overall-float(best["adp"]))
    survive=round(max(8,min(92,82*exp(-gap/18))))
    return {
        "player":best,"score":best["iq_score"],"confidence":min(96,max(60,best["iq_score"]-3)),
        "adp_value":best["adp_value"],"roster_fit":best["roster_fit"],"scarcity":best["scarcity"],
        "tier_risk":tier_risk,"survival_probability":survive,
        "rationale":f"{best['name']} is the best combination of league-adjusted value, {best['roster_fit'].lower()} roster fit, and {best['scarcity'].lower()} positional scarcity. Estimated chance to survive to your next pick: {survive}%.",
        "next_best":scored[1:4],
    }

def roster_slots(context,state):
    lookup={p["name"]:p for p in PLAYERS}
    by={}
    for name in state["roster"]:
        p=lookup.get(name)
        if p: by.setdefault(p["pos"],[]).append(name)
    rows=[]
    for label,pos in [("QB","QB"),("RB1","RB"),("RB2","RB"),("WR1","WR"),("WR2","WR"),("TE","TE"),("FLEX","FLEX")]:
        candidates=(by.get("RB",[])[2:]+by.get("WR",[])[2:]+by.get("TE",[])[1:]) if pos=="FLEX" else by.get(pos,[])
        idx=1 if label.endswith("2") else 0
        player=candidates[idx] if idx<len(candidates) else None
        rows.append({"slot":label,"player":player,"status":"Filled" if player else "Open"})
    return rows

def roster_needs(context,state):
    counts=position_counts(state["roster"])
    out=[]
    for pos in ("RB","WR","TE","QB"):
        score=need_score(pos,counts,context)
        out.append({"position":pos,"score":score,"label":"High" if score>=80 else "Medium" if score>=55 else "Low"})
    return out

def tier_alerts(state):
    drafted=set(state["drafted"]); out=[]
    for pos in ("RB","WR","TE","QB"):
        avail=[p for p in PLAYERS if p["name"] not in drafted and p["pos"]==pos]
        if not avail: continue
        tier=min(p["tier"] for p in avail)
        remaining=len([p for p in avail if p["tier"]==tier])
        level="High" if remaining<=2 else "Medium" if remaining<=4 else "Low"
        out.append({"position":pos,"tier":tier,"remaining":remaining,"level":level,"message":f"{remaining} player{'s' if remaining!=1 else ''} remain in the current {pos} tier."})
    return out

def draft_leagues():
    snap=load_snapshot()
    if snap:
        CONTEXTS["espn-gramps"].update({
            "league_name":snap["league"].get("league_name","Gramp's Gridiron"),
            "teams":int(snap["league"].get("teams",12) or 12),
            "scoring":snap["settings"].get("scoring_label") or snap["settings"].get("scoring") or "Full PPR",
        })
    return [{"key":"espn-gramps","name":CONTEXTS["espn-gramps"]["league_name"],"platform":"ESPN"},{"key":"yahoo-westrockers","name":"WestRockers","platform":"Yahoo"}]


# ============================================================
# MOCK DRAFT LAB
# ============================================================

import random

def mock_history():
    return session.get("mock_draft_history", [])

def save_mock_history(history):
    session["mock_draft_history"] = history[-100:]

def mock_pick_order(teams, rounds):
    order = []
    overall = 1
    for rnd in range(1, rounds + 1):
        slots = range(1, teams + 1) if rnd % 2 else range(teams, 0, -1)
        for slot in slots:
            order.append({"overall":overall,"round":rnd,"slot":slot})
            overall += 1
    return order

def mock_strategy_score(player, strategy, round_no, roster_counts):
    score = 100 - abs(player["adp"] - max(1, round_no * 12 - 5)) * 0.20
    pos = player["pos"]

    if strategy == "zero-rb":
        if pos == "WR" and round_no <= 5: score += 9
        if pos == "RB" and round_no <= 4: score -= 8
    elif strategy == "hero-rb":
        if pos == "RB" and round_no <= 2 and roster_counts.get("RB", 0) == 0: score += 12
        if pos == "WR" and 2 <= round_no <= 6: score += 5
    elif strategy == "robust-rb":
        if pos == "RB" and round_no <= 4: score += 8
    elif strategy == "late-qb":
        if pos == "QB" and round_no <= 6: score -= 12
    elif strategy == "balanced":
        if pos in ("RB","WR") and round_no <= 5: score += 4

    # Roster construction pressure.
    targets = {"QB":1,"RB":4,"WR":5,"TE":1}
    if roster_counts.get(pos, 0) < targets.get(pos, 99):
        score += 3

    # Mild premium on higher projected players.
    score += float(player.get("projection", 0)) / 100.0
    return score

def run_one_mock(context, draft_slot, strategy, rounds=12):
    teams = int(context.get("teams", 12) or 12)
    scoring = context.get("scoring", "Full PPR")
    order = mock_pick_order(teams, rounds)
    available = [dict(p) for p in MOCK_PLAYER_POOL]
    user_roster = []
    user_counts = Counter()
    all_picks = []

    for pick in order:
        if not available:
            break

        if pick["slot"] == draft_slot:
            candidates = []
            for player in available:
                s = mock_strategy_score(player, strategy, pick["round"], user_counts)
                # Scoring-format adjustment.
                s += scoring_bonus(player, scoring)
                candidates.append((s, player))
            candidates.sort(key=lambda x: x[0], reverse=True)
            chosen = candidates[0][1]
            user_roster.append(chosen)
            user_counts[chosen["pos"]] += 1
        else:
            # Simulate opponent picks around ADP with controlled randomness.
            overall = pick["overall"]
            candidates = sorted(
                available,
                key=lambda p: abs(float(p["adp"]) - overall) + random.random() * 7.0
            )
            chosen = candidates[0]

        available = [p for p in available if p["name"] != chosen["name"]]
        all_picks.append({
            "overall":pick["overall"],
            "round":pick["round"],
            "slot":pick["slot"],
            "player":chosen["name"],
            "pos":chosen["pos"],
            "team":chosen["team"],
            "user_pick":pick["slot"] == draft_slot,
        })

    # Grade roster balance + player quality.
    quality = sum(max(0, 110 - p["rank"]) for p in user_roster)
    balance = 0
    desired = {"QB":1,"RB":4,"WR":5,"TE":1}
    for pos, target in desired.items():
        balance += max(0, 20 - abs(user_counts.get(pos,0)-target)*5)

    grade_score = max(50, min(99, round(55 + quality / max(1,len(user_roster)) * .25 + balance * .18)))
    sequence = "-".join(p["pos"] for p in user_roster[:6])

    return {
        "strategy":strategy,
        "draft_slot":draft_slot,
        "rounds":rounds,
        "score":grade_score,
        "sequence":sequence,
        "roster":[{"round":i+1, **p} for i,p in enumerate(user_roster)],
        "counts":dict(user_counts),
        "picks":all_picks,
    }

def summarize_mock_batch(results):
    if not results:
        return {}

    seq_counts = Counter(r["sequence"] for r in results)
    avg_score = round(sum(r["score"] for r in results) / len(results), 1)
    best = max(results, key=lambda r:r["score"])

    round_players = {}
    for r in results:
        for p in r["roster"]:
            rnd = p["round"]
            round_players.setdefault(rnd, Counter())
            round_players[rnd][p["name"]] += 1

    common_by_round = []
    for rnd in sorted(round_players):
        name, count = round_players[rnd].most_common(1)[0]
        common_by_round.append({
            "round":rnd,
            "player":name,
            "frequency":round(count / len(results) * 100),
        })

    top_sequences = [
        {"sequence":seq,"count":count,"percent":round(count/len(results)*100)}
        for seq,count in seq_counts.most_common(5)
    ]

    return {
        "runs":len(results),
        "average_score":avg_score,
        "best_score":best["score"],
        "best_sequence":best["sequence"],
        "top_sequences":top_sequences,
        "common_by_round":common_by_round[:8],
    }


@app.get("/")
def home(): return redirect(url_for("dashboard"))

@app.get("/app")
@app.get("/dashboard")
def dashboard(): return page("dashboard.html")


@app.get("/mock-draft")
def mock_draft():
    key = request.args.get("league") or session.get("active_draft_league") or "espn-gramps"
    if key not in CONTEXTS:
        key = "espn-gramps"
    context = dict(CONTEXTS[key])
    history = mock_history()
    summary = summarize_mock_batch(history[-25:]) if history else {}
    return page(
        "mock_draft.html",
        draft_leagues=draft_leagues(),
        active_league_key=key,
        mock_context=context,
        mock_history=history[-20:][::-1],
        mock_summary=summary,
        manual_mocks=_manual_mock_list(20),
    )

@app.get("/draft-center")
def draft_center():
    key=request.args.get("league") or session.get("active_draft_league") or "espn-gramps"
    if key not in CONTEXTS: key="espn-gramps"
    session["active_draft_league"]=key
    context=dict(CONTEXTS[key]); state=draft_state(key); strategy="balanced"
    context["next_picks"]=next_picks(context["draft_slot"],context["teams"],context["round"])
    rec=recommendation(context,state,context["round"],context["pick_in_round"],strategy)
    players=[player_score(p,context,state,context["round"],context["pick_in_round"],strategy) for p in PLAYERS]
    drafted=set(state["drafted"])
    for p in players: p["drafted"]=p["name"] in drafted
    players.sort(key=lambda x:x["iq_score"],reverse=True)
    return page("draft_center.html",draft_leagues=draft_leagues(),active_league_key=key,draft_context=context,recommendation=rec,players=players,roster=state["roster"],roster_slots=roster_slots(context,state),roster_needs=roster_needs(context,state),tier_alerts=tier_alerts(state),draft_log=state["draft_log"])

@app.get("/league-sync")
@app.get("/connect-league")
def league_sync():
    return page("league_sync.html",yahoo_configured=bool(os.getenv("YAHOO_CLIENT_ID") and os.getenv("YAHOO_CLIENT_SECRET")),yahoo_redirect=os.getenv("YAHOO_REDIRECT_URI",""))


def connected_league_data():
    snap = load_snapshot() or {}
    return {
        "league": snap.get("league") or {},
        "settings": snap.get("settings") or {},
        "teams": snap.get("teams") or [],
        "user_team": user_team(snap.get("teams") or []),
    }

def league_standings(teams):
    return sorted(
        teams,
        key=lambda t: (
            int(t.get("wins", 0)),
            float(t.get("points_for", 0)),
        ),
        reverse=True,
    )

def league_summary():
    data = connected_league_data()
    teams = data["teams"]
    standings = league_standings(teams)
    rostered = sum(int(t.get("roster_size", 0) or 0) for t in teams)
    return {
        **data,
        "standings": standings,
        "team_count": len(teams),
        "rostered_players": rostered,
        "pre_draft": rostered == 0,
    }

@app.get("/api/league/summary")
def league_summary_api():
    summary = league_summary()
    return jsonify(ok=bool(summary["league"]), **summary)

@app.get("/api/league/teams")
def league_teams_api():
    data = connected_league_data()
    return jsonify(ok=bool(data["league"]), league=data["league"], teams=data["teams"])


@app.get("/api/league/power-ranking-teams")
def league_power_ranking_teams_api():
    data = connected_league_data()
    league = data["league"] or {}
    settings = data["settings"] or {}
    actual_teams = [
        team
        for team in data["teams"]
        if isinstance(team, dict)
    ]

    try:
        configured_count = int(
            league.get("teams")
            or settings.get("team_count")
            or len(actual_teams)
        )
    except (TypeError, ValueError):
        configured_count = len(actual_teams)

    analytics = dashboard_analytics_with_actual_teams(
        actual_teams,
        configured_count,
    )

    return jsonify(
        ok=bool(league),
        configured_team_count=configured_count,
        synced_team_count=len(actual_teams),
        ranking_row_count=len(analytics.get("power_rankings", [])),
        teams=analytics.get("power_rankings", []),
    )

def league_power_ranking_teams_api():
    data = connected_league_data()
    teams = [
        {
            "rank": index,
            "team": str(
                team.get("team_name")
                or team.get("name")
                or f"Team {index}"
            ).strip(),
        }
        for index, team in enumerate(data["teams"], start=1)
        if isinstance(team, dict)
    ]
    return jsonify(
        ok=bool(data["league"]),
        team_count=len(teams),
        teams=teams,
    )

@app.get("/lineup-optimizer")
def lineup_optimizer(): return page("lineup.html")

@app.get("/waiver-assistant")
def waiver_assistant(): return page("waivers.html")

@app.get("/trade-analyzer")
def trade_analyzer(): return page("trade.html", league_data=league_summary())

@app.get("/matchup-analyzer")
def matchup_analyzer(): return redirect("/weekly-matchups")

@app.get("/league-intelligence")
def league_intelligence(): return page("league_intelligence.html", league_data=league_summary())

def _daily_ai_priorities():
    summary = league_summary()
    league = summary["league"]
    teams = summary["teams"]
    my_team = summary["user_team"]

    priorities = []
    if not league:
        priorities.append({
            "type": "connection",
            "priority": "High",
            "title": "Connect your league",
            "detail": "Connect ESPN or Yahoo so Gridiron IQ can load teams and league settings.",
            "action": "/league-sync",
        })
    elif summary["pre_draft"]:
        priorities.extend([
            {
                "type": "league",
                "priority": "High",
                "title": f"{summary['team_count']} ESPN teams loaded",
                "detail": "Your league is connected. Rosters are empty because the league has not drafted yet.",
                "action": "/league-intelligence",
            },
            {
                "type": "draft",
                "priority": "High",
                "title": "Prepare for the draft",
                "detail": "Use Draft Center and Mock Draft Lab while your ESPN rosters are still empty.",
                "action": "/draft-center",
            },
            {
                "type": "research",
                "priority": "Medium",
                "title": "Research draft targets",
                "detail": "Compare 2025 stats, 2026 projections and platform ADP before draft night.",
                "action": "/player-research",
            },
        ])
    else:
        priorities.extend([
            {
                "type": "roster",
                "priority": "High",
                "title": "Review your roster",
                "detail": f"{my_team.get('team_name') if my_team else 'Your team'} has {my_team.get('roster_size',0) if my_team else 0} players synced.",
                "action": "/lineup-optimizer",
            },
            {
                "type": "trade",
                "priority": "Medium",
                "title": "Scan trade opportunities",
                "detail": "Compare your roster against every team in the league.",
                "action": "/trade-analyzer",
            },
            {
                "type": "league",
                "priority": "Medium",
                "title": "Check league intelligence",
                "detail": "Review standings, team rosters and league-wide strengths.",
                "action": "/league-intelligence",
            },
        ])

    return {
        "league": league,
        "settings": summary["settings"],
        "teams": teams,
        "team": my_team,
        "team_count": summary["team_count"],
        "rostered_players": summary["rostered_players"],
        "pre_draft": summary["pre_draft"],
        "priorities": priorities,
        "stats_2025": _stats_2025_snapshot(),
        "fantasypros": _fp_api_status() if "_fp_api_status" in globals() else {"configured": False},
    }

@app.get("/reports")
def reports():
    return page("reports.html", coach=_daily_ai_priorities())

@app.get("/api/ai-coach/daily")
def daily_ai_coach_api():
    return jsonify(ok=True, coach=_daily_ai_priorities())


@app.get("/settings")
def settings(): return page("settings.html")

@app.get("/help")
def help_page(): return page("help.html")

@app.get("/health")
@app.get("/api/health")
def health():
    return jsonify(ok=True,service="Gridiron IQ",espn_snapshot=bool(load_snapshot()),time=datetime.now(timezone.utc).isoformat())

@app.post("/api/espn/test")
def espn_test():
    data=request.get_json(silent=True) or {}
    if any(not str(data.get(k,"")).strip() for k in ("league_id","season","swid","espn_s2")):
        return jsonify(ok=False,error="Complete League ID, season, SWID, and espn_s2."),400
    try:
        from espn_api.football import League
        league=League(league_id=int(data["league_id"]),year=int(data["season"]),swid=str(data["swid"]).strip(),espn_s2=str(data["espn_s2"]).strip())
        return jsonify(ok=True,message="ESPN connection successful.",league_name=getattr(league.settings,"name","ESPN League"),team_count=len(league.teams),current_week=getattr(league,"current_week",None),scoring=short_scoring(league.settings))
    except Exception as exc:
        return jsonify(ok=False,error="ESPN rejected the connection.",detail=str(exc)),400

@app.post("/api/espn/sync")
def espn_sync():
    data=request.get_json(silent=True) or {}
    if any(not str(data.get(k,"")).strip() for k in ("league_id","season","swid","espn_s2")):
        return jsonify(ok=False,error="Complete all ESPN connection fields."),400
    try:
        from espn_api.football import League
        espn=League(league_id=int(data["league_id"]),year=int(data["season"]),swid=str(data["swid"]).strip(),espn_s2=str(data["espn_s2"]).strip())
        teams=[team_dict(t) for t in espn.teams]
        scoring=short_scoring(espn.settings)
        settings={"name":getattr(espn.settings,"name","ESPN League"),"team_count":len(teams),"reg_season_count":getattr(espn.settings,"reg_season_count",14) or 14,"playoff_team_count":getattr(espn.settings,"playoff_team_count",6) or 6,"scoring":scoring,"scoring_label":scoring}
        league={"platform":"ESPN","league_id":str(data["league_id"]),"league_name":settings["name"],"season":int(data["season"]),"teams":len(teams),"current_week":getattr(espn,"current_week",None),"synced_at":datetime.now(timezone.utc).isoformat()}
        save_snapshot({"league":league,"settings":settings,"teams":teams})

        adp_info = {
            "ok": False,
            "player_count": 0,
            "source": "ESPN native fantasy ADP",
        }
        try:
            native_adp = _fetch_espn_native_adp(
                league_id=data["league_id"],
                season=data["season"],
                swid=data["swid"],
                espn_s2=data["espn_s2"],
            )
            # Save the authenticated ESPN result in the exact cache consumed
            # by Player Research. Credentials are never stored.
            if native_adp.get("players"):
                platform_path = _local_platform_adp_path("ESPN")
                temp_path = platform_path.with_suffix(platform_path.suffix + ".tmp")
                temp_path.write_text(
                    json.dumps(native_adp, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temp_path.replace(platform_path)

            adp_info = {
                "ok": bool(native_adp.get("players")),
                "player_count": len(native_adp.get("players", {})),
                "source": native_adp.get("source"),
                "updated_at": native_adp.get("updated_at"),
            }

            # Immediately copy the authenticated ESPN teams and ADP into the
            # SQLite Player Research database.
            try:
                from player_research_db import (
                    import_adp_payload as import_sqlite_adp_payload,
                    import_current_players as import_sqlite_current_players,
                )

                sqlite_adp = import_sqlite_adp_payload(
                    "ESPN",
                    native_adp,
                    source_name=native_adp.get("source")
                    or "Authenticated ESPN League Sync",
                    replace_existing=False,
                    minimum_rows=1,
                )
                public_adp = None
                try:
                    from player_research_db import import_public_adp
                    public_adp = import_public_adp("ESPN")
                except Exception as public_exc:
                    app.logger.warning(
                        "Public full ESPN ADP import unavailable: %s",
                        public_exc,
                    )

                sqlite_players = import_sqlite_current_players()

                adp_info["sqlite_imported"] = bool(sqlite_adp.get("ok"))
                adp_info["public_adp_imported"] = bool(
                    public_adp and public_adp.get("ok")
                )
                adp_info["public_adp_count"] = (
                    public_adp.get("count", 0) if public_adp else 0
                )
                adp_info["sqlite_adp_count"] = sqlite_adp.get("count", 0)
                adp_info["sqlite_received_count"] = sqlite_adp.get(
                    "received_count", 0
                )
                adp_info["sqlite_usable_count"] = sqlite_adp.get(
                    "usable_count", 0
                )
                adp_info["sqlite_player_count"] = sqlite_players

                app.logger.info(
                    "ESPN ADP direct SQLite import received=%s usable=%s inserted=%s",
                    sqlite_adp.get("received_count", 0),
                    sqlite_adp.get("usable_count", 0),
                    sqlite_adp.get("count", 0),
                )
            except Exception as sqlite_exc:
                app.logger.exception(
                    "ESPN synced but SQLite Player Research update failed"
                )
                adp_info["sqlite_error"] = str(sqlite_exc)
        except Exception as adp_exc:
            adp_info["error"] = str(adp_exc)

        return jsonify(
            ok=True,
            message="ESPN league synced.",
            league=league,
            settings=settings,
            user_team=user_team(teams),
            teams=teams,
            espn_adp=adp_info,
        )
    except Exception as exc:
        return jsonify(ok=False,error="ESPN sync failed.",detail=str(exc)),400

@app.post("/api/sleeper/sync")
def sleeper_sync():
    data=request.get_json(silent=True) or {}; league_id=str(data.get("league_id","")).strip()
    if not league_id: return jsonify(ok=False,error="Enter a Sleeper league ID."),400
    try:
        r=requests.get(f"https://api.sleeper.app/v1/league/{league_id}",timeout=20); r.raise_for_status()
        return jsonify(ok=True,message="Sleeper league found.",league=r.json())
    except Exception as exc:
        return jsonify(ok=False,error="Sleeper sync failed.",detail=str(exc)),400

@app.get("/auth/yahoo/start")
def yahoo_start():
    cid=os.getenv("YAHOO_CLIENT_ID","").strip(); uri=os.getenv("YAHOO_REDIRECT_URI","").strip()
    if not cid or not uri: return page("error.html",code=400,message="Yahoo is not configured in Render."),400
    state=os.urandom(18).hex(); session["yahoo_state"]=state
    return redirect("https://api.login.yahoo.com/oauth2/request_auth?"+urlencode({"client_id":cid,"redirect_uri":uri,"response_type":"code","language":"en-us","state":state}))

@app.get("/auth/yahoo/callback")
def yahoo_callback():
    if request.args.get("state") != session.get("yahoo_state"): return page("error.html",code=400,message="Yahoo authorization state did not match."),400
    code=request.args.get("code","")
    if not code: return page("error.html",code=400,message="Yahoo did not return an authorization code."),400
    try:
        r=requests.post("https://api.login.yahoo.com/oauth2/get_token",auth=(os.getenv("YAHOO_CLIENT_ID",""),os.getenv("YAHOO_CLIENT_SECRET","")),data={"grant_type":"authorization_code","redirect_uri":os.getenv("YAHOO_REDIRECT_URI",""),"code":code},timeout=25); r.raise_for_status()
        tok=r.json(); session["yahoo_access_token"]=tok.get("access_token"); session["yahoo_refresh_token"]=tok.get("refresh_token")
        return redirect(url_for("league_sync",yahoo="connected"))
    except Exception as exc:
        return page("error.html",code=502,message=f"Yahoo authorization failed: {exc}"),502



# ============================================================
# MANUAL MOCK DRAFT LAB
# ============================================================

MANUAL_MOCK_FILE = DATA_DIR / "manual_mock_drafts.json"
MOCK_PLAYER_CACHE_FILE = DATA_DIR / "sleeper_players_cache.json"
MOCK_PLAYER_CACHE_TTL = 24 * 60 * 60
_MANUAL_MOCK_MEMORY = None
_MOCK_CURRENT_PLAYERS_MEMORY = {}
_MOCK_CURRENT_PLAYERS_MTIME = 0.0

def _manual_mock_public(mock):
    """Return only the mock fields the browser needs, excluding the large pool."""
    return {key: value for key, value in mock.items() if key != "player_pool"}

def _mock_current_player_directory():
    """Load current teams once per day and reuse the saved Sleeper directory."""
    cached = {}
    try:
        if MOCK_PLAYER_CACHE_FILE.exists():
            cached = json.loads(MOCK_PLAYER_CACHE_FILE.read_text(encoding="utf-8"))
            if not isinstance(cached, dict):
                cached = {}
            age = time.time() - MOCK_PLAYER_CACHE_FILE.stat().st_mtime
            if cached and age < MOCK_PLAYER_CACHE_TTL:
                return cached
    except Exception:
        cached = {}

    try:
        response = requests.get(
            "https://api.sleeper.app/v1/players/nfl?active=true",
            headers={"User-Agent": "Gridiron-IQ/2026"},
            timeout=(3, 10),
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload:
            try:
                MOCK_PLAYER_CACHE_FILE.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass
            return payload
    except Exception as exc:
        app.logger.warning("Mock Draft current-team refresh failed: %s", exc)

    return cached

def _mock_current_players_by_name(refresh=False, allow_network=True):
    global _MOCK_CURRENT_PLAYERS_MEMORY, _MOCK_CURRENT_PLAYERS_MTIME
    try:
        cache_mtime = MOCK_PLAYER_CACHE_FILE.stat().st_mtime
        cache_age = time.time() - cache_mtime
    except Exception:
        cache_mtime = 0.0
        cache_age = MOCK_PLAYER_CACHE_TTL + 1

    if (
        _MOCK_CURRENT_PLAYERS_MEMORY
        and _MOCK_CURRENT_PLAYERS_MTIME == cache_mtime
        and (not refresh or cache_age < MOCK_PLAYER_CACHE_TTL)
    ):
        return _MOCK_CURRENT_PLAYERS_MEMORY

    if not refresh and MOCK_PLAYER_CACHE_FILE.exists():
        try:
            directory = json.loads(MOCK_PLAYER_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            directory = {}
    elif allow_network:
        directory = _mock_current_player_directory()
    else:
        directory = {}

    by_name = {}
    for player_id, row in (directory or {}).items():
        if not isinstance(row, dict):
            continue
        name = str(
            row.get("full_name")
            or " ".join(x for x in (row.get("first_name"), row.get("last_name")) if x)
            or ""
        ).strip()
        if name:
            by_name[_pr_norm(name)] = {"player_id": str(player_id), **row}
    _MOCK_CURRENT_PLAYERS_MEMORY = by_name
    try:
        _MOCK_CURRENT_PLAYERS_MTIME = MOCK_PLAYER_CACHE_FILE.stat().st_mtime
    except Exception:
        _MOCK_CURRENT_PLAYERS_MTIME = cache_mtime
    return _MOCK_CURRENT_PLAYERS_MEMORY

def _manual_mock_store():
    global _MANUAL_MOCK_MEMORY
    if isinstance(_MANUAL_MOCK_MEMORY, dict):
        return _MANUAL_MOCK_MEMORY
    try:
        if MANUAL_MOCK_FILE.exists():
            data = json.loads(MANUAL_MOCK_FILE.read_text(encoding="utf-8"))
            _MANUAL_MOCK_MEMORY = data if isinstance(data, dict) else {}
            return _MANUAL_MOCK_MEMORY
    except Exception:
        pass
    _MANUAL_MOCK_MEMORY = {}
    return _MANUAL_MOCK_MEMORY

def _save_manual_mock_store(store):
    global _MANUAL_MOCK_MEMORY
    # Keep the most recent mocks so this file cannot grow forever.
    ordered = sorted(
        store.values(),
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )[:10]
    _MANUAL_MOCK_MEMORY = {str(item["id"]): item for item in ordered}
    MANUAL_MOCK_FILE.write_text(
        json.dumps(_MANUAL_MOCK_MEMORY, separators=(",", ":")),
        encoding="utf-8",
    )

def _manual_mock_get(mock_id):
    return _manual_mock_store().get(str(mock_id))

def _manual_mock_save(mock):
    store = _manual_mock_store()
    store[str(mock["id"])] = mock
    _save_manual_mock_store(store)

def _manual_mock_list(limit=30):
    rows = list(_manual_mock_store().values())
    rows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return rows[:limit]

def _mock_projection_from_stats(stats, pos):
    ppr = float(stats.get("fantasy_points_ppr") or stats.get("fantasy_points") or 0)
    if ppr > 0:
        # modest growth/mean-reversion heuristic for simulator depth players
        return round(ppr * 1.03, 1)
    defaults = {"QB": 240, "RB": 150, "WR": 145, "TE": 110, "K": 120, "DEF": 120}
    return defaults.get(pos, 100)

def _build_dynamic_mock_pool(context):
    """
    Build the mock pool from the current 2026 master player database whenever
    available. This prevents stale hard-coded teams and includes rookies.
    """
    master = _master_players_2026()
    master_players = master.get("players", {})
    # Current Sleeper teams override any older team saved in the master file.
    current_players = _mock_current_players_by_name(refresh=True)

    if master_players:
        players = []
        for norm, p in master_players.items():
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            current = current_players.get(_pr_norm(name), {})
            current_team = (
                _normalize_team_code(current.get("team")) or "FA"
                if current
                else (_normalize_team_code(p.get("team")) or "FA")
            )
            pos = str(current.get("position") or p.get("position") or "").upper()
            if pos == "DST":
                pos = "DEF"
            if pos not in {"QB","RB","WR","TE","K","DEF"}:
                continue

            projection_data = p.get("projection") or {}
            projection = (
                projection_data.get("ppr_points")
                or projection_data.get("fantasy_points")
                or 0
            )
            try:
                projection = float(projection or 0)
            except Exception:
                projection = 0.0

            adp = p.get("adp")
            try:
                adp = float(adp)
            except Exception:
                adp = 999.0

            stats = p.get("stats_2025") or {}
            if not projection:
                projection = _mock_projection_from_stats(stats, pos)

            players.append({
                "rank": 999,
                "name": name,
                "pos": pos,
                "team": current_team,
                "tier": 9,
                "adp": adp,
                "projection": round(projection, 1),
                "rookie": bool(p.get("rookie")),
                "fantasypros_id": p.get("fantasypros_id"),
                "sleeper_id": p.get("sleeper_id"),
            })

        def master_sort(p):
            adp = p.get("adp", 999)
            return (
                adp if adp < 999 else 9999,
                -float(p.get("projection", 0) or 0),
                p.get("name") or "",
            )

        players.sort(key=master_sort)
        for idx, p in enumerate(players, 1):
            p["rank"] = idx
            if p.get("adp", 999) >= 999:
                p["adp"] = round(max(1, idx + 8), 1)

        return players[:300]

    # Fallback to the prior local pool until the first master refresh is run.
    platform = "YAHOO" if "YAHOO" in str(context.get("platform","")).upper() else "ESPN"
    # Starting a mock draft must never wait on an external ADP refresh. Use
    # whatever has already been saved locally; the ADP refresh tools can update
    # these files separately in the background/admin workflow.
    adp_data = _mock_local_adp_data(platform)
    adp_map = adp_data.get("players", {})
    stats_map = _stats_2025_snapshot().get("players", {})
    directory = _pr_players()

    pool = {}
    for p in MOCK_PLAYER_POOL:
        item = dict(p)
        norm = _pr_norm(item["name"])
        adp_row = adp_map.get(norm, {})
        try:
            item["adp"] = float(adp_row.get("adp", item.get("adp", 999)))
        except Exception:
            item["adp"] = float(item.get("adp", 999))
        stats = stats_map.get(norm, {})
        if not item.get("projection"):
            item["projection"] = _mock_projection_from_stats(stats, item.get("pos"))
        pool[norm] = item

    for pid, p in directory.items():
        name = p.get("full_name") or " ".join(x for x in [p.get("first_name"),p.get("last_name")] if x)
        pos = str(p.get("position") or ((p.get("fantasy_positions") or [""])[0]) or "").upper()
        if pos == "DST":
            pos = "DEF"
        if not name or pos not in {"QB","RB","WR","TE","K","DEF"}:
            continue
        norm = _pr_norm(name)
        if norm in pool:
            continue
        adp_row = adp_map.get(norm, {})
        try:
            adp = float(adp_row.get("adp", 999))
        except Exception:
            adp = 999.0
        stats = stats_map.get(norm, {})
        pool[norm] = {
            "rank": 999,
            "name": name,
            "pos": pos,
            "team": p.get("team") or stats.get("team") or "FA",
            "tier": 9,
            "adp": adp,
            "projection": _mock_projection_from_stats(stats, pos),
            "rookie": bool(p.get("rookie")),
        }

    players = list(pool.values())
    players.sort(key=lambda p: (
        float(p.get("adp",999)),
        -float(p.get("projection",0) or 0),
        p.get("name","")
    ))
    for idx, p in enumerate(players, 1):
        p["rank"] = idx
        if p.get("adp", 999) >= 999:
            p["adp"] = round(max(1, idx + 8), 1)
    return players[:300]

def _manual_player_lookup(mock=None):
    pool = (mock or {}).get("player_pool") if mock else None
    pool = pool or MOCK_PLAYER_POOL
    return {p["name"]: p for p in pool}

def _manual_available(mock):
    drafted = {p["player"] for p in mock.get("picks", [])}
    pool = mock.get("player_pool") or MOCK_PLAYER_POOL
    return [dict(p) for p in pool if p["name"] not in drafted]

def _manual_refresh_pool_teams(mock):
    """Correct teams in new and previously saved mocks from the local daily cache."""
    current = _mock_current_players_by_name(refresh=False)
    if not current:
        return mock

    for player in mock.get("player_pool", []):
        row = current.get(_pr_norm(player.get("name")), {})
        if row:
            player["team"] = _normalize_team_code(row.get("team")) or "FA"

    for pick in mock.get("picks", []):
        row = current.get(_pr_norm(pick.get("player")), {})
        if row:
            pick["team"] = _normalize_team_code(row.get("team")) or "FA"
    return mock

def _manual_order(mock):
    return mock_pick_order(int(mock["teams"]), int(mock["rounds"]))

def _manual_current_order_row(mock):
    order = _manual_order(mock)
    idx = len(mock.get("picks", []))
    return order[idx] if idx < len(order) else None

def _manual_user_roster(mock):
    lookup = _manual_player_lookup(mock)
    roster = []
    for pick in mock.get("picks", []):
        if pick.get("user_pick"):
            player = lookup.get(pick.get("player"))
            if player:
                roster.append({"round": pick["round"], "overall": pick["overall"], **player})
    return roster

def _manual_opponent_pick(mock, order_row):
    available = _manual_available(mock)
    if not available:
        return None

    overall = order_row["overall"]
    # Opponents draft mostly around ADP, with enough randomness to make mocks different.
    candidates = sorted(
        available,
        key=lambda p: abs(float(p.get("adp", 999)) - overall) + random.random() * 9.0
    )
    chosen = candidates[0]
    return {
        "overall": overall,
        "round": order_row["round"],
        "slot": order_row["slot"],
        "player": chosen["name"],
        "pos": chosen["pos"],
        "team": chosen["team"],
        "adp": chosen["adp"],
        "projection": chosen["projection"],
        "user_pick": False,
        "manager": f"Team {order_row['slot']}",
    }

def _manual_autopick_until_user(mock):
    while True:
        row = _manual_current_order_row(mock)
        if row is None:
            mock["status"] = "complete"
            break
        if int(row["slot"]) == int(mock["draft_slot"]):
            mock["status"] = "your_pick"
            break

        pick = _manual_opponent_pick(mock, row)
        if not pick:
            mock["status"] = "complete"
            break
        mock.setdefault("picks", []).append(pick)

    mock["updated_at"] = datetime.now(timezone.utc).isoformat()
    return mock

def _manual_need_bonus(pos, roster_counts, round_no):
    targets = {"QB": 1, "RB": 4, "WR": 5, "TE": 1}
    current = roster_counts.get(pos, 0)
    target = targets.get(pos, 99)

    if current < target:
        bonus = 6
    else:
        bonus = -3

    if pos == "QB" and round_no <= 4:
        bonus -= 5
    if pos == "TE" and round_no <= 2:
        bonus -= 2

    return bonus

def _manual_player_pick_score(mock, player, counts=None, overall=None, round_no=None):
    if counts is None:
        counts = Counter(p["pos"] for p in _manual_user_roster(mock))
    if overall is None or round_no is None:
        row = _manual_current_order_row(mock)
        overall = row["overall"] if row else len(mock.get("picks", [])) + 1
        round_no = row["round"] if row else int(mock["rounds"])

    adp_value = float(player.get("adp", overall)) - overall
    projection = float(player.get("projection", 0) or 0)

    score = 70
    score += min(12, max(-12, adp_value)) * 1.1
    score += projection / 75.0
    score += _manual_need_bonus(player["pos"], counts, round_no)

    return round(max(35, min(99, score)))

def _manual_2025_points_map(names):
    # Fast snapshot lookup; never reparse the full CSV during a draft.
    players = _stats_2025_snapshot().get("players", {})
    result = {}
    for name in names:
        stats = players.get(_pr_norm(name), {}) or {}
        result[name] = round(
            float(stats.get("fantasy_points_ppr") or stats.get("fantasy_points") or 0),
            1,
        )
    return result


def _manual_pick_report(mock):
    roster = _manual_user_roster(mock)
    reports = []
    context = dict(CONTEXTS.get(mock.get("league_key"), CONTEXTS["espn-gramps"]))

    for p in roster:
        enriched = _draft_player_enrichment(p, context, int(p.get("overall", 1)))
        grade = round(max(
            35,
            min(
                99,
                65
                + max(-12, min(12, enriched["value_vs_adp"])) * 1.1
                + min(10, enriched["projection_2026"] / 30)
                + min(8, enriched["points_2025"] / 35),
            ),
        ))
        reports.append({
            "round": p.get("round"),
            "overall": p.get("overall"),
            "name": p.get("name"),
            "pos": p.get("pos"),
            "adp": enriched["platform_adp"],
            "projection_2026": enriched["projection_2026"],
            "points_2025": enriched["points_2025"],
            "value_vs_adp": enriched["value_vs_adp"],
            "pick_grade": grade,
        })
    return reports

def _manual_grade(mock):
    roster = _manual_user_roster(mock)
    if not roster:
        return {
            "overall": 0,
            "projection_score": 0,
            "stats_score": 0,
            "value_score": 0,
            "balance_score": 0,
            "depth_score": 0,
            "projected_points": 0,
            "previous_year_points": 0,
            "summary": "No user picks yet.",
        }

    counts = Counter(p["pos"] for p in roster)
    projected_points = round(sum(float(p.get("projection", 0) or 0) for p in roster), 1)
    previous_map = _manual_2025_points_map([p["name"] for p in roster])
    previous_points = round(sum(previous_map.values()), 1)

    # Projection score: normalize around a strong 12-round fantasy roster.
    projection_score = round(max(45, min(99, 55 + projected_points / max(1, len(roster)) / 6.0)))

    # Historical production rewards proven production, but does not punish rookies/new players too harshly.
    if previous_points > 0:
        stats_score = round(max(45, min(99, 55 + previous_points / max(1, len(roster)) / 5.5)))
    else:
        stats_score = 70

    # Value score based on where the user selected players relative to ADP.
    values = []
    for p in roster:
        values.append(float(p.get("adp", p["overall"])) - float(p["overall"]))
    avg_value = sum(values) / max(1, len(values))
    value_score = round(max(40, min(99, 72 + avg_value * 1.8)))

    # Balance score.
    desired_min = {"QB": 1, "RB": 3, "WR": 4, "TE": 1}
    penalties = 0
    for pos, minimum in desired_min.items():
        if counts.get(pos, 0) < minimum:
            penalties += (minimum - counts.get(pos, 0)) * 7
    if counts.get("QB", 0) > 2:
        penalties += (counts["QB"] - 2) * 5
    if counts.get("TE", 0) > 2:
        penalties += (counts["TE"] - 2) * 5
    balance_score = max(40, 96 - penalties)

    # Depth score rewards useful RB/WR depth.
    rbwr = counts.get("RB", 0) + counts.get("WR", 0)
    depth_score = max(45, min(99, 55 + rbwr * 5))

    overall = round(
        projection_score * 0.30
        + stats_score * 0.20
        + value_score * 0.20
        + balance_score * 0.20
        + depth_score * 0.10
    )

    strengths = []
    concerns = []
    if value_score >= 80:
        strengths.append("strong value versus ADP")
    if projection_score >= 80:
        strengths.append("high projected production")
    if balance_score >= 85:
        strengths.append("balanced roster construction")
    if counts.get("RB", 0) < 3:
        concerns.append("running-back depth")
    if counts.get("WR", 0) < 4:
        concerns.append("wide-receiver depth")
    if counts.get("QB", 0) == 0:
        concerns.append("quarterback still open")
    if counts.get("TE", 0) == 0:
        concerns.append("tight end still open")

    summary = f"Overall draft grade: {overall}/100."
    if strengths:
        summary += " Strengths: " + ", ".join(strengths) + "."
    if concerns:
        summary += " Watch: " + ", ".join(concerns) + "."

    return {
        "overall": overall,
        "projection_score": projection_score,
        "stats_score": stats_score,
        "value_score": value_score,
        "balance_score": balance_score,
        "depth_score": depth_score,
        "projected_points": projected_points,
        "previous_year_points": previous_points,
        "summary": summary,
    }

def _manual_finalize_if_complete(mock):
    row = _manual_current_order_row(mock)
    if row is None:
        mock["status"] = "complete"
        mock["grade"] = _manual_grade(mock)
        mock["completed_at"] = datetime.now(timezone.utc).isoformat()
    else:
        mock["grade"] = _manual_grade(mock)
    mock["updated_at"] = datetime.now(timezone.utc).isoformat()
    return mock


# ============================================================
# ADVANCED AI MOCK DRAFT ENGINE
# FantasyPros-style fast simulator for ESPN/Yahoo league profiles
# ============================================================

def _mock_local_adp_data(platform):
    """Return saved ADP without making a network request."""
    platform = "YAHOO" if str(platform or "").upper() == "YAHOO" else "ESPN"
    try:
        path = _local_platform_adp_path(platform)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("players"):
                return payload
    except Exception as exc:
        app.logger.warning("Saved %s mock-draft ADP could not be read: %s", platform, exc)

    if platform == "ESPN":
        try:
            payload = _load_espn_native_adp()
            if isinstance(payload, dict) and payload.get("players"):
                return payload
        except Exception:
            pass

    return {"platform": platform, "source": "built-in mock pool", "players": {}}

def _mock_platform_adp(context):
    platform = "YAHOO" if "YAHOO" in str(context.get("platform", "")).upper() else "ESPN"
    data = _mock_local_adp_data(platform)
    return platform, data

def _mock_roster_template(context):
    # Use connected league settings if available, otherwise sensible defaults.
    scoring = str(context.get("scoring") or "")
    return {
        "QB": 1,
        "RB": 2,
        "WR": 2 if "Half" in scoring else 3,
        "TE": 1,
        "FLEX": 1,
        "K": 1,
        "DEF": 1,
        "BENCH": 6,
    }

def _mock_team_counts(team_roster):
    return Counter(p.get("pos") for p in team_roster)

def _mock_position_need_score(pos, roster, round_no, total_rounds):
    counts = _mock_team_counts(roster)

    # Starter requirements / practical depth.
    targets = {
        "QB": 1,
        "RB": 4,
        "WR": 5,
        "TE": 1,
        "K": 1,
        "DEF": 1,
    }

    current = counts.get(pos, 0)
    target = targets.get(pos, 99)

    if current == 0 and pos in {"QB","RB","WR","TE"}:
        score = 10
    elif current < target:
        score = 5
    else:
        score = -5

    # Avoid unrealistic early K/DST and excessive QB/TE hoarding.
    if pos in {"K","DEF"} and round_no < max(8, total_rounds - 4):
        score -= 18
    if pos == "QB" and counts.get("QB", 0) >= 1 and round_no <= 8:
        score -= 9
    if pos == "TE" and counts.get("TE", 0) >= 1 and round_no <= 8:
        score -= 7

    return score

def _mock_strategy_archetype(team_slot):
    # Deterministic mix of opponent personalities.
    styles = [
        "balanced",
        "rb-heavy",
        "wr-heavy",
        "late-qb",
        "early-qb",
        "balanced",
        "hero-rb",
        "best-player",
        "balanced",
        "zero-rb",
        "balanced",
        "best-player",
    ]
    return styles[(int(team_slot)-1) % len(styles)]

def _mock_strategy_bonus_for_ai(player, style, round_no):
    pos = player["pos"]
    if style == "rb-heavy" and pos == "RB" and round_no <= 5:
        return 8
    if style == "wr-heavy" and pos == "WR" and round_no <= 6:
        return 8
    if style == "late-qb" and pos == "QB" and round_no <= 7:
        return -12
    if style == "early-qb" and pos == "QB" and round_no <= 4:
        return 8
    if style == "hero-rb":
        if pos == "RB" and round_no <= 2:
            return 10
        if pos == "WR" and 2 <= round_no <= 6:
            return 5
    if style == "zero-rb":
        if pos == "WR" and round_no <= 5:
            return 9
        if pos == "RB" and round_no <= 4:
            return -8
    return 0

def _mock_ai_score(
    player, context, team_roster, overall_pick, round_no, total_rounds, style,
    adp_players=None, stats_players=None,
):
    # adp_players/stats_players are supplied by _mock_ai_pick so hundreds of
    # candidates do not repeatedly read the same files from disk.
    if adp_players is None:
        _, adp_data = _mock_platform_adp(context)
        adp_players = adp_data.get("players", {})
    if stats_players is None:
        stats_players = _stats_2025_snapshot().get("players", {})

    normalized_name = _pr_norm(player["name"])
    adp_row = adp_players.get(normalized_name, {})
    platform_adp = adp_row.get("adp")
    try:
        platform_adp = float(platform_adp)
    except Exception:
        platform_adp = float(player.get("adp", 999))

    projection = float(player.get("projection", 0) or 0)
    prior = stats_players.get(normalized_name, {}) or {}
    prior_points = float(prior.get("fantasy_points_ppr") or prior.get("fantasy_points") or 0)

    # Base: market ADP + talent/projection + previous production.
    adp_distance = abs(platform_adp - overall_pick) if platform_adp < 999 else 50
    score = 100 - min(30, adp_distance * 0.9)
    score += min(12, projection / 28)
    score += min(10, prior_points / 32)

    score += _mock_position_need_score(
        player["pos"], team_roster, round_no, total_rounds
    )
    score += _mock_strategy_bonus_for_ai(player, style, round_no)

    # Controlled randomness prevents all mocks from being identical.
    score += random.uniform(-7.5, 7.5)

    return score, platform_adp

def _mock_ai_pick(mock, order_row, adp_players=None, stats_players=None):
    available = _manual_available(mock)
    if not available:
        return None

    slot = int(order_row["slot"])
    round_no = int(order_row["round"])
    overall = int(order_row["overall"])
    total_rounds = int(mock["rounds"])
    context = dict(CONTEXTS.get(mock["league_key"], CONTEXTS["espn-gramps"]))

    roster = [
        p for p in mock.get("picks", [])
        if int(p.get("slot", 0)) == slot
    ]
    style = _mock_strategy_archetype(slot)

    # Load both datasets once for this pick, rather than once per candidate.
    if adp_players is None:
        _, adp_data = _mock_platform_adp(context)
        adp_players = adp_data.get("players", {})
    if stats_players is None:
        stats_players = _stats_2025_snapshot().get("players", {})

    scored = []
    for player in available:
        score, platform_adp = _mock_ai_score(
            player, context, roster, overall, round_no, total_rounds, style,
            adp_players=adp_players,
            stats_players=stats_players,
        )
        scored.append((score, platform_adp, player))

    scored.sort(key=lambda x: x[0], reverse=True)
    _, platform_adp, chosen = scored[0]

    return {
        "overall": overall,
        "round": round_no,
        "slot": slot,
        "player": chosen["name"],
        "pos": chosen["pos"],
        "team": chosen["team"],
        "adp": round(platform_adp, 1) if platform_adp < 999 else chosen.get("adp", 999),
        "projection": chosen.get("projection", 0),
        "user_pick": False,
        "manager": f"Team {slot}",
        "ai_style": style,
    }

def _manual_autopick_until_user(mock):
    context = dict(CONTEXTS.get(mock["league_key"], CONTEXTS["espn-gramps"]))
    _, adp_data = _mock_platform_adp(context)
    adp_players = adp_data.get("players", {})
    stats_players = _stats_2025_snapshot().get("players", {})

    while True:
        row = _manual_current_order_row(mock)
        if row is None:
            mock["status"] = "complete"
            break

        if int(row["slot"]) == int(mock["draft_slot"]):
            mock["status"] = "your_pick"
            break

        pick = _mock_ai_pick(
            mock, row,
            adp_players=adp_players,
            stats_players=stats_players,
        )
        if not pick:
            mock["status"] = "complete"
            break

        mock.setdefault("picks", []).append(pick)

    mock["updated_at"] = datetime.now(timezone.utc).isoformat()
    return mock

@app.post("/api/mock-draft/manual/autodraft-rest")
def manual_mock_autodraft_rest():
    data = request.get_json(silent=True) or {}
    mock_id = str(data.get("mock_id") or "")
    mock = _manual_mock_get(mock_id)
    if not mock:
        return jsonify(ok=False, error="Mock draft not found."), 404

    context = dict(CONTEXTS.get(mock["league_key"], CONTEXTS["espn-gramps"]))
    _, adp_data = _mock_platform_adp(context)
    adp_players = adp_data.get("players", {})
    stats_players = _stats_2025_snapshot().get("players", {})

    while mock.get("status") != "complete":
        row = _manual_current_order_row(mock)
        if row is None:
            mock["status"] = "complete"
            break

        if int(row["slot"]) == int(mock["draft_slot"]):
            available = _manual_available(mock)
            if not available:
                mock["status"] = "complete"
                break

            roster = [
                p for p in mock.get("picks", [])
                if int(p.get("slot", 0)) == int(mock["draft_slot"])
            ]
            scored = []
            for player in available:
                score, platform_adp = _mock_ai_score(
                    player, context, roster, row["overall"], row["round"],
                    mock["rounds"], "balanced",
                    adp_players=adp_players,
                    stats_players=stats_players,
                )
                scored.append((score, platform_adp, player))
            scored.sort(key=lambda x: x[0], reverse=True)
            _, platform_adp, player = scored[0]
            mock.setdefault("picks", []).append({
                "overall": row["overall"],
                "round": row["round"],
                "slot": row["slot"],
                "player": player["name"],
                "pos": player["pos"],
                "team": player["team"],
                "adp": round(platform_adp, 1) if platform_adp < 999 else player.get("adp", 999),
                "projection": player.get("projection", 0),
                "user_pick": True,
                "manager": "Your Team (Auto)",
                "ai_style": "balanced",
            })
        else:
            pick = _mock_ai_pick(
                mock, row,
                adp_players=adp_players,
                stats_players=stats_players,
            )
            if not pick:
                mock["status"] = "complete"
                break
            mock.setdefault("picks", []).append(pick)

    _manual_finalize_if_complete(mock)
    _manual_mock_save(mock)
    return jsonify(ok=True, mock=_manual_mock_public(mock), grade=mock.get("grade"))

@app.post("/api/mock-draft/manual/start")
def manual_mock_start():
    data = request.get_json(silent=True) or {}
    key = data.get("league_key") or "espn-gramps"
    context = dict(CONTEXTS.get(key, CONTEXTS["espn-gramps"]))

    draft_slot = max(1, min(int(context.get("teams", 12)), int(data.get("draft_slot") or context.get("draft_slot", 7))))
    rounds = max(6, min(15, int(data.get("rounds") or 12)))

    mock = {
        "id": uuid.uuid4().hex[:10],
        "league_key": key,
        "league_name": context.get("league_name", "League"),
        "platform": context.get("platform", ""),
        "scoring": context.get("scoring", ""),
        "teams": int(context.get("teams", 12)),
        "draft_slot": draft_slot,
        "rounds": rounds,
        "status": "starting",
        "picks": [],
        "player_pool": _build_dynamic_mock_pool(context),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    _manual_autopick_until_user(mock)
    _manual_finalize_if_complete(mock)
    _manual_mock_save(mock)

    return jsonify(
        ok=True,
        mock=_manual_mock_public(mock),
        player_pool_count=len(mock.get("player_pool", [])),
    )


def _manual_board_teams(mock):
    teams = {}
    for slot in range(1, int(mock["teams"]) + 1):
        teams[str(slot)] = {
            "slot": slot,
            "label": "Your Team" if slot == int(mock["draft_slot"]) else f"Team {slot}",
            "strategy": "you" if slot == int(mock["draft_slot"]) else _mock_strategy_archetype(slot),
            "roster": [],
        }

    for pick in mock.get("picks", []):
        teams[str(pick["slot"])]["roster"].append(pick)

    return list(teams.values())

@app.get("/api/mock-draft/manual/<mock_id>/board")
def manual_mock_board(mock_id):
    mock = _manual_mock_get(mock_id)
    if not mock:
        return jsonify(ok=False, error="Mock draft not found."), 404
    _manual_refresh_pool_teams(mock)

    return jsonify(ok=True, mock=_manual_mock_public(mock), teams=_manual_board_teams(mock))

@app.get("/api/mock-draft/manual/<mock_id>")
def manual_mock_state(mock_id):
    mock = _manual_mock_get(mock_id)
    if not mock:
        return jsonify(ok=False, error="Mock draft not found."), 404
    _manual_refresh_pool_teams(mock)

    row = _manual_current_order_row(mock)
    available = _manual_available(mock)
    platform = "YAHOO" if "YAHOO" in str(mock.get("platform", "")).upper() else "ESPN"
    local_adp = _mock_local_adp_data(platform).get("players", {})
    platform_adp = {
        key: float(value.get("adp", 999) or 999)
        for key, value in local_adp.items()
        if isinstance(value, dict)
    }

    roster = _manual_user_roster(mock)
    counts = Counter(p["pos"] for p in roster)
    overall = row["overall"] if row else len(mock.get("picks", [])) + 1
    round_no = row["round"] if row else int(mock["rounds"])

    # Apply the ADP that matches the selected league platform.
    scored = []
    for p in available:
        item = dict(p)
        item["adp"] = platform_adp.get(_pr_norm(item["name"]), item.get("adp", 999))
        item["adp_source"] = platform
        item["pick_score"] = _manual_player_pick_score(
            mock,
            item,
            counts=counts,
            overall=overall,
            round_no=round_no,
        )
        scored.append(item)
    # Draft board is ranked by ADP (lowest/best ADP first).
    # Pick Score remains visible as Gridiron IQ's roster-aware recommendation.
    scored.sort(key=lambda x: (float(x.get("adp", 9999)), int(x.get("rank", 9999))))

    return jsonify(
        ok=True,
        mock=_manual_mock_public(mock),
        current_pick=row,
        roster=roster,
        available=scored,
        grade=mock.get("grade") or _manual_grade(mock),
        teams=_manual_board_teams(mock),
    )

@app.post("/api/mock-draft/manual/<mock_id>/pick")
def manual_mock_pick(mock_id):
    mock = _manual_mock_get(mock_id)
    if not mock:
        return jsonify(ok=False, error="Mock draft not found."), 404
    _manual_refresh_pool_teams(mock)

    if mock.get("status") == "complete":
        return jsonify(ok=False, error="This mock draft is already complete."), 400

    row = _manual_current_order_row(mock)
    if not row or int(row["slot"]) != int(mock["draft_slot"]):
        return jsonify(ok=False, error="It is not your pick right now."), 400

    data = request.get_json(silent=True) or {}
    player_name = str(data.get("player") or "").strip()
    lookup = {p["name"]: p for p in _manual_available(mock)}
    player = lookup.get(player_name)
    if not player:
        return jsonify(ok=False, error="That player is no longer available."), 400

    platform = "YAHOO" if "YAHOO" in str(mock.get("platform", "")).upper() else "ESPN"
    local_adp = _mock_local_adp_data(platform).get("players", {})
    platform_adp = {
        key: float(value.get("adp", 999) or 999)
        for key, value in local_adp.items()
        if isinstance(value, dict)
    }
    player = dict(player)
    player["adp"] = platform_adp.get(_pr_norm(player["name"]), player.get("adp", 999))

    pick = {
        "overall": row["overall"],
        "round": row["round"],
        "slot": row["slot"],
        "player": player["name"],
        "pos": player["pos"],
        "team": player["team"],
        "adp": player["adp"],
        "projection": player["projection"],
        "pick_score": _manual_player_pick_score(mock, player),
        "user_pick": True,
        "manager": "Your Team",
    }
    mock.setdefault("picks", []).append(pick)

    _manual_autopick_until_user(mock)
    _manual_finalize_if_complete(mock)
    _manual_mock_save(mock)

    return jsonify(ok=True, mock=_manual_mock_public(mock), grade=mock.get("grade"))

@app.post("/api/mock-draft/manual/<mock_id>/undo")
def manual_mock_undo(mock_id):
    mock = _manual_mock_get(mock_id)
    if not mock:
        return jsonify(ok=False, error="Mock draft not found."), 404

    picks = mock.get("picks", [])
    user_indexes = [i for i, p in enumerate(picks) if p.get("user_pick")]
    if not user_indexes:
        return jsonify(ok=False, error="There is no user pick to undo."), 400

    # Roll back to just before the most recent user selection.
    last_user_index = user_indexes[-1]
    mock["picks"] = picks[:last_user_index]
    mock.pop("completed_at", None)
    mock["status"] = "your_pick"
    mock["grade"] = _manual_grade(mock)
    mock["updated_at"] = datetime.now(timezone.utc).isoformat()
    _manual_mock_save(mock)

    return jsonify(ok=True, mock=_manual_mock_public(mock))

@app.get("/mock-draft/review/<mock_id>")
def manual_mock_review(mock_id):
    mock = _manual_mock_get(mock_id)
    if not mock:
        return page("error.html", code=404, message="Mock draft not found."), 404

    return page(
        "mock_draft_review.html",
        mock=mock,
        roster=_manual_user_roster(mock),
        grade=mock.get("grade") or _manual_grade(mock),
    )


@app.post("/api/mock-draft/run")
def mock_draft_run():
    data = request.get_json(silent=True) or {}
    key = data.get("league_key") or "espn-gramps"
    context = dict(CONTEXTS.get(key, CONTEXTS["espn-gramps"]))
    draft_slot = int(data.get("draft_slot") or context.get("draft_slot", 7))
    strategy = str(data.get("strategy") or "balanced")
    runs = max(1, min(100, int(data.get("runs") or 10)))
    rounds = max(6, min(15, int(data.get("rounds") or 12)))

    results = [run_one_mock(context, draft_slot, strategy, rounds) for _ in range(runs)]
    summary = summarize_mock_batch(results)

    history = mock_history()
    for r in results:
        history.append({
            "strategy":r["strategy"],
            "draft_slot":r["draft_slot"],
            "rounds":r["rounds"],
            "score":r["score"],
            "sequence":r["sequence"],
            "roster":r["roster"],
        })
    save_mock_history(history)

    return jsonify(
        ok=True,
        summary=summary,
        best=max(results,key=lambda r:r["score"]),
        latest=results[-1],
    )

@app.get("/api/mock-draft/history")
def mock_draft_history_api():
    history = mock_history()
    return jsonify(ok=True, history=history[-100:], summary=summarize_mock_batch(history[-100:]))

@app.post("/api/mock-draft/reset")
def mock_draft_reset():
    session["mock_draft_history"] = []
    return jsonify(ok=True)

@app.get("/api/draft/pro/context")
def draft_context_api():
    key=request.args.get("league_key","espn-gramps"); context=CONTEXTS.get(key)
    if not context: return jsonify(ok=False,error="Unknown league."),404
    data=dict(context); data["next_picks"]=next_picks(data["draft_slot"],data["teams"],data["round"])
    return jsonify(ok=True,context=data,state=draft_state(key))


def _draft_platform_for_context(context):
    platform = str(context.get("platform") or "ESPN").upper()
    return "YAHOO" if "YAHOO" in platform else "ESPN"

def _current_master_player(player_name):
    try:
        return _master_players_2026().get("players", {}).get(_pr_norm(player_name), {})
    except Exception:
        return {}

def _draft_player_enrichment(player, context, overall_pick):
    platform = _draft_platform_for_context(context)
    adp_data = _platform_2026_adp_data(platform)
    adp_row = adp_data.get("players", {}).get(_pr_norm(player["name"]), {})
    platform_adp = _fp_float(adp_row.get("adp")) if "_fp_float" in globals() else None
    if platform_adp is None or platform_adp >= 999:
        platform_adp = float(player.get("adp", 999))

    stats = _stats_2025_for_name(player["name"]) or {}
    prior_points = float(stats.get("fantasy_points_ppr") or stats.get("fantasy_points") or 0)
    projection = float(player.get("projection", 0) or 0)

    # Prefer FantasyPros projection snapshot if it exists inside the platform dataset.
    fp_proj = adp_row.get("projection_2026")
    if isinstance(fp_proj, dict):
        for key in ("fpts", "fantasy_points", "fantasy_points_ppr", "points"):
            value = _fp_float(fp_proj.get(key)) if "_fp_float" in globals() else None
            if value is not None:
                projection = value
                break

    value_vs_adp = platform_adp - overall_pick

    current_master = _current_master_player(player["name"])
    return {
        "current_team": current_master.get("team") or player.get("team") or "FA",
        "platform_adp": round(platform_adp, 1) if platform_adp < 999 else 999,
        "projection_2026": round(projection, 1),
        "points_2025": round(prior_points, 1),
        "value_vs_adp": round(value_vs_adp, 1) if platform_adp < 999 else 0,
    }

def _draft_survival_probability(adp, next_overall):
    if adp is None or adp >= 999:
        return 25
    distance = next_overall - float(adp)
    return round(max(5, min(95, 82 * exp(-max(0, distance) / 18))))

def intelligent_recommendation(context, state, round_no, pick_no, strategy):
    overall = (round_no - 1) * context["teams"] + pick_no
    next_round = round_no + 1
    next_overall = (
        (next_round - 1) * context["teams"]
        + snake_pick(next_round, context["draft_slot"], context["teams"])
    )

    counts = position_counts(state["roster"])
    drafted = set(state["drafted"])
    scored = []

    for base in PLAYERS:
        if base["name"] in drafted:
            continue

        enriched = _draft_player_enrichment(base, context, overall)
        need = need_score(base["pos"], counts, context)
        scarcity_label, scarcity_num = scarcity(base["pos"], drafted)

        production_signal = min(12, enriched["projection_2026"] / 28.0)
        history_signal = min(10, enriched["points_2025"] / 30.0)
        adp_signal = max(-10, min(14, enriched["value_vs_adp"] * 0.9))

        position_metrics = position_baseline_metrics(
            projection=enriched["projection_2026"],
            previous_points=enriched["points_2025"],
            adp_value=enriched["value_vs_adp"],
            roster_need=need,
            scarcity=scarcity_num,
        )
        position_evaluation = evaluate_position_player(
            base["pos"],
            position_metrics,
        )

        score = (
            43
            + position_evaluation["score"] * 0.32
            + production_signal
            + history_signal
            + adp_signal
            + need * 0.06
            + scarcity_num * 0.03
            + scoring_bonus(base, context["scoring"])
            + strategy_bonus(base, strategy, round_no)
        )

        survival = _draft_survival_probability(enriched["platform_adp"], next_overall)
        # Reward players unlikely to make it back to the user.
        score += (100 - survival) * 0.07

        fit = "Excellent" if need >= 80 else "Good" if need >= 55 else "Depth"

        scored.append({
            **base,
            **enriched,
            "iq_score": round(max(40, min(99, score))),
            "roster_fit": fit,
            "scarcity": scarcity_label,
            "survival_probability": survival,
            "position_evaluation": position_evaluation,
            "position_score": position_evaluation["score"],
            "draft_action": position_evaluation["action"],
            "criteria_strengths": position_evaluation["strengths"],
            "criteria_risks": position_evaluation["risks"],
            "criteria_coverage": position_evaluation["coverage"],
        })

    scored.sort(
        key=lambda x: (
            x["iq_score"],
            -x["projection_2026"],
            -x["points_2025"],
            -x["rank"],
        ),
        reverse=True,
    )

    if not scored:
        return recommendation(context, state, round_no, pick_no, strategy)

    best = scored[0]
    same_tier = [
        p for p in scored
        if p["pos"] == best["pos"] and p.get("tier") == best.get("tier")
    ]
    tier_risk = "High" if len(same_tier) <= 2 else "Medium" if len(same_tier) <= 4 else "Low"

    rationale = (
        f"{best['name']} grades as the best current pick using "
        f"{context['platform']} ADP, 2026 projection, 2025 production, "
        f"positional need and scarcity. "
        f"ADP: {best['platform_adp'] if best['platform_adp'] < 999 else 'N/A'}; "
        f"2025 PPR points: {best['points_2025']}; "
        f"2026 projection: {best['projection_2026']}; "
        f"chance of surviving to your next pick: {best['survival_probability']}%. "
        f"Position model: {best['position_evaluation']['grade']} "
        f"({best['position_evaluation']['score']}/100) — "
        f"{best['position_evaluation']['action']}."
    )

    return {
        "player": best,
        "score": best["iq_score"],
        "confidence": min(97, max(60, best["iq_score"] - 2)),
        "adp_value": f"{best['value_vs_adp']:+.1f}",
        "platform_adp": best["platform_adp"],
        "projection_2026": best["projection_2026"],
        "points_2025": best["points_2025"],
        "roster_fit": best["roster_fit"],
        "scarcity": best["scarcity"],
        "tier_risk": tier_risk,
        "survival_probability": best["survival_probability"],
        "position_evaluation": best["position_evaluation"],
        "position_score": best["position_score"],
        "draft_action": best["draft_action"],
        "criteria_strengths": best["criteria_strengths"],
        "criteria_risks": best["criteria_risks"],
        "criteria_coverage": best["criteria_coverage"],
        "rationale": rationale,
        "next_best": scored[1:4],
    }


@app.get("/api/draft/position-criteria")
def draft_position_criteria_api():
    return jsonify(ok=True, weights=load_position_weights())


@app.post("/api/draft/evaluate-player")
def draft_evaluate_player_api():
    payload = request.get_json(silent=True) or {}
    position = str(payload.get("position") or "").upper()
    metrics = payload.get("metrics") or {}

    if position not in {"QB", "RB", "WR", "TE", "K", "DEF", "DST"}:
        return jsonify(
            ok=False,
            error="Position must be QB, RB, WR, TE, K, DEF or DST.",
        ), 400

    return jsonify(
        ok=True,
        player=payload.get("player"),
        evaluation=evaluate_position_player(position, metrics),
    )


@app.get("/api/draft/intelligence")
def draft_intelligence_api():
    key = request.args.get("league_key") or "espn-gramps"
    context = dict(CONTEXTS.get(key, CONTEXTS["espn-gramps"]))
    state = draft_state(key)
    rec = intelligent_recommendation(
        context,
        state,
        int(context.get("round", 1)),
        int(context.get("pick_in_round", 1)),
        "balanced",
    )
    return jsonify(ok=True, recommendation=rec, context=context)

@app.post("/api/draft/pro/recommend")
def draft_recommend_api():
    data = request.get_json(silent=True) or {}
    key = data.get("league_key") or "espn-gramps"
    context = dict(CONTEXTS.get(key, CONTEXTS["espn-gramps"]))

    context["draft_slot"] = int(data.get("draft_slot") or context["draft_slot"])
    context["round"] = int(data.get("round") or context["round"])
    context["pick_in_round"] = int(data.get("pick_in_round") or context["pick_in_round"])
    context["next_picks"] = next_picks(
        context["draft_slot"], context["teams"], context["round"]
    )

    rec = intelligent_recommendation(
        context,
        draft_state(key),
        context["round"],
        context["pick_in_round"],
        str(data.get("strategy") or "balanced"),
    )
    return jsonify(ok=True, recommendation=rec, context=context)

@app.post("/api/draft/pro/mark")
def draft_mark_api():
    data=request.get_json(silent=True) or {}; key=data.get("league_key") or "espn-gramps"; player=str(data.get("player") or "").strip(); drafted=bool(data.get("drafted"))
    if not player: return jsonify(ok=False,error="Player is required."),400
    state=draft_state(key); ds=set(state["drafted"])
    if drafted:
        ds.add(player)
        if player not in state["roster"]: state["roster"].append(player)
        state["draft_log"].append({"overall":len(state["draft_log"])+1,"player":player,"team_label":"Your Team"})
    else:
        ds.discard(player); state["roster"]=[x for x in state["roster"] if x!=player]; state["draft_log"]=[x for x in state["draft_log"] if x["player"]!=player]
    state["drafted"]=list(ds); save_draft_state(key,state)
    return jsonify(ok=True,state=state,reload=True)

@app.post("/api/draft/pro/reset")
def draft_reset_api():
    data=request.get_json(silent=True) or {}; key=data.get("league_key") or "espn-gramps"; save_draft_state(key,{"drafted":[],"roster":[],"draft_log":[]})
    return jsonify(ok=True)

@app.post("/api/draft/pro/simulate")
def draft_sim_api():
    data=request.get_json(silent=True) or {}; key=data.get("league_key") or "espn-gramps"; strategy=str(data.get("strategy") or "balanced"); context=CONTEXTS.get(key,CONTEXTS["espn-gramps"]); slot=int(data.get("draft_slot") or context["draft_slot"])
    results={"balanced":("Balanced build grades best","A balanced RB/WR opening keeps the widest number of strong roster paths available through Round 6."),"hero-rb":("Hero RB is a strong fit","Secure one premium running back early, then attack WR depth."),"zero-rb":("Zero RB is viable","Prioritize elite WR/TE value early, then attack volume backs in the middle rounds."),"late-qb":("Waiting on QB improves depth","Build RB/WR/TE strength before selecting quarterback.")}
    h,s=results.get(strategy,results["balanced"]); s+=f" From draft slot {slot} in this {context['teams']}-team {context['scoring']} league."
    return jsonify(ok=True,result={"headline":h,"summary":s})

@app.post("/api/trade/analyze")
def trade_analyze():
    d=request.get_json(silent=True) or {}; give=str(d.get("give","")).strip(); receive=str(d.get("receive","")).strip()
    if not give or not receive: return jsonify(ok=False,error="Enter players on both sides."),400
    return jsonify(ok=True,verdict="Fair starting point",confidence=72)

@app.post("/api/lineup/optimize")
def lineup_optimize():
    return jsonify(ok=True,lineup=DEMO["lineup"],projected_total=round(sum(x["projection"] for x in DEMO["lineup"]),1))

@app.post("/api/waivers/analyze")
def waiver_analyze():
    return jsonify(ok=True,recommendations=DEMO["waivers"])


# ============================================================
# PLAYER RESEARCH CENTER
# ============================================================
import csv
from html.parser import HTMLParser
import io
import html
import re
import time

PLAYER_CACHE_FILE = DATA_DIR / "sleeper_players_cache.json"
BUNDLED_PLAYER_CACHE_FILE = BASE_DIR / "data" / "sleeper_players_cache.json"
PLAYER_DAILY_STATUS_FILE = DATA_DIR / "player_research_daily_status.json"
BUNDLED_PLAYER_DAILY_STATUS_FILE = BASE_DIR / "data" / "player_research_daily_status.json"
PLAYER_NEWS_INDEX_FILE = DATA_DIR / "player_news_index.json"
BUNDLED_PLAYER_NEWS_INDEX_FILE = BASE_DIR / "data" / "player_news_index.json"
PLAYER_CACHE_TTL = 24 * 60 * 60


def _player_daily_refresh_status():
    for path in (PLAYER_DAILY_STATUS_FILE, BUNDLED_PLAYER_DAILY_STATUS_FILE):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    return {}


def _player_daily_refresh_is_fresh():
    value = str(_player_daily_refresh_status().get("checked_at") or "")
    if not value:
        return False
    try:
        checked = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - checked).total_seconds() < 48 * 60 * 60
    except (TypeError, ValueError):
        return False


def _player_news_index():
    for path in (PLAYER_NEWS_INDEX_FILE, BUNDLED_PLAYER_NEWS_INDEX_FILE):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("players"), dict):
                return payload
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    return {"players": {}}


def _indexed_player_news(player_name):
    payload = _player_news_index()
    row = payload.get("players", {}).get(_pr_norm(player_name), {})
    news = row.get("news", []) if isinstance(row, dict) else []
    return [item for item in news if isinstance(item, dict)]


def _has_active_injury(value):
    status = str(value or "").strip()
    return bool(status and _pr_norm(status) not in {"active", "healthy", "none", "na", "full"})

def _pr_norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

def _pr_num(value):
    try:
        return float(value) if value not in (None, "", "NA", "NaN") else 0.0
    except Exception:
        return 0.0

def _pr_int(value):
    try:
        return int(float(value))
    except Exception:
        return 0

def _pr_players():
    """
    Return the current NFL fantasy-player directory.

    Sleeper's active-player endpoint is the canonical current-player source.
    The local 2026 master file is used only as a fallback, not as the full
    player universe.
    """
    cache_path = PLAYER_CACHE_FILE if PLAYER_CACHE_FILE.exists() else BUNDLED_PLAYER_CACHE_FILE
    try:
        if (
            cache_path.exists()
            and (
                (time.time() - cache_path.stat().st_mtime) < PLAYER_CACHE_TTL
                or _player_daily_refresh_is_fresh()
            )
        ):
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached:
                return cached
    except Exception:
        pass

    try:
        response = requests.get(
            "https://api.sleeper.app/v1/players/nfl?active=true",
            headers={"User-Agent": "Gridiron-IQ/2026"},
            timeout=(5, 25),
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data:
            try:
                PLAYER_CACHE_FILE.write_text(
                    json.dumps(data, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass
            return data
    except Exception as exc:
        app.logger.warning("Current player directory refresh failed: %s", exc)

    try:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached:
                return cached
    except Exception:
        pass

    # Final fallback: use the master file, but preserve only current-looking
    # fantasy positions instead of treating every historical row as active.
    try:
        master = _master_players_2026()
        out = {}
        for index, player in enumerate(master.get("players", {}).values(), 1):
            if not isinstance(player, dict):
                continue
            position = str(player.get("position") or "").upper()
            if position == "DST":
                position = "DEF"
            if position not in {"QB", "RB", "WR", "TE", "K", "DEF"}:
                continue
            name = str(player.get("name") or "").strip()
            if not name:
                continue
            out[str(player.get("sleeper_id") or index)] = {
                "full_name": name,
                "position": position,
                "fantasy_positions": [position],
                "team": player.get("team") or "FA",
                "status": player.get("status") or "",
                "age": player.get("age"),
                "years_exp": player.get("years_exp"),
                "college": player.get("college"),
                "injury_status": player.get("injury_status"),
                "rookie": bool(player.get("rookie")),
            }
        return out
    except Exception:
        return {}


def _pr_search(query, limit=25):
    q = _pr_norm(query)
    if not q:
        return []
    rows = []
    for player_id, p in _pr_players().items():
        name = p.get("full_name") or " ".join(x for x in [p.get("first_name"), p.get("last_name")] if x)
        if not name or q not in _pr_norm(name):
            continue
        rows.append({
            "player_id": player_id,
            "name": name,
            "team": p.get("team") or "FA",
            "position": p.get("position") or ((p.get("fantasy_positions") or [""])[0]),
            "status": p.get("status") or "",
            "age": p.get("age"),
            "years_exp": p.get("years_exp"),
        })
    rows.sort(key=lambda x: (0 if _pr_norm(x["name"]).startswith(q) else 1, x["name"]))
    return rows[:limit]

def _pr_urls(season):
    season = int(season)
    return [
        f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_reg_{season}.csv",
        f"https://github.com/nflverse/nflverse-data/releases/download/player_stats/stats_player_week_{season}.csv",
    ]


NFLVERSE_2025_STATS_URLS = tuple(_pr_urls(2025))


def _pr_rows(season, force=False):
    """Load nflverse stats, optionally bypassing the saved CSV."""
    season = int(season)
    cache = DATA_DIR / f"player_stats_{season}.csv"
    cached_rows = []

    if cache.exists():
        try:
            cached_text = cache.read_text(encoding="utf-8")
            cached_rows = list(csv.DictReader(io.StringIO(cached_text)))
            if cached_rows and not force:
                return cached_rows
        except Exception:
            cached_rows = []

    headers = {
        "Accept": "text/csv,application/octet-stream;q=0.9,*/*;q=0.8",
        "User-Agent": "Gridiron-IQ/2026",
    }
    errors = []

    for url in _pr_urls(season):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=(10, 60),
                allow_redirects=True,
            )
            if response.status_code != 200:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue
            if len(response.content) < 1000:
                errors.append(f"{url}: response too small")
                continue

            csv_text = response.content.decode("utf-8-sig", errors="replace")
            rows = list(csv.DictReader(io.StringIO(csv_text)))
            if not rows:
                errors.append(f"{url}: empty CSV")
                continue

            columns = set(rows[0].keys())
            expected = {
                "player_display_name", "player_name", "player_id",
                "passing_yards", "rushing_yards", "receiving_yards",
            }
            if not columns.intersection(expected):
                errors.append(f"{url}: response was not player-stat CSV")
                continue

            cache.write_text(csv_text, encoding="utf-8")
            return rows
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    if cached_rows:
        app.logger.warning(
            "Using cached %s stats because remote refresh failed: %s",
            season,
            " | ".join(errors),
        )
        return cached_rows

    raise RuntimeError(
        f"Unable to load {season} nflverse stats. "
        + (" | ".join(errors) if errors else "No source succeeded.")
    )


def _pr_row_name(row):
    for key in ("player_display_name", "player_name", "name", "full_name"):
        if row.get(key):
            return row[key]
    return ""

def _pr_aggregate(rows, player_name):
    target = _pr_norm(player_name)
    matches = [r for r in rows if _pr_norm(_pr_row_name(r)) == target]
    if not matches:
        matches = [r for r in rows if target and (target in _pr_norm(_pr_row_name(r)) or _pr_norm(_pr_row_name(r)) in target)]
    if not matches:
        return None

    def total(field):
        return sum(_pr_num(r.get(field)) for r in matches)

    games_values = [_pr_int(r.get("games") or r.get("games_played")) for r in matches]
    week_values = {r.get("week") for r in matches if r.get("week")}
    games = max(max(games_values or [0]), len(week_values), 1)

    return {
        "games": games,
        "completions": total("completions"),
        "attempts": total("attempts"),
        "passing_yards": total("passing_yards"),
        "passing_tds": total("passing_tds"),
        "interceptions": total("interceptions") or total("passing_interceptions"),
        "sacks_suffered": total("sacks_suffered"),
        "passing_air_yards": total("passing_air_yards"),
        "passing_first_downs": total("passing_first_downs"),
        "passing_epa": total("passing_epa"),
        "passing_cpoe": total("passing_cpoe"),
        "rushing_yards": total("rushing_yards"),
        "rushing_tds": total("rushing_tds"),
        "carries": total("carries") or total("rushing_attempts"),
        "rushing_first_downs": total("rushing_first_downs"),
        "rushing_epa": total("rushing_epa"),
        "rushing_10": total("rushing_10"),
        "rushing_20": total("rushing_20"),
        "receptions": total("receptions"),
        "targets": total("targets"),
        "receiving_yards": total("receiving_yards"),
        "receiving_tds": total("receiving_tds"),
        "receiving_air_yards": total("receiving_air_yards"),
        "receiving_yards_after_catch": total("receiving_yards_after_catch"),
        "receiving_first_downs": total("receiving_first_downs"),
        "receiving_epa": total("receiving_epa"),
        "target_share": max((_pr_num(row.get("target_share")) for row in matches), default=0),
        "air_yards_share": max((_pr_num(row.get("air_yards_share")) for row in matches), default=0),
        "wopr": max((_pr_num(row.get("wopr")) for row in matches), default=0),
        "fg_made": total("fg_made"),
        "fg_att": total("fg_att"),
        "fg_pct": max((_pr_num(row.get("fg_pct")) for row in matches), default=0),
        "fg_long": max((_pr_num(row.get("fg_long")) for row in matches), default=0),
        "fg_made_40_49": total("fg_made_40_49"),
        "fg_made_50_59": total("fg_made_50_59"),
        "fg_made_60_": total("fg_made_60_"),
        "pat_made": total("pat_made"),
        "pat_att": total("pat_att"),
        "pat_pct": max((_pr_num(row.get("pat_pct")) for row in matches), default=0),
        "fantasy_points": total("fantasy_points"),
        "fantasy_points_ppr": total("fantasy_points_ppr"),
    }

CAREER_STATS_FILE = DATA_DIR / "nfl_player_career_history.json"
BUNDLED_CAREER_STATS_FILE = BASE_DIR / "data" / "nfl_player_career_history.json"
_CAREER_STATS_CACHE = {"signature": None, "payload": None}


def _career_stats_paths():
    paths = []
    seen = set()
    for path in (CAREER_STATS_FILE, BUNDLED_CAREER_STATS_FILE):
        identity = str(path.resolve(strict=False))
        if identity in seen:
            continue
        seen.add(identity)
        paths.append(path)
    return paths


def _career_stats_signature():
    signature = []
    for path in _career_stats_paths():
        try:
            stat = path.stat()
            signature.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((str(path), 0, 0))
    return tuple(signature)


def _career_stats_snapshot():
    empty = {"updated_at": "", "loaded_seasons": [], "players": {}, "status": "missing"}
    signature = _career_stats_signature()
    if (
        _CAREER_STATS_CACHE.get("signature") == signature
        and isinstance(_CAREER_STATS_CACHE.get("payload"), dict)
    ):
        return _CAREER_STATS_CACHE["payload"]

    candidates = []
    for path in _career_stats_paths():
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            payload.setdefault("loaded_seasons", [])
            payload.setdefault("players", {})
            payload["loaded_from"] = str(path)
            player_seasons = sum(
                len(seasons) for seasons in payload["players"].values()
                if isinstance(seasons, dict)
            )
            candidates.append((
                len(payload["loaded_seasons"]),
                player_seasons,
                payload,
            ))
        except Exception as exc:
            app.logger.warning("Career-history database %s could not be read: %s", path, exc)
    if not candidates:
        return empty
    payload = max(candidates, key=lambda item: (item[0], item[1]))[2]
    _CAREER_STATS_CACHE.update({"signature": signature, "payload": payload})
    return payload


def _aggregate_season_rows(rows, season):
    grouped = defaultdict(list)
    for row in rows or []:
        name = _pr_row_name(row)
        if name:
            grouped[_pr_norm(name)].append(row)

    result = {}
    for norm, matches in grouped.items():
        name = _pr_row_name(matches[0])
        stats = _pr_aggregate(matches, name)
        if not stats:
            continue
        first = matches[0]
        position = str(first.get("position") or first.get("position_group") or "").upper()
        if position == "DST":
            position = "DEF"
        result[norm] = {
            "season": int(season),
            "name": name,
            "player_id": str(first.get("player_id") or ""),
            "team": str(first.get("recent_team") or first.get("team") or ""),
            "position": position,
            **stats,
        }
    return result


def _build_career_history_season(season, force=False):
    season = int(season)
    if season < 1999 or season > 2025:
        raise ValueError("Career-history season must be between 1999 and 2025.")

    rows = _pr_rows(season, force=force)
    season_players = _aggregate_season_rows(rows, season)
    payload = _career_stats_snapshot()
    players = payload.setdefault("players", {})

    for norm in list(players):
        seasons = players.get(norm)
        if not isinstance(seasons, dict):
            players[norm] = {}
            continue
        seasons.pop(str(season), None)
        if not seasons:
            players.pop(norm, None)

    for norm, record in season_players.items():
        players.setdefault(norm, {})[str(season)] = record

    loaded = {int(value) for value in payload.get("loaded_seasons", [])}
    loaded.add(season)
    payload.update({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "loaded_seasons": sorted(loaded),
        "season_count": len(loaded),
        "player_count": len(players),
        "status": "local",
        "source": "nflverse Player Summary Stats",
    })

    temp = CAREER_STATS_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(CAREER_STATS_FILE)
    return payload, len(season_players)


def _pr_history(player_name, career_snapshot=None):
    norm = _pr_norm(player_name)
    payload = (
        career_snapshot
        if isinstance(career_snapshot, dict)
        else _career_stats_snapshot()
    )
    season_map = payload.get("players", {}).get(norm, {})
    history = []

    if isinstance(season_map, dict):
        for season_key, record in season_map.items():
            if not isinstance(record, dict):
                continue
            clean = {k: v for k, v in record.items() if k not in {"name", "player_id"}}
            clean["season"] = int(record.get("season") or season_key)
            history.append(clean)

    stats_2025 = _stats_2025_for_name(player_name)
    if stats_2025 and not any(item.get("season") == 2025 for item in history):
        clean = {k: v for k, v in stats_2025.items() if k not in {"name", "player_id"}}
        history.append({"season": 2025, **clean})

    history.sort(key=lambda item: int(item.get("season", 0)))
    return history


STATS_2025_SNAPSHOT_FILE = DATA_DIR / "nfl_player_stats_2025.json"
BUNDLED_STATS_2025_FILE = BASE_DIR / "data" / "nfl_player_stats_2025.json"

STATS_2025_FIELDS = (
    "games", "completions", "attempts", "passing_yards", "passing_tds",
    "interceptions", "sacks_suffered", "passing_air_yards", "passing_first_downs",
    "passing_epa", "passing_cpoe", "carries", "rushing_yards", "rushing_tds",
    "rushing_first_downs", "rushing_epa", "rushing_10", "rushing_20",
    "targets", "receptions", "receiving_yards", "receiving_tds",
    "receiving_air_yards", "receiving_yards_after_catch", "receiving_first_downs",
    "receiving_epa", "target_share", "air_yards_share", "wopr",
    "fg_made", "fg_att", "fg_pct", "fg_long", "fg_made_40_49",
    "fg_made_50_59", "fg_made_60_", "pat_made", "pat_att", "pat_pct",
    "fantasy_points", "fantasy_points_ppr", "offense_snaps", "snap_share",
    "red_zone_targets", "end_zone_targets", "red_zone_carries",
    "red_zone_receptions", "red_zone_touches", "goal_line_carries",
    "yards_before_contact", "yards_before_contact_per_carry",
    "yards_after_contact", "yards_after_contact_per_carry",
    "rushing_broken_tackles", "carries_per_broken_tackle",
    "receiving_broken_tackles", "receptions_per_broken_tackle", "drops",
    "drop_rate", "target_interceptions", "target_passer_rating",
    "qb_throwaways", "qb_drops", "qb_drop_rate", "qb_bad_throws",
    "qb_bad_throw_rate", "qb_pocket_time", "qb_blitzes", "qb_hurries",
    "qb_hits", "qb_pressures", "qb_pressure_rate", "qb_on_target_throws",
    "qb_on_target_rate", "qb_scrambles", "qb_scramble_ypa",
    "ngs_time_to_throw", "ngs_completed_air_yards", "ngs_intended_air_yards",
    "ngs_aggressiveness", "ngs_expected_completion_rate", "ngs_cpoe",
    "ngs_passer_rating", "ngs_cushion", "ngs_separation", "ngs_adot",
    "ngs_air_yards_share", "ngs_yac_per_reception",
    "ngs_expected_yac_per_reception", "ngs_yac_over_expected_per_reception",
    "ngs_rush_efficiency", "ngs_stacked_box_rate", "ngs_time_to_line",
    "ngs_expected_rush_yards", "ngs_rush_yards_over_expected",
    "ngs_ryoe_per_carry", "ngs_ryoe_success_rate",
    "expected_fantasy_points_ppr", "expected_receptions",
    "expected_total_yards", "expected_total_tds"
)

def _stats_2025_snapshot():
    empty = {
        "season": 2025,
        "season_type": "REG",
        "source": "",
        "updated_at": "",
        "player_count": 0,
        "position_counts": {},
        "players": {},
        "status": "missing",
    }

    snapshot_path = (
        STATS_2025_SNAPSHOT_FILE
        if STATS_2025_SNAPSHOT_FILE.exists()
        else BUNDLED_STATS_2025_FILE
    )

    if not snapshot_path.exists():
        return empty

    try:
        raw = snapshot_path.read_text(encoding="utf-8")
        if not raw.strip():
            return empty
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return empty
        if not isinstance(payload.get("players"), dict):
            payload["players"] = {}
        payload["player_count"] = len(payload["players"])
        payload.setdefault("position_counts", {})
        payload.setdefault("updated_at", "")
        payload.setdefault("source", "")
        payload.setdefault("status", "local")
        return payload
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        app.logger.warning("Invalid 2025 stats snapshot ignored: %s", exc)
        try:
            damaged = snapshot_path.with_suffix(
                snapshot_path.suffix + ".invalid"
            )
            if snapshot_path == STATS_2025_SNAPSHOT_FILE and damaged.exists():
                damaged.unlink()
            if snapshot_path == STATS_2025_SNAPSHOT_FILE:
                snapshot_path.replace(damaged)
        except Exception:
            pass
        return empty



def _stats_2025_clean_number(value):
    """Convert nflverse CSV values into JSON-safe numbers."""
    try:
        if value in (None, "", "NA", "NaN", "nan", "null"):
            return 0
        number = float(value)
        return int(number) if number.is_integer() else round(number, 2)
    except (TypeError, ValueError):
        return 0


def _stats_2025_player_record(name, rows):
    """
    Convert one player's nflverse rows into the saved 2025 stat record.

    The nflverse source may contain either one season-summary row or several
    weekly rows. `_pr_aggregate` handles both shapes.
    """
    rows = rows or []
    stats = _pr_aggregate(rows, name) or {}
    first = rows[0] if rows else {}

    position = str(
        first.get("position")
        or first.get("position_group")
        or stats.get("position")
        or ""
    ).upper()

    if position == "DST":
        position = "DEF"

    record = {
        "name": name,
        "player_id": str(
            first.get("player_id")
            or stats.get("player_id")
            or ""
        ),
        "position": position,
        "team": str(
            first.get("recent_team")
            or first.get("team")
            or stats.get("team")
            or ""
        ),
    }

    for field in STATS_2025_FIELDS:
        record[field] = _stats_2025_clean_number(stats.get(field))

    record["total_tds"] = (
        _stats_2025_clean_number(record.get("passing_tds"))
        + _stats_2025_clean_number(record.get("rushing_tds"))
        + _stats_2025_clean_number(record.get("receiving_tds"))
    )

    return record


def _build_2025_stats_snapshot(force=False):
    rows = _pr_rows(2025, force=force)
    if not rows:
        raise RuntimeError(
            "No 2025 nflverse player-stat rows were returned. "
            "Check Render outbound access and the nflverse loader."
        )

    # Regular season only when season_type is present.
    regular = [
        row for row in rows
        if str(row.get("season_type") or "REG").upper() == "REG"
    ]
    if regular:
        rows = regular

    grouped = {}
    for row in rows:
        name = _pr_row_name(row)
        norm = _pr_norm(name)
        if not norm:
            continue
        grouped.setdefault(norm, {"name": name, "rows": []})
        grouped[norm]["rows"].append(row)

    players = {}
    position_counts = {}
    for norm, bundle in grouped.items():
        record = _stats_2025_player_record(bundle["name"], bundle["rows"])
        # Keep fantasy-relevant offensive players and kickers.
        pos = record.get("position", "")
        if pos not in {"QB", "RB", "WR", "TE", "K", "FB"}:
            continue
        players[norm] = record
        position_counts[pos] = position_counts.get(pos, 0) + 1

    payload = {
        "season": 2025,
        "season_type": "REG",
        "source": "nflverse Player Summary Stats",
        "status": "local",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "player_count": len(players),
        "position_counts": position_counts,
        "players": players,
    }

    if not players:
        raise RuntimeError("2025 rows loaded, but no fantasy-relevant player records were built.")

    STATS_2025_SNAPSHOT_FILE.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8"
    )
    return payload


def _ensure_2025_stats_snapshot(force=False):
    """
    Return the saved 2025 snapshot, building it automatically when it is empty.
    This fixes the previous undefined-function failure that silently blanked
    every historical-stat column.
    """
    existing = _stats_2025_snapshot()
    if existing.get("players") and not force:
        return existing
    return _build_2025_stats_snapshot(force=force)

def _stats_2025_for_name(player_name):
    """
    Fast local lookup only.

    Player Research loops through hundreds of players. Calling _pr_rows(2025)
    here caused the full CSV to be re-read and parsed hundreds of times, which
    triggered Gunicorn WORKER TIMEOUT on Render.
    """
    snapshot = _stats_2025_snapshot()
    return snapshot.get("players", {}).get(_pr_norm(player_name))

@app.post("/api/data/build-2025-stats")
def build_2025_stats_api():
    try:
        payload = _ensure_2025_stats_snapshot(force=True)
        _clear_pr_rows_cache()
        return jsonify(
            ok=True,
            season=2025,
            season_type="REG",
            status=payload.get("status"),
            source=payload.get("source"),
            player_count=len(payload.get("players", {})),
            position_counts=payload.get("position_counts", {}),
            updated_at=payload.get("updated_at"),
            data_directory=str(DATA_DIR),
            message="2025 player stats refreshed successfully.",
        )
    except Exception as exc:
        app.logger.exception("2025 player statistics refresh failed")
        existing = _stats_2025_snapshot()
        return jsonify(
            ok=False,
            season=2025,
            status="error",
            error=str(exc),
            existing_player_count=len(existing.get("players", {})),
            existing_updated_at=existing.get("updated_at", ""),
        ), 500


@app.get("/api/data/2025-stats/status")
def stats_2025_status_api():
    payload = _stats_2025_snapshot()
    return jsonify(
        ok=bool(payload.get("players")),
        season=2025,
        season_type=payload.get("season_type", "REG"),
        status=payload.get("status", "empty"),
        source=payload.get("source"),
        player_count=len(payload.get("players", {})),
        position_counts=payload.get("position_counts", {}),
        updated_at=payload.get("updated_at", ""),
    )

@app.get("/api/data/2025-stats/player/<path:player_name>")
def stats_2025_player_api(player_name):
    player = _stats_2025_for_name(player_name)
    if not player:
        return jsonify(ok=False, error="Player not found in 2025 stats database."), 404
    return jsonify(ok=True, season=2025, player=player)




@app.post("/api/data/career-history/season/<int:season>")
def build_career_history_season_api(season):
    body = request.get_json(silent=True) or {}
    try:
        payload, count = _build_career_history_season(season, force=bool(body.get("force", False)))
        return jsonify(
            ok=True,
            season=season,
            season_player_count=count,
            loaded_seasons=payload.get("loaded_seasons", []),
            total_player_count=payload.get("player_count", 0),
            updated_at=payload.get("updated_at", ""),
        )
    except Exception as exc:
        app.logger.exception("Career-history season %s failed", season)
        return jsonify(ok=False, season=season, error=str(exc)), 500


@app.get("/api/data/career-history/status")
def career_history_status_api():
    payload = _career_stats_snapshot()
    return jsonify(
        ok=bool(payload.get("loaded_seasons")),
        loaded_seasons=payload.get("loaded_seasons", []),
        season_count=len(payload.get("loaded_seasons", [])),
        player_count=len(payload.get("players", {})),
        updated_at=payload.get("updated_at", ""),
    )


# ============================================================
# 2026 MASTER PLAYER DATABASE + REFRESH ENGINE
# ============================================================
MASTER_PLAYERS_2026_FILE = DATA_DIR / "nfl_players_2026.json"
BUNDLED_MASTER_PLAYERS_2026_FILE = BASE_DIR / "data" / "nfl_players_2026.json"

def _master_players_2026():
    for path in (MASTER_PLAYERS_2026_FILE, BUNDLED_MASTER_PLAYERS_2026_FILE):
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            continue
    return {
        "season": 2026,
        "updated_at": "",
        "count": 0,
        "sources": [],
        "players": {}
    }

def _master_player_norm(name):
    return _pr_norm(name)

def _fp_headers():
    key = os.getenv("FANTASYPROS_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}

def _fp_get_json(url, params=None, timeout=25):
    headers = _fp_headers()
    if not headers:
        raise RuntimeError("FANTASYPROS_API_KEY is not configured.")
    r = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _fp_player_list_2026():
    payload = _fp_get_json("https://api.fantasypros.com/public/v2/json/nfl/players")
    rows = payload.get("players") or []
    out = {}
    for p in rows:
        name = str(p.get("player_name") or p.get("name") or "").strip()
        if not name:
            continue
        pos = str(
            p.get("position_id")
            or p.get("player_position_id")
            or p.get("player_positions")
            or ""
        ).split(",")[0].upper()
        if pos == "DST":
            pos = "DEF"
        team = str(
            p.get("team_id")
            or p.get("player_team_id")
            or p.get("player_team")
            or p.get("team")
            or ""
        ).upper()
        out[_master_player_norm(name)] = {
            "name": name,
            "position": pos,
            "team": team,
            "fantasypros_id": p.get("player_id") or p.get("fpid"),
            "espn_id": p.get("player_espn_id") or p.get("espn_player_id"),
            "yahoo_id": p.get("player_yahoo_id"),
            "bye_week": p.get("player_bye_week") or p.get("bye_week"),
            "source_player": "FantasyPros",
        }
    return out

def _fp_projections_2026(scoring="PPR"):
    payload = _fp_get_json(
        "https://api.fantasypros.com/public/v2/json/nfl/2026/projections",
        params={
            "week": 0,
            "positions": "QB:RB:WR:TE:DST:K",
            "scoring": scoring,
        },
    )
    rows = payload.get("players") or []
    out = {}
    for p in rows:
        name = str(p.get("name") or p.get("player_name") or "").strip()
        if not name:
            continue
        stats = p.get("stats") or {}
        pos = str(p.get("position_id") or p.get("position") or "").upper()
        if pos == "DST":
            pos = "DEF"
        team = str(p.get("team_id") or p.get("team") or "").upper()
        out[_master_player_norm(name)] = {
            "projection": {
                "fantasy_points": stats.get("points"),
                "ppr_points": stats.get("points_ppr"),
                "half_ppr_points": stats.get("points_half"),
                "pass_yards": stats.get("pass_yds"),
                "pass_tds": stats.get("pass_tds"),
                "interceptions": stats.get("pass_ints") or stats.get("pass_int"),
                "rush_attempts": stats.get("rush_att"),
                "rush_yards": stats.get("rush_yds"),
                "rush_tds": stats.get("rush_tds"),
                "receptions": stats.get("rec_rec"),
                "receiving_yards": stats.get("rec_yds"),
                "receiving_tds": stats.get("rec_tds"),
                "targets": stats.get("rec_tgt") or stats.get("targets"),
            },
            "projection_team": team,
            "projection_position": pos,
        }
    return out

def _fp_adp_2026(scoring="PPR"):
    payload = _fp_get_json(
        "https://api.fantasypros.com/public/v2/json/nfl/2026/consensus-rankings",
        params={"position": "ALL", "scoring": scoring, "type": "ADP", "week": 0},
    )
    # FantasyPros responses have varied slightly over time. Accept common shapes.
    rows = (
        payload.get("players")
        or payload.get("rankings")
        or payload.get("results")
        or []
    )
    if isinstance(rows, dict):
        flattened = []
        for value in rows.values():
            if isinstance(value, list):
                flattened.extend(value)
        rows = flattened

    out = {}
    for p in rows if isinstance(rows, list) else []:
        name = str(p.get("player_name") or p.get("name") or "").strip()
        if not name:
            continue
        adp = p.get("rank_adp") or p.get("adp") or p.get("rank_ave") or p.get("rank_ecr")
        try:
            adp = float(adp)
        except Exception:
            adp = None
        out[_master_player_norm(name)] = {
            "adp": adp,
            "adp_position_rank": p.get("pos_rank"),
        }
    return out

def _sleeper_active_players_2026():
    r = requests.get(
        "https://api.sleeper.app/v1/players/nfl?active=true",
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    out = {}
    for player_id, p in payload.items():
        name = str(
            p.get("full_name")
            or " ".join(x for x in [p.get("first_name"), p.get("last_name")] if x)
        ).strip()
        if not name:
            continue
        pos = str(p.get("position") or ((p.get("fantasy_positions") or [""])[0]) or "").upper()
        if pos == "DST":
            pos = "DEF"
        out[_master_player_norm(name)] = {
            "name": name,
            "position": pos,
            "team": str(p.get("team") or "").upper(),
            "sleeper_id": str(player_id),
            "status": p.get("status"),
            "active": p.get("active"),
            "age": p.get("age"),
            "years_exp": p.get("years_exp"),
            "college": p.get("college"),
            "number": p.get("number"),
            "injury_status": p.get("injury_status"),
            "depth_chart_position": p.get("depth_chart_position"),
            "depth_chart_order": p.get("depth_chart_order"),
            "depth_chart_source": "Sleeper published depth chart" if p.get("depth_chart_order") else "",
            "fantasy_positions": p.get("fantasy_positions") or [],
            "source_player": "Sleeper",
        }
    return out


def _normalize_team_code(team):
    team = str(team or "").strip().upper()
    aliases = {
        "JAX": "JAC",
        "WSH": "WAS",
        "LA": "LAR",
        "OAK": "LV",
        "SD": "LAC",
        "STL": "LAR",
    }
    return aliases.get(team, team)

def _current_team_from_sleeper(row):
    team = _normalize_team_code(row.get("team"))
    if team:
        return team
    return ""

def _current_team_from_fantasypros(row):
    return _normalize_team_code(
        row.get("team")
        or row.get("team_id")
        or row.get("player_team")
        or row.get("player_team_id")
    )

def _resolve_current_team(sleeper_row=None, fp_row=None, projection_row=None):
    """
    2026 CURRENT TEAM PRIORITY

    1. Sleeper active-player directory current team
    2. FantasyPros current player directory
    3. FantasyPros 2026 projection team
    4. blank/FA

    2025 historical stats are NEVER allowed to overwrite the 2026 team.
    """
    sleeper_row = sleeper_row or {}
    fp_row = fp_row or {}
    projection_row = projection_row or {}

    for candidate in (
        _current_team_from_sleeper(sleeper_row),
        _current_team_from_fantasypros(fp_row),
        _normalize_team_code(projection_row.get("projection_team")),
    ):
        if candidate:
            return candidate

    return "FA"

def _build_master_players_2026():
    warnings = []
    sources = []

    sleeper = {}
    fp_players = {}
    projections = {}
    adp = {}

    # Broad current player/roster directory.
    try:
        sleeper = _sleeper_active_players_2026()
        sources.append(f"Sleeper active NFL players ({len(sleeper)})")
    except Exception as e:
        warnings.append(f"Sleeper players: {e}")

    # FantasyPros current player directory.
    try:
        fp_players = _fp_player_list_2026()
        sources.append(f"FantasyPros NFL players ({len(fp_players)})")
    except Exception as e:
        warnings.append(f"FantasyPros players: {e}")

    # 2026 projections.
    try:
        projections = _fp_projections_2026("PPR")
        sources.append(f"FantasyPros 2026 projections ({len(projections)})")
    except Exception as e:
        warnings.append(f"FantasyPros projections: {e}")

    # 2026 ADP/rank data.
    try:
        adp = _fp_adp_2026("PPR")
        sources.append(f"FantasyPros 2026 ADP ({len(adp)})")
    except Exception as e:
        warnings.append(f"FantasyPros ADP: {e}")

    # Merge every unique player across all current 2026 sources.
    all_keys = set(sleeper) | set(fp_players) | set(projections) | set(adp)
    stats_2025 = _stats_2025_snapshot().get("players", {})
    merged = {}

    for norm in all_keys:
        sleeper_row = dict(sleeper.get(norm) or {})
        fp_row = dict(fp_players.get(norm) or {})
        proj_row = dict(projections.get(norm) or {})
        adp_row = dict(adp.get(norm) or {})

        # Best available current name.
        name = (
            sleeper_row.get("name")
            or fp_row.get("name")
            or norm
        )

        # Current position priority.
        position = (
            sleeper_row.get("position")
            or fp_row.get("position")
            or proj_row.get("projection_position")
            or ""
        )
        position = str(position).upper()
        if position == "DST":
            position = "DEF"

        # IMPORTANT: current team never comes from 2025 stats.
        team = _resolve_current_team(
            sleeper_row=sleeper_row,
            fp_row=fp_row,
            projection_row=proj_row,
        )

        item = {}

        # Start with lower-priority metadata first.
        item.update(fp_row)
        item.update(sleeper_row)

        # Explicitly enforce current fields after merge.
        item["name"] = name
        item["position"] = position
        item["team"] = team
        item["season"] = 2026

        # Projection block.
        if proj_row:
            item.update(proj_row)

        # ADP block.
        if adp_row:
            item.update(adp_row)

        # Historical stats are nested only. They cannot replace top-level team.
        if norm in stats_2025:
            historical = dict(stats_2025[norm])
            historical["historical_team_2025"] = historical.get("team")
            item["stats_2025"] = historical

        # Rookie detection.
        years_exp = item.get("years_exp")
        try:
            item["rookie"] = int(years_exp) == 0
        except Exception:
            item["rookie"] = False

        merged[norm] = item

    fantasy_positions = {"QB", "RB", "WR", "TE", "K", "DEF"}
    clean = {
        norm: p
        for norm, p in merged.items()
        if p.get("name") and p.get("position") in fantasy_positions
    }

    payload = {
        "season": 2026,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(clean),
        "rookie_count": sum(1 for p in clean.values() if p.get("rookie")),
        "sources": sources,
        "warnings": warnings,
        "team_resolution_priority": [
            "Sleeper current player directory",
            "FantasyPros current player directory",
            "FantasyPros 2026 projection team",
        ],
        "players": clean,
    }

    MASTER_PLAYERS_2026_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


@app.get("/player-database-2026")
def player_database_2026_page():
    return page("player_database_2026.html")

@app.post("/api/data/refresh-2026-players")
def refresh_2026_players():
    try:
        payload = _build_master_players_2026()
        return jsonify(
            ok=True,
            count=payload.get("count", 0),
            rookie_count=payload.get("rookie_count", 0),
            updated_at=payload.get("updated_at"),
            sources=payload.get("sources", []),
            warnings=payload.get("warnings", []),
        )
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@app.get("/api/data/2026-players/team-check/<path:player_name>")
def team_check_2026_player(player_name):
    norm = _pr_norm(player_name)
    master = _master_players_2026().get("players", {}).get(norm, {})
    return jsonify(
        ok=bool(master),
        player=player_name,
        current_team=master.get("team"),
        position=master.get("position"),
        rookie=master.get("rookie"),
        sleeper_id=master.get("sleeper_id"),
        fantasypros_id=master.get("fantasypros_id"),
        updated_at=_master_players_2026().get("updated_at"),
    )

@app.get("/api/data/2026-players/status")
def status_2026_players():
    payload = _master_players_2026()
    return jsonify(
        ok=bool(payload.get("players")),
        season=2026,
        count=payload.get("count", 0),
        rookie_count=payload.get("rookie_count", 0),
        updated_at=payload.get("updated_at", ""),
        sources=payload.get("sources", []),
        warnings=payload.get("warnings", []),
        fantasypros_api_configured=bool(os.getenv("FANTASYPROS_API_KEY", "").strip()),
    )

@app.get("/api/data/2026-players")
def list_2026_players():
    payload = _master_players_2026()
    pos = str(request.args.get("position") or "").upper()
    rookies_only = str(request.args.get("rookies") or "").lower() in {"1","true","yes"}
    rows = list(payload.get("players", {}).values())
    if pos:
        rows = [p for p in rows if p.get("position") == pos]
    if rookies_only:
        rows = [p for p in rows if p.get("rookie")]
    rows.sort(key=lambda p: (
        p.get("adp") if isinstance(p.get("adp"), (int,float)) else 9999,
        p.get("name","")
    ))
    return jsonify(ok=True, count=len(rows), players=rows)



# ============================================================
# PLAYER RESEARCH DATA UNIFICATION
# 2026 current team + platform ADP + 2025 stats + 2026 projections
# ============================================================

def _player_research_master_row(player_name):
    try:
        return _master_players_2026().get("players", {}).get(_pr_norm(player_name), {})
    except Exception:
        return {}

def _fp_adp_for_player(player_name, position, scoring="PPR"):
    """
    Return FantasyPros 2026 ADP for one player from a cached position response.
    """
    try:
        payload = _fp_adp_position_data(position, scoring)
        rows = _extract_fp_list(payload, ("players", "rankings", "results", "data"))
        target = _pr_norm(player_name)

        for row in rows:
            name = str(row.get("player_name") or row.get("name") or "").strip()
            if _pr_norm(name) != target:
                continue

            value = row.get("rank_adp")
            if value in (None, ""):
                value = row.get("adp")
            if value in (None, ""):
                value = row.get("rank_ave")

            try:
                adp = float(value)
            except Exception:
                adp = None

            return {
                "adp": adp,
                "position_adp": row.get("pos_rank") or row.get("position_rank") or "",
                "source": "FantasyPros 2026 ADP",
            }
    except Exception:
        pass

    return None


def _player_research_adp(player_name, platform="ESPN", position=None):
    """
    ADP priority:
      1. selected platform's local ADP dataset
      2. 2026 master database
      3. FantasyPros current ADP by position
    """
    platform = str(platform or "ESPN").upper()
    norm = _pr_norm(player_name)

    try:
        pdata = _platform_2026_adp_data(platform)
        row = pdata.get("players", {}).get(norm, {})
        value = row.get("adp")
        if value not in (None, "", 999, 999.0):
            return {
                "adp": float(value),
                "position_adp": row.get("position_adp") or "",
                "source": pdata.get("source") or platform,
            }
    except Exception:
        pass

    master = _player_research_master_row(player_name)
    value = master.get("adp")
    try:
        value = float(value)
    except Exception:
        value = None

    if value is not None and value < 999:
        return {
            "adp": value,
            "position_adp": master.get("adp_position_rank") or "",
            "source": "2026 master database",
        }

    pos = position or master.get("position")
    if pos:
        try:
            fp = _fp_adp_for_player(
                player_name,
                pos,
                "HALF" if platform == "YAHOO" else "PPR",
            )
        except Exception:
            fp = None

        if fp and fp.get("adp") is not None:
            return fp

    return {"adp": 999.0, "position_adp": "", "source": "Unavailable"}


def _player_research_stats_2025(player_name, snapshot=None):
    """
    Return already-saved 2025 stats only.
    Never download or rebuild data during a page request.
    """
    snapshot = snapshot if isinstance(snapshot, dict) else _stats_2025_snapshot()
    players = snapshot.get("players", {}) if isinstance(snapshot, dict) else {}
    return players.get(_pr_norm(player_name), {}) or {}


def _player_research_projection_2026(player_name, position):
    """
    Projection priority:
      1. projection already stored in the 2026 master DB
      2. on-demand FantasyPros preseason projection by position
      3. Gridiron IQ history-based fallback
    """
    master = _player_research_master_row(player_name)
    fp = master.get("projection")

    if isinstance(fp, dict) and fp:
        mapped = {
            "games": 17,
            "position": position,
            "passing_yards": fp.get("pass_yards"),
            "passing_tds": fp.get("pass_tds"),
            "interceptions": fp.get("interceptions"),
            "carries": fp.get("rush_attempts"),
            "rushing_yards": fp.get("rush_yards"),
            "rushing_tds": fp.get("rush_tds"),
            "targets": fp.get("targets"),
            "receptions": fp.get("receptions"),
            "receiving_yards": fp.get("receiving_yards"),
            "receiving_tds": fp.get("receiving_tds"),
            "fantasy_points": fp.get("fantasy_points"),
            "fantasy_points_ppr": fp.get("ppr_points"),
            "method": "FantasyPros 2026 projection",
        }
        if any(v not in (None, "", 0, 0.0) for k, v in mapped.items() if k not in {"games","position","method"}):
            return mapped

    try:
        live = _fp_projection_for_player(player_name, position)
    except Exception:
        live = None

    if live:
        return live

    history = _pr_history(player_name)
    return _pr_projection(history, position)


PLAYER_NEWS_CACHE_DIR = DATA_DIR / "player_news_cache"
# Player news is checked on demand whenever a profile opens. Keep the server
# cache disabled so a newly published transaction or injury is not hidden by
# an earlier empty result.
PLAYER_NEWS_CACHE_TTL = 0

def _news_cache_path(player_name):
    PLAYER_NEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9]+", "_", str(player_name).lower()).strip("_")
    return PLAYER_NEWS_CACHE_DIR / f"{safe}.json"

def _fp_public_get(path, params=None):
    key = str(os.getenv("FANTASYPROS_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("FANTASYPROS_API_KEY is not configured.")

    url = "https://api.fantasypros.com/public/v2/json/" + str(path).lstrip("/")
    response = requests.get(
        url,
        params=params or {},
        headers={
            "x-api-key": key,
            "Accept": "application/json",
            "User-Agent": "GridironIQ/2026",
        },
        timeout=8,
    )
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        raise RuntimeError("FantasyPros returned a non-JSON response.")

def _extract_fp_list(payload, keys):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for inner in keys:
                inner_value = value.get(inner)
                if isinstance(inner_value, list):
                    return inner_value
    return []

def _player_news_matches(row, player_name, player_id=None):
    target = _pr_norm(player_name)
    for key in ("player_name","name","player","title","headline"):
        text = str(row.get(key) or "")
        if target and target in _pr_norm(text):
            return True

    if player_id:
        for key in ("player_id","player_fantasypros_id","fpid"):
            if str(row.get(key) or "") == str(player_id):
                return True
    return False

def _normalize_player_news(row):
    return {
        "title": row.get("title") or row.get("headline") or row.get("news_title") or "Player update",
        "summary": row.get("description") or row.get("summary") or row.get("news") or row.get("note") or "",
        "analysis": row.get("analysis") or row.get("fantasy_analysis") or row.get("impact") or "",
        "published": row.get("published_at") or row.get("published") or row.get("date") or row.get("created_at") or "",
        "source": row.get("source") or row.get("source_name") or "FantasyPros",
        "category": row.get("category") or row.get("type") or "",
        "url": row.get("url") or row.get("source_url") or "",
    }


def _clean_news_text(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text.replace("&nbsp;", " ")).strip()


def _clean_news_title(value, source=""):
    title = _clean_news_text(value) or "Player update"
    suffix = f" - {str(source or '').strip()}"
    if len(suffix) > 3 and title.lower().endswith(suffix.lower()):
        title = title[:-len(suffix)].strip()
    return title


def _summarize_news_item(title, description):
    title = _clean_news_title(title)
    summary = _clean_news_text(description)

    # Google News RSS descriptions often repeat only the headline and source.
    # In that case, the headline itself is the most accurate compact summary.
    if not summary or _pr_norm(summary) in {_pr_norm(title), ""}:
        summary = title
    elif _pr_norm(title) in _pr_norm(summary) and len(summary) < len(title) + 80:
        summary = title

    sentences = re.split(r"(?<=[.!?])\s+", summary)
    compact = " ".join(sentences[:2]).strip()
    if len(compact) > 420:
        compact = compact[:417].rsplit(" ", 1)[0] + "..."
    if compact and compact[-1] not in ".!?":
        compact += "."
    return compact


def _news_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()

def _player_research_news(player_name):
    indexed = _indexed_player_news(player_name)
    cache = _news_cache_path(player_name)
    try:
        if (
            PLAYER_NEWS_CACHE_TTL > 0
            and cache.exists()
            and (time.time() - cache.stat().st_mtime) < PLAYER_NEWS_CACHE_TTL
        ):
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(cached.get("news"), list):
                return cached
    except Exception:
        pass

    target = _pr_norm(player_name)
    news = []
    seen = set()
    warnings = []

    def add_news(item):
        if not isinstance(item, dict):
            return
        source = str(item.get("source") or "Player news").strip()
        title = _clean_news_title(item.get("title") or "Player update", source)
        key = _pr_norm(title)
        if not key or key in seen:
            return
        seen.add(key)
        news.append({
            "title": title,
            "summary": _summarize_news_item(title, item.get("summary")),
            "analysis": _clean_news_text(item.get("analysis")),
            "published": item.get("published") or "",
            "source": source,
            "category": item.get("category") or "NFL",
            "url": str(item.get("url") or "").strip(),
        })

    for article in indexed:
        add_news(article)

    try:
        response = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news",
            params={"limit": 100},
            headers={"User-Agent": "Gridiron-IQ/2026"},
            timeout=(5, 10),
        )
        response.raise_for_status()
        payload = response.json()
        for article in payload.get("articles", []) or []:
            combined = " ".join([str(article.get("headline") or ""), str(article.get("description") or "")])
            if target and target not in _pr_norm(combined):
                continue
            web_link = ((article.get("links") or {}).get("web") or {})
            add_news({
                "title": article.get("headline") or "Player update",
                "summary": article.get("description") or "",
                "analysis": "",
                "published": article.get("published") or article.get("lastModified") or "",
                "source": "ESPN",
                "category": "NFL",
                "url": web_link.get("href") or "",
            })
    except Exception as exc:
        warnings.append(f"ESPN news: {exc}")

    if len(news) < 5:
        try:
            import xml.etree.ElementTree as ET
            response = requests.get(
                "https://news.google.com/rss/search",
                params={"q": f'"{player_name}" NFL when:7d', "hl": "en-US", "gl": "US", "ceid": "US:en"},
                headers={"User-Agent": "Mozilla/5.0 Gridiron-IQ/2026"},
                timeout=(5, 10),
            )
            response.raise_for_status()
            rss_root = ET.fromstring(response.content)
            for item in rss_root.findall("./channel/item")[:12]:
                link = item.findtext("link") or ""
                source_node = item.find("source")
                source_name = source_node.text.strip() if source_node is not None and source_node.text else "Google News"
                add_news({
                    "title": item.findtext("title") or "Player update",
                    "summary": item.findtext("description") or "",
                    "analysis": "",
                    "published": item.findtext("pubDate") or "",
                    "source": source_name,
                    "category": "NFL",
                    "url": link,
                })
                if len(news) >= 10:
                    break
        except Exception as exc:
            warnings.append(f"Google News: {exc}")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
    recent = [item for item in news if not _news_timestamp(item.get("published")) or _news_timestamp(item.get("published")) >= cutoff]
    recent.sort(key=lambda item: _news_timestamp(item.get("published")), reverse=True)
    result = {
        "player": player_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "refresh_minutes": PLAYER_NEWS_CACHE_TTL // 60,
        "news": recent[:10],
        "warnings": warnings[-2:],
        "source": "Live ESPN and Google News search plus saved player updates",
    }
    try:
        cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result


def _player_research_injury(player_name):
    master = _player_research_master_row(player_name)
    fp_id = master.get("fantasypros_id")

    result = {
        "status": master.get("injury_status") or "",
        "body_part": master.get("injury_body_part") or "",
        "practice": master.get("practice_participation") or "",
        "description": "",
        "updated_at": "",
        "source": "2026 master player database",
    }

    try:
        params = {"season": 2026}
        if fp_id:
            params["player_id"] = fp_id

        payload = _fp_public_get("nfl/injuries", params=params)
        rows = _extract_fp_list(payload, ("injuries","players","results","data"))
        for row in rows:
            if not _player_news_matches(row, player_name, fp_id):
                continue
            result = {
                "status": row.get("injury_status") or row.get("status") or row.get("designation") or result["status"],
                "body_part": row.get("injury_body_part") or row.get("body_part") or row.get("injury") or result["body_part"],
                "practice": row.get("practice_status") or row.get("practice_participation") or row.get("practice") or result["practice"],
                "description": row.get("description") or row.get("note") or "",
                "updated_at": row.get("updated_at") or row.get("date") or "",
                "source": "FantasyPros injuries",
            }
            break
    except Exception:
        pass

    return result

@app.get("/api/player-research/news/<path:player_name>")
def player_research_news_api(player_name):
    response = jsonify(ok=True, **_player_research_news(player_name))
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response

def _player_research_data_status(platform="ESPN"):
    platform = str(platform or "ESPN").upper()
    master = _master_players_2026()
    stats = _stats_2025_snapshot()
    adp = _platform_2026_adp_data(platform)
    daily = _player_daily_refresh_status()
    news_index = _player_news_index()

    projection_count = sum(
        1 for p in master.get("players", {}).values()
        if isinstance(p.get("projection"), dict) and p.get("projection")
    )
    adp_count = 0
    for p in adp.get("players", {}).values():
        try:
            if float(p.get("adp", 999)) < 999:
                adp_count += 1
        except Exception:
            pass

    return {
        "platform": platform,
        "master_player_count": len(master.get("players", {})),
        "stats_2025_count": len(stats.get("players", {})),
        "projection_2026_count": projection_count,
        "platform_adp_count": adp_count,
        "fantasypros_api_configured": bool(os.getenv("FANTASYPROS_API_KEY", "").strip()),
        "nflverse_stats_url": (NFLVERSE_2025_STATS_URLS[0] if NFLVERSE_2025_STATS_URLS else None),
        "data_directory": str(DATA_DIR),
        "persistent_data_configured": bool(os.getenv("GRIDIRON_DATA_DIR", "").strip()),
        "fantasypros_base": "https://api.fantasypros.com/public/v2/json",
        "daily_player_refresh_enabled": True,
        "daily_player_refresh_checked_at": daily.get("checked_at", ""),
        "daily_player_refresh_source": daily.get("source", ""),
        "daily_player_refresh_count": daily.get("player_count", 0),
        "daily_player_refresh_fresh": _player_daily_refresh_is_fresh(),
        "recent_news_player_count": len(news_index.get("players", {})),
        "recent_news_updated_at": news_index.get("updated_at", ""),
        "recent_news_window_hours": news_index.get("window_hours", 72),
    }


@app.get("/api/player-research/data-status")
def player_research_data_status_api():
    platform = str(request.args.get("platform") or _league_platform()).upper()
    return jsonify(ok=True, **_player_research_data_status(platform))


@app.get("/player-analytics")
def player_analytics():
    # Keep the existing dashboard/navigation link working while the new page
    # also remains available at its descriptive /offensive-stats URL.
    return redirect(url_for("offensive_stats_page"))


@app.get("/player-research")
def player_research():
    selected_position = request.args.get("position", "").strip().upper()
    if selected_position not in {"", "QB", "RB", "WR", "TE", "K", "DEF"}:
        selected_position = ""

    league_key = (
        request.args.get("league")
        or session.get("active_league_key")
        or "espn-gramps"
    )
    if league_key not in CONTEXTS:
        league_key = "espn-gramps"

    session["active_league_key"] = league_key
    context = CONTEXTS[league_key]
    platform = (
        "YAHOO"
        if "YAHOO" in str(context.get("platform", "")).upper()
        else "ESPN"
    )
    daily_refresh = _player_daily_refresh_status()

    return page(
        "player_research.html",
        selected_position=selected_position,
        draft_leagues=draft_leagues(),
        active_league_key=league_key,
        active_platform=platform,
        active_scoring=context.get("scoring", ""),
        daily_refresh=daily_refresh,
        daily_refresh_fresh=_player_daily_refresh_is_fresh(),
    )



@app.get("/api/player-research/table")
def player_research_table_api():
    position = request.args.get("position", "").strip().upper()
    if position not in {"", "QB", "RB", "WR", "TE", "K", "DEF"}:
        return jsonify(ok=False, error="Unsupported position."), 400

    platform = str(request.args.get("platform") or _league_platform()).upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    query = request.args.get("q", "").strip().lower()
    sort_by = request.args.get("sort", "adp").strip().lower()
    direction = request.args.get("direction", "asc").strip().lower()

    try:
        page = max(1, int(request.args.get("page", 1)))
    except Exception:
        page = 1

    try:
        page_size = min(250, max(25, int(request.args.get("page_size", 200))))
    except Exception:
        page_size = 200

    all_rows = _pr_position_rows("", limit=5000, platform=platform)

    position_counts = dict(Counter(
        row.get("position")
        for row in all_rows
        if row.get("position")
    ))

    rows = (
        [row for row in all_rows if row.get("position") == position]
        if position
        else list(all_rows)
    )

    if query:
        rows = [
            row for row in rows
            if query in str(row.get("name", "")).lower()
            or query in str(row.get("team", "")).lower()
            or query in str(row.get("position", "")).lower()
        ]

    sort_fields = {
        "name": "name",
        "team": "team",
        "position": "position",
        "adp": "adp",
        "position_adp": "position_adp",
        "points_2025": "fantasy_points_ppr",
        "projection_2026": "proj_2026_ppr",
        "games": "games",
    }
    field = sort_fields.get(sort_by, "adp")
    reverse = direction == "desc"

    def value_for_sort(row):
        value = row.get(field)
        if field in {"name", "team", "position", "position_adp"}:
            return str(value or "").lower()
        try:
            number = float(value)
            return 999999.0 if field == "adp" and number >= 999 else number
        except Exception:
            return 999999.0

    rows.sort(key=value_for_sort, reverse=reverse)

    total_count = len(rows)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    page = min(page, total_pages)
    start_index = (page - 1) * page_size
    page_rows = rows[start_index:start_index + page_size]

    stats = _stats_2025_snapshot()
    adp = _platform_2026_adp_data(platform)
    master = _master_players_2026()
    daily = _player_daily_refresh_status()
    news_index = _player_news_index()

    return jsonify(
        ok=True,
        platform=platform,
        selected_position=position or "ALL",
        count=total_count,
        returned_count=len(page_rows),
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        position_counts=position_counts,
        players=page_rows,
        sources={
            "stats_2025": stats.get("source", ""),
            "projections_2026": "2026 source projections or Gridiron IQ fallback",
            "adp_2026": adp.get("source", ""),
            "current_players": daily.get("source") or "Sleeper current player directory",
            "recent_news": news_index.get("source") or "Daily player news index",
        },
        updated_at={
            "stats_2025": stats.get("updated_at", ""),
            "adp_2026": adp.get("updated_at", ""),
            "current_players": daily.get("checked_at") or master.get("updated_at", ""),
            "recent_news": news_index.get("updated_at", ""),
        },
        warnings=[],
    )

@app.get("/api/diagnostics/player-research")
def diagnostics_player_research():
    platform = _league_platform()
    directory = _pr_players()
    stats = _stats_2025_snapshot()
    adp = _platform_2026_adp_data(platform)
    daily = _player_daily_refresh_status()
    return jsonify(
        ok=bool(directory),
        fast_mode=True,
        player_directory_count=len(directory),
        stats_2025_count=len(stats.get("players", {})),
        adp_player_count=len(adp.get("players", {})),
        platform=platform,
        adp_source=adp.get("source"),
        note="Player Research no longer parses historical CSV files during page load.",
        daily_refresh_enabled=True,
        daily_refresh_checked_at=daily.get("checked_at", ""),
        daily_refresh_fresh=_player_daily_refresh_is_fresh(),
    )


@app.get("/api/diagnostics/mock-draft")
def diagnostics_mock_draft():
    key = request.args.get("league") or "espn-gramps"
    context = dict(CONTEXTS.get(key, CONTEXTS["espn-gramps"]))
    pool = _build_dynamic_mock_pool(context)
    counts = Counter(p.get("pos") for p in pool)
    return jsonify(
        ok=len(pool) >= int(context.get("teams",12)) * 10,
        league=key,
        platform=context.get("platform"),
        teams=context.get("teams"),
        player_pool_count=len(pool),
        position_counts=dict(counts),
    )

@app.get("/api/player-research/search")
def player_research_search():
    q = request.args.get("q", "").strip()
    return jsonify(ok=True, players=_pr_search(q) if len(q) >= 2 else [])



ESPN_NATIVE_ADP_FILE = DATA_DIR / "espn_native_adp_2026.json"

def _save_espn_native_adp(payload):
    ESPN_NATIVE_ADP_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def _load_espn_native_adp():
    try:
        if ESPN_NATIVE_ADP_FILE.exists():
            data = json.loads(ESPN_NATIVE_ADP_FILE.read_text(encoding="utf-8"))
            if data.get("players"):
                return data
    except Exception:
        pass
    return None

def _fetch_espn_native_adp(league_id=None, season=2026, swid=None, espn_s2=None):
    """
    Pull ESPN's own PPR Average Draft Position from ESPN Fantasy's
    default PPR player pool (leaguedefaults/3).

    This endpoint is better for market ADP than the private-league endpoint.
    Cookies are optional; they are used only as a fallback if ESPN requires them.
    """
    season = int(season or 2026)

    urls = []

    # When the user has synced ESPN successfully, use the authenticated league
    # endpoint first. It is substantially more reliable than anonymous access.
    if league_id and swid and espn_s2:
        urls.extend([
            f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{int(league_id)}?view=kona_player_info",
            f"https://fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{int(league_id)}?view=kona_player_info",
        ])

    urls.extend([
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3?view=kona_player_info",
        f"https://fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3?view=kona_player_info",
    ])

    fantasy_filter = {
        "players": {
            "limit": 2000,
            "filterActive": {"value": True},
            "sortPercOwned": {
                "sortPriority": 4,
                "sortAsc": False
            },
            "sortDraftRanks": {
                "sortPriority": 100,
                "sortAsc": True,
                "value": "PPR"
            }
        }
    }

    headers = {
        "Accept": "application/json",
        "X-Fantasy-Filter": json.dumps(fantasy_filter),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36",
    }

    cookies = {}
    if swid:
        cookies["SWID"] = str(swid).strip()
    if espn_s2:
        cookies["espn_s2"] = str(espn_s2).strip()

    errors = []

    for url in urls:
        try:
            response = requests.get(
                url,
                headers=headers,
                cookies=cookies or None,
                timeout=35
            )
            response.raise_for_status()

            content_type = str(response.headers.get("content-type") or "").lower()
            body_preview = response.text[:160].strip()

            if "json" not in content_type:
                raise RuntimeError(
                    "ESPN returned non-JSON content"
                    + (f" ({content_type})" if content_type else "")
                    + (f": {body_preview}" if body_preview else "")
                )

            try:
                payload = response.json()
            except Exception as exc:
                raise RuntimeError(
                    f"ESPN returned invalid JSON: {exc}"
                ) from exc

            if not isinstance(payload, dict):
                raise RuntimeError("ESPN returned an unexpected response format.")

            wrappers = payload.get("players") or []
            players = {}

            for wrapper in wrappers:
                p = wrapper.get("player") or wrapper
                name = str(p.get("fullName") or "").strip()
                if not name:
                    continue

                ownership = p.get("ownership") or {}
                adp = ownership.get("averageDraftPosition")

                # Some ESPN payloads expose ADP on the wrapper.
                if adp in (None, ""):
                    adp = (wrapper.get("ownership") or {}).get("averageDraftPosition")

                rank = None
                rank_sets = p.get("draftRanksByRankType") or {}
                for rank_key in ("PPR", "STANDARD"):
                    rank_info = rank_sets.get(rank_key) or {}
                    if rank_info.get("rank") is not None:
                        try:
                            rank = int(rank_info["rank"])
                        except Exception:
                            rank = None
                        break

                if adp in (None, ""):
                    adp = rank

                if adp in (None, ""):
                    continue

                try:
                    adp = round(float(adp), 2)
                except Exception:
                    continue

                position_map = {
                    1: "QB",
                    2: "RB",
                    3: "WR",
                    4: "TE",
                    5: "K",
                    16: "DEF",
                }
                try:
                    position_id = int(p.get("defaultPositionId") or 0)
                except Exception:
                    position_id = 0

                position = position_map.get(position_id, "")
                team = str(
                    p.get("proTeamAbbreviation")
                    or p.get("team")
                    or ""
                ).upper()

                players[_pr_norm(name)] = {
                    "name": name,
                    "adp": adp,
                    "rank": rank,
                    "position": position,
                    "team": team,
                    "position_adp": "",
                    "source": "ESPN",
                }

            if players:
                by_position = defaultdict(list)
                for norm_key, item in players.items():
                    pos_key = str(item.get("position") or "").upper()
                    if pos_key in {"QB", "RB", "WR", "TE", "K", "DEF"}:
                        by_position[pos_key].append(
                            (float(item.get("adp", 999)), norm_key)
                        )
                for pos_key, ranked in by_position.items():
                    ranked.sort(key=lambda pair: (pair[0], pair[1]))
                    for pos_number, (_, norm_key) in enumerate(ranked, start=1):
                        players[norm_key]["position_adp"] = (
                            f"{pos_key}{pos_number}"
                        )

                result = {
                    "season": season,
                    "platform": "ESPN",
                    "scoring": "PPR",
                    "source": "ESPN native PPR fantasy ADP",
                    "source_url": url,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "live",
                    "players": players,
                }
                _save_espn_native_adp(result)
                return result

            errors.append(f"{url}: ESPN returned {len(wrappers)} players but none had averageDraftPosition.")
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError(" | ".join(errors) or "ESPN ADP request returned no usable players.")

ADP_2026_CACHE_TTL = 6 * 60 * 60
ADP_2026_SOURCES = {
    "ESPN": {
        "url": "https://www.fantasypros.com/nfl/adp/ppr-overall.php",
        "column": "ESPN",
        "scoring": "PPR",
    },
    "YAHOO": {
        "url": "https://www.fantasypros.com/nfl/adp/half-point-ppr-overall.php",
        "column": "Yahoo",
        "scoring": "Half PPR",
    },
}

class _ADPTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tr = False
        self.in_cell = False
        self.cell_text = []
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.in_tr = True
            self.row = []
        elif self.in_tr and tag in ("td", "th"):
            self.in_cell = True
            self.cell_text = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text.append(data)

    def handle_endtag(self, tag):
        if self.in_tr and tag in ("td", "th") and self.in_cell:
            self.row.append(" ".join("".join(self.cell_text).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_tr:
            if self.row:
                self.rows.append(self.row)
            self.in_tr = False

def _adp_player_name(raw_player):
    raw_player = str(raw_player or "").strip()
    if not raw_player:
        return ""

    m = re.match(
        r"^(.+?)\s+[A-Z]\.\s+[A-Za-z'’\-\s]+?\s+[A-Z]{2,3}\s+\(\d+\)",
        raw_player
    )
    if m:
        return m.group(1).strip()

    cleaned = re.sub(r"\s+[A-Z]{2,3}\s+\(\d+\)\s*$", "", raw_player).strip()
    m2 = re.match(r"^(.+?)\s+[A-Z]\.\s+[A-Za-z'’\-]+(?:\s+(?:Jr\.|Sr\.|II|III|IV))?$", cleaned)
    return m2.group(1).strip() if m2 else cleaned

def _parse_platform_adp(html, platform):
    platform = str(platform or "ESPN").upper()
    wanted = ADP_2026_SOURCES.get(platform, ADP_2026_SOURCES["ESPN"])["column"].lower()

    parser = _ADPTableParser()
    parser.feed(html)

    header = None
    for row in parser.rows:
        lower = [str(c).strip().lower() for c in row]
        if any("player" in c for c in lower) and wanted in lower:
            header = lower
            break

    if not header:
        return {}

    player_idx = next((i for i,c in enumerate(header) if "player" in c), None)
    platform_idx = next((i for i,c in enumerate(header) if c == wanted), None)
    pos_idx = next((i for i,c in enumerate(header) if c == "pos"), None)

    if player_idx is None or platform_idx is None:
        return {}

    result = {}
    for row in parser.rows:
        if len(row) <= max(player_idx, platform_idx):
            continue

        name = _adp_player_name(row[player_idx])
        if not name:
            continue

        try:
            adp = float(str(row[platform_idx]).replace("#", "").strip())
        except Exception:
            continue

        result[_pr_norm(name)] = {
            "adp": round(adp, 1),
            "position_adp": row[pos_idx] if pos_idx is not None and len(row) > pos_idx else "",
            "source": platform,
        }

    return result



class _SimpleHtmlTableParser(HTMLParser):
    """Small dependency-free HTML table parser for public ADP pages."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._cell_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = tag
            self._cell_parts = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"th", "td"} and self._cell is not None:
            value = re.sub(r"\s+", " ", " ".join(self._cell_parts)).strip()
            self._row.append(value)
            self._cell = None
            self._cell_parts = []
        elif tag == "tr" and self._row is not None:
            if any(str(value).strip() for value in self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def _clean_public_player_name(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\b[A-Z]\.\s+(?=[A-Z][a-z])", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _parse_public_adp_number(value):
    text = str(value or "").strip()
    if text in {"", "-", "—", "–", "NR", "N/A"}:
        return None

    # Round/pick formats such as 1.03 are still valid draft-position values.
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        return None


def _fourforfour_platform_adp_dataset(platform):
    """
    Parse 4for4's public cross-platform ADP table.

    The table includes columns for ESPN and Yahoo as well as a consensus ADP.
    No FantasyPros API key is required.
    """
    platform = str(platform or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    response = requests.get(
        "https://www.4for4.com/adp",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150 Safari/537.36"
            ),
        },
        timeout=(8, 30),
        allow_redirects=True,
    )
    response.raise_for_status()

    content_type = str(response.headers.get("content-type") or "").lower()
    if "html" not in content_type and "<table" not in response.text.lower():
        raise RuntimeError(
            f"4for4 returned non-table content ({content_type or 'unknown type'})."
        )

    parser = _SimpleHtmlTableParser()
    parser.feed(response.text)

    selected_table = None
    header_index = None
    header = None

    for table in parser.tables:
        for index, row in enumerate(table[:8]):
            normalized = [re.sub(r"\s+", " ", cell).strip().upper() for cell in row]
            has_player = any(cell == "PLAYER" or cell.startswith("PLAYER ") for cell in normalized)
            has_platform = (
                any(cell == "ESPN" for cell in normalized)
                if platform == "ESPN"
                else any(cell in {"Y!", "YAHOO", "YAHOO!"} for cell in normalized)
            )
            if has_player and has_platform:
                selected_table = table
                header_index = index
                header = normalized
                break
        if selected_table is not None:
            break

    if selected_table is None or header is None:
        raise RuntimeError("The public 4for4 ADP table could not be identified.")

    def find_column(*names):
        for name in names:
            for index, value in enumerate(header):
                if value == name or value.startswith(name + " "):
                    return index
        return None

    player_col = find_column("PLAYER")
    position_col = find_column("POSITION", "POS")
    team_col = find_column("TEAM")
    consensus_col = find_column("ADP", "AVG")
    platform_col = (
        find_column("ESPN")
        if platform == "ESPN"
        else find_column("Y!", "YAHOO", "YAHOO!")
    )

    if player_col is None or platform_col is None:
        raise RuntimeError("Required player or platform ADP columns were missing.")

    players = {}

    for row in selected_table[header_index + 1:]:
        if len(row) <= max(player_col, platform_col):
            continue

        name = _clean_public_player_name(row[player_col])
        if not name or name.upper() == "PLAYER":
            continue

        platform_adp = _parse_public_adp_number(row[platform_col])
        consensus_adp = (
            _parse_public_adp_number(row[consensus_col])
            if consensus_col is not None and len(row) > consensus_col
            else None
        )

        # Prefer the platform-specific value. Use consensus only when the
        # platform has no value so the player does not incorrectly display NR.
        adp = platform_adp if platform_adp is not None else consensus_adp
        if adp is None:
            continue

        position_text = (
            str(row[position_col]).strip().upper()
            if position_col is not None and len(row) > position_col
            else ""
        )
        position_match = re.match(r"(QB|RB|WR|TE|K|DST|DEF)(?:[-\s]?(\d+))?", position_text)
        position = ""
        position_adp = ""

        if position_match:
            position = position_match.group(1)
            if position == "DST":
                position = "DEF"
            if position_match.group(2):
                position_adp = f"{position}{position_match.group(2)}"

        team = (
            str(row[team_col]).strip().upper()
            if team_col is not None and len(row) > team_col
            else ""
        )

        players[_pr_norm(name)] = {
            "name": name,
            "adp": round(float(adp), 2),
            "platform_adp": platform_adp,
            "consensus_adp": consensus_adp,
            "position": position,
            "position_adp": position_adp,
            "team": team,
            "source": f"4for4 public {platform} ADP",
        }

    if len(players) < 50:
        raise RuntimeError(
            f"The public 4for4 table returned only {len(players)} usable players."
        )

    # Complete missing positional ranks.
    by_position = defaultdict(list)
    for norm, item in players.items():
        position = str(item.get("position") or "").upper()
        if position in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            by_position[position].append(
                (float(item.get("adp", 999) or 999), norm)
            )

    for position, ranked in by_position.items():
        ranked.sort(key=lambda pair: (pair[0], pair[1]))
        for number, (_, norm) in enumerate(ranked, start=1):
            if not players[norm].get("position_adp"):
                players[norm]["position_adp"] = f"{position}{number}"

    payload = {
        "season": 2026,
        "platform": platform,
        "scoring": "PPR" if platform == "ESPN" else "Half PPR",
        "source": f"4for4 public webpage — {platform} ADP",
        "source_url": "https://www.4for4.com/adp",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "public",
        "players": players,
    }

    path = _local_platform_adp_path(platform)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)
    return payload


def _public_platform_adp_dataset(platform):
    """
    Load the public FantasyPros ADP table without an API key.

    The public page exposes platform columns such as ESPN and Yahoo. This is
    used when the restricted FantasyPros JSON API returns 403.
    """
    platform = str(platform or "ESPN").upper()
    if platform not in ADP_2026_SOURCES:
        platform = "ESPN"

    source = ADP_2026_SOURCES[platform]
    response = requests.get(
        source["url"],
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150 Safari/537.36"
            ),
        },
        timeout=(8, 30),
    )
    response.raise_for_status()

    players = _parse_platform_adp(response.text, platform)
    if not players:
        raise RuntimeError(
            f"The public FantasyPros {platform} ADP table returned no usable rows."
        )

    # Fill position/team from the current Sleeper directory.
    directory_by_name = {}
    try:
        for player_id, row in _pr_players().items():
            if not isinstance(row, dict):
                continue
            name = str(
                row.get("full_name")
                or " ".join(
                    value for value in [
                        row.get("first_name"),
                        row.get("last_name"),
                    ] if value
                )
            ).strip()
            if not name:
                continue
            position = str(
                row.get("position")
                or ((row.get("fantasy_positions") or [""])[0])
                or ""
            ).upper()
            if position == "DST":
                position = "DEF"
            directory_by_name[_pr_norm(name)] = {
                "position": position,
                "team": str(row.get("team") or "").upper(),
                "player_id": str(player_id),
            }
    except Exception:
        directory_by_name = {}

    for norm, item in players.items():
        current = directory_by_name.get(norm, {})
        item.setdefault("name", "")
        item["position"] = item.get("position") or current.get("position") or ""
        item["team"] = item.get("team") or current.get("team") or ""
        item["player_id"] = current.get("player_id") or ""
        item["source"] = f"FantasyPros public {platform} ADP"

    # Calculate positional ranks when the page does not supply them.
    by_position = defaultdict(list)
    for norm, item in players.items():
        position = str(item.get("position") or "").upper()
        if position in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            by_position[position].append(
                (float(item.get("adp", 999) or 999), norm)
            )

    for position, ranked in by_position.items():
        ranked.sort(key=lambda pair: (pair[0], pair[1]))
        for number, (_, norm) in enumerate(ranked, start=1):
            if not players[norm].get("position_adp"):
                players[norm]["position_adp"] = f"{position}{number}"

    payload = {
        "season": 2026,
        "platform": platform,
        "scoring": source["scoring"],
        "source": f"FantasyPros public webpage — {platform} ADP",
        "source_url": source["url"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "public",
        "players": players,
    }

    path = _local_platform_adp_path(platform)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)
    return payload


def _adp_cache_file(platform):
    return DATA_DIR / f"adp_2026_{str(platform).lower()}_cache.json"

FANTASYPROS_API_BASE = "https://api.fantasypros.com/public/v2/json"
FANTASYPROS_API_KEY_ENV = "FANTASYPROS_API_KEY"

def _local_platform_adp_path(platform):
    platform = str(platform or "ESPN").upper()
    filename = "espn_adp_2026.json" if platform == "ESPN" else "yahoo_adp_2026.json"
    return DATA_DIR / filename

def _fp_api_key():
    return str(os.getenv(FANTASYPROS_API_KEY_ENV, "") or "").strip()

def _fp_get(path, params=None):
    api_key = _fp_api_key()
    if not api_key:
        raise RuntimeError(
            "FANTASYPROS_API_KEY is not set in Render. Add it under Environment and redeploy."
        )

    url = f"{FANTASYPROS_API_BASE}/{str(path).lstrip('/')}"
    response = requests.get(
        url,
        params=params or {},
        headers={
            "x-api-key": api_key,
            "Accept": "application/json",
            "User-Agent": "GridironIQ/2026",
        },
        timeout=35,
    )

    if response.status_code in (401, 403):
        raise RuntimeError(
            f"FantasyPros API rejected the key ({response.status_code}). "
            "Confirm FANTASYPROS_API_KEY and that the key has access to this endpoint."
        )
    response.raise_for_status()

    try:
        return response.json()
    except Exception:
        raise RuntimeError(
            f"FantasyPros API returned non-JSON content ({response.status_code})."
        )

def _fp_player_rows(payload):
    """
    Tolerate common FantasyPros response envelopes without hard-coding a single
    response shape. The official API examples use a top-level players array.
    """
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    for key in ("players", "rankings", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for inner in ("players", "rankings", "results"):
                rows = value.get(inner)
                if isinstance(rows, list):
                    return rows
    return []

def _fp_first(row, *keys):
    for key in keys:
        value = row.get(key) if isinstance(row, dict) else None
        if value not in (None, ""):
            return value
    return None

def _fp_float(value):
    if value in (None, "", "-", "—"):
        return None
    try:
        return float(value)
    except Exception:
        return None

def _fp_int(value):
    number = _fp_float(value)
    return int(number) if number is not None else None

def _fp_name(row):
    return str(_fp_first(
        row, "player_name", "name", "full_name", "playerName"
    ) or "").strip()

def _fp_position(row):
    return str(_fp_first(
        row, "player_position_id", "position", "pos", "player_position"
    ) or "").upper().strip()

def _fp_team(row):
    return str(_fp_first(
        row, "player_team_id", "team", "team_id", "player_team"
    ) or "").upper().strip()

def _fp_consensus_rankings(scoring="PPR", position="ALL"):
    params = {"scoring": scoring}
    if position and position != "ALL":
        params["position"] = position

    return _fp_get(
        "nfl/2026/consensus-rankings",
        params=params,
    )

def _fp_players():
    return _fp_get("nfl/players")

def _fp_projections(position=None):
    params = {}
    if position and position != "ALL":
        params["position"] = position
    return _fp_get("nfl/2026/projections", params=params)

def _fp_extract_adp(row, platform):
    """
    Prefer an explicit platform ADP field when the API supplies one.
    Fall back to generic ADP only if the row identifies that platform/source.
    """
    platform = str(platform or "ESPN").upper()
    aliases = {
        "ESPN": (
            "adp_espn", "espn_adp", "adpEspn", "adp_espn_ppr",
            "rank_adp_espn", "espn"
        ),
        "YAHOO": (
            "adp_yahoo", "yahoo_adp", "adpYahoo", "adp_yahoo_half_ppr",
            "rank_adp_yahoo", "yahoo"
        ),
    }

    for key in aliases.get(platform, ()):
        value = _fp_float(row.get(key)) if isinstance(row, dict) else None
        if value is not None:
            return value

    source = str(_fp_first(
        row, "adp_source", "source", "platform", "league_host"
    ) or "").upper()
    if platform in source:
        for key in ("adp", "average_draft_position", "rank_adp"):
            value = _fp_float(row.get(key)) if isinstance(row, dict) else None
            if value is not None:
                return value

    return None

def _fp_position_adp(row, platform, position):
    platform = str(platform or "ESPN").upper()
    aliases = {
        "ESPN": ("position_adp_espn", "espn_position_adp", "pos_adp_espn"),
        "YAHOO": ("position_adp_yahoo", "yahoo_position_adp", "pos_adp_yahoo"),
    }
    for key in aliases.get(platform, ()):
        value = _fp_first(row, key)
        if value not in (None, ""):
            text = str(value).strip()
            return text if any(ch.isalpha() for ch in text) else f"{position}{text}"
    return ""

def _fp_projection_map():
    """
    Pull 2026 projections and normalize them by player name.
    Projection fields are preserved so Player Research can consume them as the
    UI grows; missing fields simply remain absent.
    """
    result = {}
    for position in ("QB", "RB", "WR", "TE", "K", "DST"):
        try:
            payload = _fp_projections(position)
        except Exception:
            continue
        for row in _fp_player_rows(payload):
            name = _fp_name(row)
            if not name:
                continue
            result[_pr_norm(name)] = row
    return result

def _fp_build_platform_dataset(platform):
    platform = str(platform or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    scoring = "PPR" if platform == "ESPN" else "HALF"
    projection_map = _fp_projection_map()

    merged = {}
    errors = []

    # Pull by position so the integration can populate the complete draftable pool.
    for position in ("QB", "RB", "WR", "TE", "K", "DST"):
        try:
            payload = _fp_consensus_rankings(scoring=scoring, position=position)
            rows = _fp_player_rows(payload)
        except Exception as exc:
            errors.append(f"{position}: {exc}")
            continue

        for row in rows:
            name = _fp_name(row)
            if not name:
                continue

            pos = _fp_position(row) or position
            if pos == "DST":
                app_pos = "DEF"
            else:
                app_pos = pos

            adp = _fp_extract_adp(row, platform)
            norm = _pr_norm(name)

            # Keep rankings/projections even when the API doesn't expose a
            # platform-specific ADP field for that player.
            item = {
                "name": name,
                "position": app_pos,
                "team": _fp_team(row),
                "adp": adp if adp is not None else 999.0,
                "position_adp": _fp_position_adp(row, platform, app_pos),
                "ecr": _fp_int(_fp_first(row, "rank_ecr", "ecr", "rank")),
                "tier": _fp_int(_fp_first(row, "tier", "rank_tier")),
                "best_rank": _fp_int(_fp_first(row, "rank_min", "best_rank")),
                "worst_rank": _fp_int(_fp_first(row, "rank_max", "worst_rank")),
                "source": f"FantasyPros {platform}",
            }

            projection = projection_map.get(norm)
            if isinstance(projection, dict):
                item["projection_2026"] = projection

            merged[norm] = item

    if not merged:
        raise RuntimeError(
            "FantasyPros returned no usable NFL ranking rows. " + " | ".join(errors)
        )

    payload = {
        "season": 2026,
        "platform": platform,
        "scoring": "PPR" if platform == "ESPN" else "Half PPR",
        "source": f"FantasyPros API — {platform} 2026 platform dataset",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "api",
        "players": merged,
        "warnings": errors,
    }

    # Durable local cache/fallback.
    path = _local_platform_adp_path(platform)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload

def _platform_2026_adp_data(platform="ESPN", force=False):
    """
    Load 2026 ADP in this order:
      1. complete saved dataset
      2. ESPN native ADP for ESPN
      3. public FantasyPros platform ADP webpage
      4. restricted FantasyPros API when available
      5. last successful saved dataset
    """
    platform = str(platform or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    path = _local_platform_adp_path(platform)
    cached = None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("players"):
            cached = payload
            players = payload.get("players", {})
            ranked_count = sum(
                1 for item in players.values()
                if float(item.get("adp", 999) or 999) < 999
            )
            has_position_data = any(
                str(item.get("position") or "").upper()
                in {"QB", "RB", "WR", "TE", "K", "DEF"}
                for item in players.values()
            )
            if not force and ranked_count >= 75 and has_position_data:
                payload["status"] = payload.get("status") or "local"
                return payload
    except Exception:
        cached = None

    errors = []

    if platform == "ESPN":
        try:
            native = _fetch_espn_native_adp(season=2026)
            if native.get("players"):
                path.write_text(
                    json.dumps(native, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return native
        except Exception as exc:
            errors.append(f"ESPN native: {exc}")

        try:
            native_cached = _load_espn_native_adp()
            if native_cached and native_cached.get("players"):
                players = native_cached.get("players", {})
                ranked_count = sum(
                    1 for item in players.values()
                    if float(item.get("adp", 999) or 999) < 999
                )
                if ranked_count >= 75:
                    native_cached["status"] = "cached"
                    native_cached["warning"] = (
                        "Live ESPN refresh was unavailable; using saved ESPN ADP."
                    )
                    path.write_text(
                        json.dumps(native_cached, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    return native_cached
        except Exception as exc:
            errors.append(f"ESPN saved data: {exc}")

    # Public cross-platform table with explicit ESPN and Yahoo columns.
    try:
        return _fourforfour_platform_adp_dataset(platform)
    except Exception as exc:
        errors.append(f"4for4 public ADP: {exc}")

    # Secondary public webpage source.
    try:
        return _public_platform_adp_dataset(platform)
    except Exception as exc:
        errors.append(f"FantasyPros public ADP: {exc}")

    # Do not repeatedly call a restricted FantasyPros endpoint after a 403.
    # The public sources above are preferred and require no API subscription.

    if cached and cached.get("players"):
        cached["status"] = "cached"
        cached["warning"] = (
            "Live ADP refresh was unavailable. The last saved ADP is being used."
        )
        return cached

    return {
        "season": 2026,
        "platform": platform,
        "scoring": "PPR" if platform == "ESPN" else "Half PPR",
        "source": "No live ADP source available",
        "updated_at": "",
        "players": {},
        "status": "unavailable",
        "warning": (
            "The live ADP sources are temporarily unavailable. "
            "Try refreshing again later."
        ),
        "diagnostic_errors": errors[-3:],
    }


def _fp_api_status():
    return {
        "configured": bool(_fp_api_key()),
        "environment_variable": FANTASYPROS_API_KEY_ENV,
    }

def _league_platform(league_key=None):
    key = league_key or request.args.get("league") or session.get("active_league_key") or "espn-gramps"
    context = CONTEXTS.get(key, CONTEXTS.get("espn-gramps", {}))
    platform = str(context.get("platform") or "ESPN").upper()
    return "YAHOO" if "YAHOO" in platform else "ESPN"

def _pr_adp_lookup(platform="ESPN"):
    data = _platform_2026_adp_data(platform)
    return {
        key: float(value.get("adp", 999.0))
        for key, value in data.get("players", {}).items()
    }


def _fast_2026_projection_from_2025(stats, position):
    """Create a complete 2026 projection from an in-memory 2025 record."""
    stats = stats or {}
    position = str(position or "").upper()

    def number(key):
        try:
            return float(stats.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    multipliers = {
        "QB": 1.01,
        "RB": 0.98,
        "WR": 1.01,
        "TE": 1.02,
        "K": 1.00,
        "DEF": 1.00,
    }
    factor = multipliers.get(position, 1.00)

    projected = {
        "games": 17,
        "completions": round(number("completions") * factor),
        "attempts": round(number("attempts") * factor),
        "passing_yards": round(number("passing_yards") * factor),
        "passing_tds": round(number("passing_tds") * factor, 1),
        "interceptions": round(number("interceptions") * factor, 1),
        "sacks_suffered": round(number("sacks_suffered") * factor),
        "passing_air_yards": round(number("passing_air_yards") * factor),
        "passing_first_downs": round(number("passing_first_downs") * factor),
        "passing_epa": round(number("passing_epa") * factor, 2),
        "passing_cpoe": round(number("passing_cpoe"), 2),
        "carries": round(number("carries") * factor),
        "rushing_yards": round(number("rushing_yards") * factor),
        "rushing_tds": round(number("rushing_tds") * factor, 1),
        "rushing_first_downs": round(number("rushing_first_downs") * factor),
        "rushing_epa": round(number("rushing_epa") * factor, 2),
        "rushing_10": round(number("rushing_10") * factor),
        "rushing_20": round(number("rushing_20") * factor),
        "targets": round(number("targets") * factor),
        "receptions": round(number("receptions") * factor),
        "receiving_yards": round(number("receiving_yards") * factor),
        "receiving_tds": round(number("receiving_tds") * factor, 1),
        "receiving_air_yards": round(number("receiving_air_yards") * factor),
        "receiving_yards_after_catch": round(number("receiving_yards_after_catch") * factor),
        "receiving_first_downs": round(number("receiving_first_downs") * factor),
        "receiving_epa": round(number("receiving_epa") * factor, 2),
    }

    # Public usage/efficiency fields are carried forward as a transparent 2025
    # baseline so a 2026 projection view does not turn into a wall of blanks.
    # Volume fields receive the same modest position multiplier as projections;
    # rate fields retain the prior-season value.
    for field in (
        "offense_snaps", "red_zone_targets", "end_zone_targets",
        "red_zone_carries", "red_zone_receptions", "red_zone_touches",
        "goal_line_carries", "yards_before_contact", "yards_after_contact",
        "rushing_broken_tackles", "receiving_broken_tackles", "drops",
        "qb_throwaways", "qb_drops", "qb_bad_throws", "qb_blitzes",
        "qb_hurries", "qb_hits", "qb_pressures", "qb_on_target_throws",
        "qb_scrambles", "ngs_expected_rush_yards", "ngs_rush_yards_over_expected",
        "expected_total_yards", "expected_total_tds", "expected_receptions",
    ):
        if stats.get(field) not in (None, ""):
            projected[field] = round(number(field) * factor, 2)

    for field in (
        "snap_share", "target_share", "air_yards_share", "wopr", "drop_rate",
        "yards_before_contact_per_carry", "yards_after_contact_per_carry",
        "carries_per_broken_tackle", "receptions_per_broken_tackle",
        "target_interceptions", "target_passer_rating", "qb_drop_rate",
        "qb_bad_throw_rate", "qb_pocket_time", "qb_pressure_rate",
        "qb_on_target_rate", "qb_scramble_ypa", "ngs_time_to_throw",
        "ngs_completed_air_yards", "ngs_intended_air_yards", "ngs_aggressiveness",
        "ngs_expected_completion_rate", "ngs_cpoe", "ngs_passer_rating",
        "ngs_cushion", "ngs_separation", "ngs_adot", "ngs_air_yards_share",
        "ngs_yac_per_reception", "ngs_expected_yac_per_reception",
        "ngs_yac_over_expected_per_reception", "ngs_rush_efficiency",
        "ngs_stacked_box_rate", "ngs_time_to_line", "ngs_ryoe_per_carry",
        "ngs_ryoe_success_rate",
    ):
        if stats.get(field) not in (None, ""):
            projected[field] = stats[field]

    if stats.get("expected_fantasy_points_ppr") not in (None, ""):
        projected["expected_fantasy_points_ppr"] = round(
            number("expected_fantasy_points_ppr") * factor, 1
        )
    projected["usage_basis_year"] = 2025

    prior_ppr = number("fantasy_points_ppr")
    if prior_ppr > 0:
        projected["fantasy_points_ppr"] = round(prior_ppr * factor, 1)
    else:
        projected["fantasy_points_ppr"] = {
            "QB": 245.0,
            "RB": 145.0,
            "WR": 140.0,
            "TE": 105.0,
            "K": 120.0,
            "DEF": 120.0,
        }.get(position, 100.0)

    return projected


# ============================================================
# OFFENSIVE STATS CENTER
# Sortable position rankings plus calculated usage/efficiency metrics.
# ============================================================

OFFENSIVE_ADVANCED_STATS_FILE = DATA_DIR / "offensive_advanced_stats.json"
OFFENSIVE_POSITIONS = {"QB", "RB", "WR", "TE", "K"}
CURRENT_OFFENSIVE_STATS_FILE = DATA_DIR / "nfl_player_stats_2026.json"
BUNDLED_CURRENT_OFFENSIVE_STATS_FILE = BASE_DIR / "data" / "nfl_player_stats_2026.json"
_CURRENT_OFFENSIVE_STATS_CACHE = {"path": "", "mtime": -1, "payload": None}


def _off_num(value, default=0.0):
    try:
        if value in (None, "", "NA", "NaN", "nan", "null", "--"):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _current_offensive_stats_snapshot():
    candidates = (CURRENT_OFFENSIVE_STATS_FILE, BUNDLED_CURRENT_OFFENSIVE_STATS_FILE)
    for path in candidates:
        if not path.exists():
            continue
        try:
            mtime = path.stat().st_mtime_ns
            if (
                _CURRENT_OFFENSIVE_STATS_CACHE.get("path") == str(path)
                and _CURRENT_OFFENSIVE_STATS_CACHE.get("mtime") == mtime
                and isinstance(_CURRENT_OFFENSIVE_STATS_CACHE.get("payload"), dict)
            ):
                return _CURRENT_OFFENSIVE_STATS_CACHE["payload"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("season") or 0) != 2026 or not isinstance(payload.get("players"), dict) or not payload["players"]:
                continue
            _CURRENT_OFFENSIVE_STATS_CACHE.update(path=str(path), mtime=mtime, payload=payload)
            return payload
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            app.logger.warning("Current offensive statistics snapshot ignored: %s", exc)
    return {}


def _off_round(value, digits=1):
    value = _off_num(value)
    rounded = round(value, digits)
    return int(rounded) if digits == 0 or rounded.is_integer() else rounded


def _off_optional_round(value, digits=1):
    """Round a real value while preserving unavailable public-data fields."""
    if value in (None, "", "--"):
        return None
    return _off_round(value, digits)


def _off_pct(value):
    """Normalize either 0-1 shares or already-percent values to 0-100."""
    if value in (None, "", "--"):
        return None
    number = _off_num(value)
    if abs(number) <= 1.5:
        number *= 100
    return round(number, 1)


def _off_div(numerator, denominator, multiplier=1.0, digits=1):
    numerator = _off_num(numerator)
    denominator = _off_num(denominator)
    if denominator <= 0:
        return None
    return round((numerator / denominator) * multiplier, digits)


def _offensive_advanced_players(season):
    """Read an optional licensed/charted-data export without requiring it."""
    if not OFFENSIVE_ADVANCED_STATS_FILE.exists():
        return {}, ""
    try:
        payload = json.loads(OFFENSIVE_ADVANCED_STATS_FILE.read_text(encoding="utf-8"))
        season_key = str(int(season))
        if isinstance(payload.get("seasons"), dict):
            season_payload = payload["seasons"].get(season_key, {})
        elif int(payload.get("season") or 0) == int(season):
            season_payload = payload
        else:
            season_payload = {}
        players = season_payload.get("players", {}) if isinstance(season_payload, dict) else {}
        if isinstance(players, list):
            players = {
                _pr_norm(item.get("name")): item
                for item in players
                if isinstance(item, dict) and item.get("name")
            }
        return (players if isinstance(players, dict) else {}), str(
            season_payload.get("source") or payload.get("source") or "Advanced data import"
        )
    except Exception as exc:
        app.logger.warning("Advanced offensive statistics file ignored: %s", exc)
        return {}, ""


def _offensive_season_source(season):
    season = int(season)
    master_payload = _master_players_2026()
    master_players = master_payload.get("players", {}) if isinstance(master_payload, dict) else {}

    if season == 2026:
        current_actual = _current_offensive_stats_snapshot()
        if current_actual.get("players"):
            return dict(current_actual["players"]), str(
                current_actual.get("source") or "2026 current-season player statistics"
            )
        prior_players = _stats_2025_snapshot().get("players", {}) or {}
        # Interactive tables use the bundled 2026 roster first and an existing
        # cache second. They never wait on a live player-directory request.
        bundled_current = (_defensive_stats_snapshot().get("current_players", {}) or {})
        cached_current = _mock_current_players_by_name(refresh=False, allow_network=False)
        current_players = {**bundled_current, **cached_current}
        fallback_players = {_pr_norm(player["name"]): player for player in MOCK_PLAYER_POOL}
        all_keys = set(prior_players) | set(master_players) | set(current_players) | set(fallback_players)
        rows = {}
        for norm in all_keys:
            prior = dict(prior_players.get(norm) or {})
            master = dict(master_players.get(norm) or {})
            current = dict(current_players.get(norm) or {})
            fallback = dict(fallback_players.get(norm) or {})
            position = str(
                current.get("position")
                or master.get("position")
                or prior.get("position")
                or fallback.get("pos")
                or ""
            ).upper()
            if position == "DST":
                position = "DEF"
            if position not in OFFENSIVE_POSITIONS:
                continue

            current_team = _normalize_team_code(current.get("team"))
            if current and not current_team:
                current_team = "FA"
            team = (
                current_team
                or _normalize_team_code(master.get("team"))
                or _normalize_team_code(prior.get("team"))
                or _normalize_team_code(fallback.get("team"))
                or "FA"
            )
            # Exclude inactive historical records that are absent from every
            # current/projection signal.
            if current_players and not current and not master and not fallback:
                continue

            projected = _fast_2026_projection_from_2025(prior, position)
            projection_block = master.get("projection") or {}
            if isinstance(projection_block, dict):
                for field in (
                    "games", "completions", "attempts", "passing_yards", "passing_tds",
                    "interceptions", "carries", "rushing_yards", "rushing_tds",
                    "targets", "receptions", "receiving_yards", "receiving_tds",
                ):
                    if projection_block.get(field) not in (None, ""):
                        projected[field] = projection_block[field]
                projected_points = (
                    projection_block.get("ppr_points")
                    or projection_block.get("fantasy_points_ppr")
                    or projection_block.get("fantasy_points")
                )
                if projected_points not in (None, ""):
                    projected["fantasy_points_ppr"] = projected_points
            if fallback.get("projection") and not projection_block:
                projected["fantasy_points_ppr"] = fallback["projection"]

            rows[norm] = {
                **projected,
                "season": 2026,
                "data_type": "projection",
                "name": current.get("full_name") or master.get("name") or prior.get("name") or fallback.get("name") or norm,
                "player_id": current.get("player_id") or master.get("sleeper_id") or prior.get("player_id") or "",
                "position": position,
                "team": team,
            }
        return rows, "2026 Gridiron IQ projections"

    if season == 2025:
        snapshot = _stats_2025_snapshot()
        return dict(snapshot.get("players", {}) or {}), str(snapshot.get("source") or "2025 player statistics")

    career = _career_stats_snapshot()
    rows = {}
    for norm, seasons in (career.get("players", {}) or {}).items():
        if not isinstance(seasons, dict):
            continue
        record = seasons.get(str(season))
        if isinstance(record, dict):
            rows[norm] = dict(record)
    return rows, str(career.get("source") or "Career-history statistics")


def _offensive_stats_rows(season=2025, scoring="PPR"):
    season = int(season)
    scoring = str(scoring or "PPR").upper()
    if scoring not in {"PPR", "HALF", "STANDARD"}:
        scoring = "PPR"

    source_players, source_label = _offensive_season_source(season)
    advanced_players, advanced_source = _offensive_advanced_players(season)
    master_players = _master_players_2026().get("players", {}) or {}
    prepared = []

    for raw_norm, raw in source_players.items():
        if not isinstance(raw, dict):
            continue
        norm = _pr_norm(raw.get("name") or raw_norm)
        master = master_players.get(norm, {}) if isinstance(master_players, dict) else {}
        position = str(raw.get("position") or master.get("position") or "").upper()
        if position == "DST":
            position = "DEF"
        if position not in OFFENSIVE_POSITIONS:
            continue

        name = str(raw.get("name") or master.get("name") or "").strip()
        if not name:
            continue
        advanced = advanced_players.get(norm, {}) if isinstance(advanced_players, dict) else {}
        if not isinstance(advanced, dict):
            advanced = {}

        receptions = _off_num(raw.get("receptions"))
        standard_points = _off_num(raw.get("fantasy_points"))
        ppr_points = _off_num(raw.get("fantasy_points_ppr"))
        if not standard_points and ppr_points:
            standard_points = max(0, ppr_points - receptions)
        if not ppr_points and standard_points:
            ppr_points = standard_points + receptions
        selected_points = (
            ppr_points if scoring == "PPR"
            else standard_points + receptions * 0.5 if scoring == "HALF"
            else standard_points
        )

        expected_receptions = _off_optional_round(raw.get("expected_receptions"), 2)
        expected_ppr = _off_optional_round(raw.get("expected_fantasy_points_ppr"), 1)
        expected_points = expected_ppr
        if expected_ppr is not None and expected_receptions is not None:
            if scoring == "HALF":
                expected_points = round(max(0, expected_ppr - expected_receptions * 0.5), 1)
            elif scoring == "STANDARD":
                expected_points = round(max(0, expected_ppr - expected_receptions), 1)
        imported_expected = advanced.get("expected_fantasy_points")
        if imported_expected not in (None, ""):
            expected_points = _off_round(imported_expected, 1)

        team = _normalize_team_code(raw.get("team")) or "FA"
        if season == 2026 and str(raw.get("data_type") or "").lower() != "actual":
            team = _normalize_team_code(master.get("team") or team) or "FA"

        row = {
            "player_key": norm,
            "player_id": str(raw.get("player_id") or master.get("sleeper_id") or ""),
            "name": name,
            "position": position,
            "team": team,
            "season": season,
            "data_type": raw.get("data_type") or "actual",
            "usage_basis_year": raw.get("usage_basis_year"),
            "games": _off_round(raw.get("games"), 0),
            "completions": _off_round(raw.get("completions"), 0),
            "attempts": _off_round(raw.get("attempts"), 0),
            "passing_yards": _off_round(raw.get("passing_yards"), 0),
            "passing_tds": _off_round(raw.get("passing_tds"), 1),
            "interceptions": _off_round(raw.get("interceptions"), 1),
            "carries": _off_round(raw.get("carries") or raw.get("rushing_attempts"), 0),
            "rushing_yards": _off_round(raw.get("rushing_yards"), 0),
            "rushing_tds": _off_round(raw.get("rushing_tds"), 1),
            "targets": _off_round(raw.get("targets"), 0),
            "receptions": _off_round(receptions, 0),
            "receiving_yards": _off_round(raw.get("receiving_yards"), 0),
            "receiving_tds": _off_round(raw.get("receiving_tds"), 1),
            "fantasy_points": round(selected_points, 1),
            "fantasy_points_ppr": round(ppr_points, 1),
            "passing_air_yards": _off_round(raw.get("passing_air_yards"), 0),
            "passing_first_downs": _off_round(raw.get("passing_first_downs"), 0),
            "passing_epa": _off_round(raw.get("passing_epa"), 2),
            "passing_cpoe": _off_round(raw.get("passing_cpoe"), 2),
            "sacks_suffered": _off_round(raw.get("sacks_suffered"), 0),
            "rushing_first_downs": _off_round(raw.get("rushing_first_downs"), 0),
            "rushing_epa": _off_round(raw.get("rushing_epa"), 2),
            "rushing_10": _off_round(raw.get("rushing_10"), 0),
            "rushing_20": _off_round(raw.get("rushing_20"), 0),
            "receiving_air_yards": _off_round(raw.get("receiving_air_yards"), 0),
            "yards_after_catch": _off_round(raw.get("receiving_yards_after_catch"), 0),
            "receiving_first_downs": _off_round(raw.get("receiving_first_downs"), 0),
            "receiving_epa": _off_round(raw.get("receiving_epa"), 2),
            "wopr": _off_round(raw.get("wopr"), 2),
            "fg_made": _off_round(raw.get("fg_made"), 0),
            "fg_att": _off_round(raw.get("fg_att"), 0),
            "fg_pct": _off_pct(raw.get("fg_pct")),
            "fg_long": _off_round(raw.get("fg_long"), 0),
            "fg_made_40_49": _off_round(raw.get("fg_made_40_49"), 0),
            "fg_made_50_59": _off_round(raw.get("fg_made_50_59"), 0),
            "fg_made_60_plus": _off_round(raw.get("fg_made_60_"), 0),
            "pat_made": _off_round(raw.get("pat_made"), 0),
            "pat_att": _off_round(raw.get("pat_att"), 0),
            "pat_pct": _off_pct(raw.get("pat_pct")),
            "offense_snaps": _off_optional_round(raw.get("offense_snaps"), 0),
            "routes_run": _off_round(advanced.get("routes_run"), 0) if advanced.get("routes_run") not in (None, "") else None,
            "route_share": _off_pct(advanced.get("route_share")),
            "snap_share": _off_pct(advanced.get("snap_share", raw.get("snap_share"))),
            "air_yards": _off_round(advanced.get("air_yards", raw.get("receiving_air_yards")), 0) if advanced.get("air_yards", raw.get("receiving_air_yards")) not in (None, "") else None,
            "air_yards_share": _off_pct(advanced.get("air_yards_share", raw.get("air_yards_share"))),
            "adot": _off_round(advanced.get("adot"), 1) if advanced.get("adot") not in (None, "") else None,
            "red_zone_targets": _off_optional_round(advanced.get("red_zone_targets", raw.get("red_zone_targets")), 0),
            "end_zone_targets": _off_optional_round(advanced.get("end_zone_targets", raw.get("end_zone_targets")), 0),
            "red_zone_carries": _off_optional_round(advanced.get("red_zone_carries", raw.get("red_zone_carries")), 0),
            "red_zone_receptions": _off_optional_round(advanced.get("red_zone_receptions", raw.get("red_zone_receptions")), 0),
            "red_zone_touches": _off_optional_round(advanced.get("red_zone_touches", raw.get("red_zone_touches")), 0),
            "goal_line_carries": _off_optional_round(advanced.get("goal_line_carries", raw.get("goal_line_carries")), 0),
            "yards_before_contact": _off_optional_round(raw.get("yards_before_contact"), 0),
            "yards_before_contact_per_carry": _off_optional_round(raw.get("yards_before_contact_per_carry"), 1),
            "yards_after_contact": _off_optional_round(advanced.get("yards_after_contact", raw.get("yards_after_contact")), 0),
            "yards_after_contact_per_carry": _off_optional_round(raw.get("yards_after_contact_per_carry"), 1),
            "rushing_broken_tackles": _off_optional_round(raw.get("rushing_broken_tackles"), 0),
            "carries_per_broken_tackle": _off_optional_round(raw.get("carries_per_broken_tackle"), 1),
            "receiving_broken_tackles": _off_optional_round(raw.get("receiving_broken_tackles"), 0),
            "receptions_per_broken_tackle": _off_optional_round(raw.get("receptions_per_broken_tackle"), 1),
            "drops": _off_optional_round(raw.get("drops"), 0),
            "drop_rate": _off_optional_round(raw.get("drop_rate"), 1),
            "target_interceptions": _off_optional_round(raw.get("target_interceptions"), 0),
            "target_passer_rating": _off_optional_round(raw.get("target_passer_rating"), 1),
            "missed_tackles_forced": _off_optional_round(advanced.get("missed_tackles_forced"), 0),
            "first_read_target_share": _off_pct(advanced.get("first_read_target_share")),
            "separation_score": _off_optional_round(advanced.get("separation_score"), 3),
            "route_win_rate": _off_pct(advanced.get("route_win_rate")),
            "expected_fantasy_points": expected_points,
            "expected_receptions": expected_receptions,
            "expected_total_yards": _off_optional_round(raw.get("expected_total_yards"), 1),
            "expected_total_tds": _off_optional_round(raw.get("expected_total_tds"), 2),
            "qb_throwaways": _off_optional_round(raw.get("qb_throwaways"), 0),
            "qb_drops": _off_optional_round(raw.get("qb_drops"), 0),
            "qb_drop_rate": _off_optional_round(raw.get("qb_drop_rate"), 1),
            "qb_bad_throws": _off_optional_round(raw.get("qb_bad_throws"), 0),
            "qb_bad_throw_rate": _off_optional_round(raw.get("qb_bad_throw_rate"), 1),
            "qb_pocket_time": _off_optional_round(raw.get("qb_pocket_time"), 2),
            "qb_blitzes": _off_optional_round(raw.get("qb_blitzes"), 0),
            "qb_hurries": _off_optional_round(raw.get("qb_hurries"), 0),
            "qb_hits": _off_optional_round(raw.get("qb_hits"), 0),
            "qb_pressures": _off_optional_round(raw.get("qb_pressures"), 0),
            "qb_pressure_rate": _off_optional_round(raw.get("qb_pressure_rate"), 1),
            "qb_on_target_throws": _off_optional_round(raw.get("qb_on_target_throws"), 0),
            "qb_on_target_rate": _off_optional_round(raw.get("qb_on_target_rate"), 1),
            "qb_scrambles": _off_optional_round(raw.get("qb_scrambles"), 0),
            "qb_scramble_ypa": _off_optional_round(raw.get("qb_scramble_ypa"), 1),
            "ngs_time_to_throw": _off_optional_round(raw.get("ngs_time_to_throw"), 2),
            "ngs_completed_air_yards": _off_optional_round(raw.get("ngs_completed_air_yards"), 1),
            "ngs_intended_air_yards": _off_optional_round(raw.get("ngs_intended_air_yards"), 1),
            "ngs_aggressiveness": _off_optional_round(raw.get("ngs_aggressiveness"), 1),
            "ngs_expected_completion_rate": _off_optional_round(raw.get("ngs_expected_completion_rate"), 1),
            "ngs_cpoe": _off_optional_round(raw.get("ngs_cpoe"), 1),
            "ngs_passer_rating": _off_optional_round(raw.get("ngs_passer_rating"), 1),
            "ngs_cushion": _off_optional_round(raw.get("ngs_cushion"), 2),
            "ngs_separation": _off_optional_round(raw.get("ngs_separation"), 2),
            "ngs_adot": _off_optional_round(raw.get("ngs_adot"), 1),
            "ngs_air_yards_share": _off_optional_round(raw.get("ngs_air_yards_share"), 1),
            "ngs_yac_per_reception": _off_optional_round(raw.get("ngs_yac_per_reception"), 1),
            "ngs_expected_yac_per_reception": _off_optional_round(raw.get("ngs_expected_yac_per_reception"), 1),
            "ngs_yac_over_expected_per_reception": _off_optional_round(raw.get("ngs_yac_over_expected_per_reception"), 2),
            "ngs_rush_efficiency": _off_optional_round(raw.get("ngs_rush_efficiency"), 2),
            "ngs_stacked_box_rate": _off_optional_round(raw.get("ngs_stacked_box_rate"), 1),
            "ngs_time_to_line": _off_optional_round(raw.get("ngs_time_to_line"), 2),
            "ngs_expected_rush_yards": _off_optional_round(raw.get("ngs_expected_rush_yards"), 0),
            "ngs_rush_yards_over_expected": _off_optional_round(raw.get("ngs_rush_yards_over_expected"), 0),
            "ngs_ryoe_per_carry": _off_optional_round(raw.get("ngs_ryoe_per_carry"), 2),
            "ngs_ryoe_success_rate": _off_pct(raw.get("ngs_ryoe_success_rate")),
        }
        prepared.append(row)

    team_totals = defaultdict(lambda: defaultdict(float))
    for row in prepared:
        team = row["team"]
        if not team or team == "FA":
            continue
        for key in (
            "attempts", "carries", "targets", "receiving_yards", "rushing_yards",
            "red_zone_targets", "red_zone_carries", "red_zone_touches",
        ):
            team_totals[team][key] += _off_num(row.get(key))
        if row.get("air_yards") is not None:
            team_totals[team]["air_yards"] += _off_num(row.get("air_yards"))

    for row in prepared:
        team = team_totals.get(row["team"], {})
        games = row["games"]
        opportunities = _off_num(row["carries"]) + _off_num(row["targets"])
        row.update({
            "fantasy_points_per_game": _off_div(row["fantasy_points"], games),
            "pass_yards_per_game": _off_div(row["passing_yards"], games),
            "rush_yards_per_game": _off_div(row["rushing_yards"], games),
            "receiving_yards_per_game": _off_div(row["receiving_yards"], games),
            "completion_rate": _off_div(row["completions"], row["attempts"], 100),
            "yards_per_attempt": _off_div(row["passing_yards"], row["attempts"]),
            "passing_touchdown_rate": _off_div(row["passing_tds"], row["attempts"], 100),
            "interception_rate": _off_div(row["interceptions"], row["attempts"], 100),
            "sack_rate": _off_div(row["sacks_suffered"], _off_num(row["attempts"]) + _off_num(row["sacks_suffered"]), 100),
            "passing_epa_per_dropback": _off_div(row["passing_epa"], _off_num(row["attempts"]) + _off_num(row["sacks_suffered"]), digits=3),
            "yards_per_carry": _off_div(row["rushing_yards"], row["carries"]),
            "rushing_epa_per_carry": _off_div(row["rushing_epa"], row["carries"], digits=3),
            "explosive_run_rate": _off_div(row["rushing_10"], row["carries"], 100),
            "catch_rate": _off_div(row["receptions"], row["targets"], 100),
            "yards_per_target": _off_div(row["receiving_yards"], row["targets"]),
            "yards_per_reception": _off_div(row["receiving_yards"], row["receptions"]),
            "receiving_touchdown_rate": _off_div(row["receiving_tds"], row["targets"], 100),
            "receiving_first_down_rate": _off_div(row["receiving_first_downs"], row["targets"], 100),
            "receiving_epa_per_target": _off_div(row["receiving_epa"], row["targets"], digits=3),
            "yards_after_catch_per_reception": _off_div(row["yards_after_catch"], row["receptions"]),
            "targets_per_game": _off_div(row["targets"], games),
            "touches": _off_round(_off_num(row["carries"]) + _off_num(row["receptions"]), 0),
            "touches_per_game": _off_div(_off_num(row["carries"]) + _off_num(row["receptions"]), games),
            "opportunities": _off_round(opportunities, 0),
            "opportunities_per_game": _off_div(opportunities, games),
            "points_per_opportunity": _off_div(row["fantasy_points"], opportunities, digits=2),
            "target_share": _off_div(row["targets"], team.get("targets"), 100),
            "rush_share": _off_div(row["carries"], team.get("carries"), 100),
            "opportunity_share": _off_div(opportunities, _off_num(team.get("targets")) + _off_num(team.get("carries")), 100),
            "receiving_yard_share": _off_div(row["receiving_yards"], team.get("receiving_yards"), 100),
            "rushing_yard_share": _off_div(row["rushing_yards"], team.get("rushing_yards"), 100),
            "red_zone_target_share": _off_div(row.get("red_zone_targets"), team.get("red_zone_targets"), 100),
            "red_zone_carry_share": _off_div(row.get("red_zone_carries"), team.get("red_zone_carries"), 100),
            "red_zone_touch_share": _off_div(row.get("red_zone_touches"), team.get("red_zone_touches"), 100),
            "total_yards": _off_round(_off_num(row["passing_yards"]) + _off_num(row["rushing_yards"]) + _off_num(row["receiving_yards"]), 0),
            "total_tds": _off_round(_off_num(row["passing_tds"]) + _off_num(row["rushing_tds"]) + _off_num(row["receiving_tds"]), 1),
        })
        if row.get("routes_run"):
            row["targets_per_route_run"] = _off_div(row["targets"], row["routes_run"], 100)
            row["yards_per_route_run"] = _off_div(row["receiving_yards"], row["routes_run"], digits=2)
        else:
            row["targets_per_route_run"] = None
            row["yards_per_route_run"] = None
        if row.get("air_yards") is not None:
            row["adot"] = row.get("adot") if row.get("adot") is not None else _off_div(row["air_yards"], row["targets"])
            row["air_yards_share"] = row.get("air_yards_share") if row.get("air_yards_share") is not None else _off_div(row["air_yards"], team.get("air_yards"), 100)
            row["receiver_air_conversion_ratio"] = _off_div(row["receiving_yards"], row["air_yards"], digits=2)
        else:
            row["receiver_air_conversion_ratio"] = None
        expected = row.get("expected_fantasy_points")
        row["fantasy_points_over_expected"] = round(row["fantasy_points"] - expected, 1) if expected is not None else None

    prepared.sort(key=lambda item: (-_off_num(item.get("fantasy_points")), item["name"]))
    overall_rank = 0
    position_ranks = defaultdict(int)
    for row in prepared:
        overall_rank += 1
        position_ranks[row["position"]] += 1
        row["overall_rank"] = overall_rank
        row["position_rank"] = position_ranks[row["position"]]
        row["rank_label"] = f"{row['position']}{row['position_rank']}"

    current_snapshot = _current_offensive_stats_snapshot() if season == 2026 else {}
    data_type = "actual" if any(str(row.get("data_type") or "").lower() == "actual" for row in prepared) else "projection" if season == 2026 else "actual"
    return prepared, {
        "season": season,
        "data_type": data_type,
        "scoring": scoring,
        "source": source_label,
        "advanced_source": advanced_source,
        "advanced_available": bool(advanced_players),
        "public_advanced_available": any(row.get("snap_share") is not None for row in prepared),
        "next_gen_note": "NFL Next Gen Stats fields include only players meeting the NFL minimum-attempt threshold.",
        "usage_basis_year": 2025 if season == 2026 and data_type == "projection" else None,
        "updated_at": current_snapshot.get("updated_at") if data_type == "actual" else None,
        "games_played_max": current_snapshot.get("games_played_max") if data_type == "actual" else None,
    }


def _offensive_stats_seasons():
    career = _career_stats_snapshot()
    seasons = {2025, 2026}
    for value in career.get("loaded_seasons", []):
        try:
            seasons.add(int(value))
        except (TypeError, ValueError):
            pass
    return sorted(seasons, reverse=True)


@app.get("/offensive-stats")
def offensive_stats_page():
    return page(
        "offensive_stats.html",
        offensive_seasons=_offensive_stats_seasons(),
        default_offensive_season=2026,
    )


@app.get("/api/offensive-stats/table")
def offensive_stats_table_api():
    try:
        season = int(request.args.get("season") or 2025)
    except (TypeError, ValueError):
        season = 2025
    if season not in _offensive_stats_seasons():
        return jsonify(ok=False, error="That season has not been loaded."), 400

    scoring = str(request.args.get("scoring") or "PPR").upper()
    position = str(request.args.get("position") or "ALL").upper()
    if position not in OFFENSIVE_POSITIONS | {"ALL"}:
        position = "ALL"

    rows, metadata = _offensive_stats_rows(season=season, scoring=scoring)
    if position != "ALL":
        rows = [row for row in rows if row["position"] == position]

    return jsonify(
        ok=True,
        count=len(rows),
        selected_position=position,
        rows=rows,
        metadata=metadata,
    )


# ============================================================
# DEFENSIVE DATA CENTER + WEEKLY MATCHUP LAB
# Bundled 2025 defense/coverage data and 2026 schedule matchups.
# ============================================================

DEFENSIVE_STATS_FILE = DATA_DIR / "nfl_defensive_stats_2025.json"
BUNDLED_DEFENSIVE_STATS_FILE = BASE_DIR / "data" / "nfl_defensive_stats_2025.json"
CURRENT_DEFENSIVE_STATS_FILE = DATA_DIR / "nfl_defensive_stats_current.json"
BUNDLED_CURRENT_DEFENSIVE_STATS_FILE = BASE_DIR / "data" / "nfl_defensive_stats_current.json"
_DEFENSIVE_SNAPSHOT_CACHE = {"path": "", "mtime": -1, "payload": None}


def _defensive_stats_snapshot():
    empty = {
        "season": 2025, "matchup_season": 2026, "players": {}, "teams": {},
        "offensive_lines": {}, "current_defenders": {}, "receiver_splits": {},
        "league_receiver_splits": {}, "schedule_2026": [], "source": "",
    }
    candidates = (
        CURRENT_DEFENSIVE_STATS_FILE,
        BUNDLED_CURRENT_DEFENSIVE_STATS_FILE,
        DEFENSIVE_STATS_FILE,
        BUNDLED_DEFENSIVE_STATS_FILE,
    )
    for path in candidates:
        if not path.exists():
            continue
        try:
            mtime = path.stat().st_mtime_ns
            if (
                _DEFENSIVE_SNAPSHOT_CACHE.get("path") == str(path)
                and _DEFENSIVE_SNAPSHOT_CACHE.get("mtime") == mtime
                and isinstance(_DEFENSIVE_SNAPSHOT_CACHE.get("payload"), dict)
            ):
                return _DEFENSIVE_SNAPSHOT_CACHE["payload"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("players"), dict) or len(payload.get("teams", {})) < 28:
                continue
            _DEFENSIVE_SNAPSHOT_CACHE.update(path=str(path), mtime=mtime, payload=payload)
            return payload
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            app.logger.warning("Defensive statistics snapshot ignored: %s", exc)
    return empty


def _def_clamp(value, low=1.0, high=99.0):
    return round(max(low, min(high, _off_num(value))), 1)


def _def_letter_grade(score):
    score = _off_num(score)
    if score >= 93: return "A+"
    if score >= 87: return "A"
    if score >= 82: return "A-"
    if score >= 77: return "B+"
    if score >= 71: return "B"
    if score >= 66: return "B-"
    if score >= 60: return "C+"
    if score >= 54: return "C"
    if score >= 48: return "C-"
    if score >= 42: return "D+"
    if score >= 35: return "D"
    return "F"


def _def_team_code(value):
    value = str(value or "").strip().upper()
    return {
        "LAR": "LA", "STL": "LA", "JAC": "JAX", "OAK": "LV",
        "SD": "LAC", "SDG": "LAC", "WSH": "WAS",
    }.get(value, value)


def _defensive_player_rows(group="ALL"):
    payload = _defensive_stats_snapshot()
    rows = [dict(row) for row in (payload.get("players", {}) or {}).values() if isinstance(row, dict)]
    group = str(group or "ALL").upper()
    if group == "DB":
        rows = [row for row in rows if row.get("position_group") == group]
    elif group in {"CB", "S", "LB", "DL", "EDGE"}:
        rows = [row for row in rows if row.get("role") == group]
    rows.sort(key=lambda row: (-_off_num(row.get("defense_grade")), row.get("name", "")))
    return rows, payload


def _defensive_team_rows():
    payload = _defensive_stats_snapshot()
    rows = [dict(row) for row in (payload.get("teams", {}) or {}).values() if isinstance(row, dict)]
    rows.sort(key=lambda row: (-_off_num(row.get("overall_grade")), row.get("team", "")))
    return rows, payload


@app.get("/defensive-stats")
def defensive_stats_page():
    return page("defensive_stats.html")


@app.get("/api/defensive-stats/table")
def defensive_stats_table_api():
    view = str(request.args.get("view") or "TEAM").upper()
    group = str(request.args.get("group") or "ALL").upper()
    if view == "TEAM":
        rows, payload = _defensive_team_rows()
    else:
        rows, payload = _defensive_player_rows(group)
    return jsonify(
        ok=True,
        count=len(rows),
        view=view,
        group=group,
        rows=rows,
        metadata={
            "season": payload.get("season", 2025),
            "source": payload.get("source") or "Gridiron IQ defensive snapshot",
            "license_note": payload.get("license_note") or "",
            "updated_at": payload.get("updated_at") or "",
        },
    )


def _weekly_schedule_lookup(payload, week):
    result = {}
    for game in payload.get("schedule_2026", []) or []:
        if int(game.get("week") or 0) != int(week):
            continue
        away = _def_team_code(game.get("away_team"))
        home = _def_team_code(game.get("home_team"))
        result[away] = {**game, "team": away, "opponent": home, "location": "Away"}
        result[home] = {**game, "team": home, "opponent": away, "location": "Home"}
    return result


def _weekly_defender_candidates(payload, opponent, position):
    players = payload.get("players", {}) or {}
    keys = (payload.get("current_defenders", {}) or {}).get(opponent, []) or []
    candidates = [dict(players[key]) for key in keys if key in players]
    if position == "WR":
        preferred = [row for row in candidates if row.get("role") == "CB"]
    else:
        preferred = [row for row in candidates if row.get("role") in {"S", "LB"}]
    if not preferred:
        preferred = [row for row in candidates if row.get("position_group") in {"DB", "LB"}]
    preferred.sort(key=lambda row: (
        -_off_num(row.get("snap_share")),
        -_off_num(row.get("coverage_targets")),
        -_off_num(row.get("coverage_grade")),
    ))
    return preferred[:3]


def _matchup_percentile_grades(rows, position):
    eligible = [row for row in rows if row.get("position") == position]
    eligible.sort(key=lambda row: _off_num(row.get("fantasy_points")))
    total = max(1, len(eligible) - 1)
    return {
        _pr_norm(row.get("name")): round(index / total * 98 + 1, 1)
        for index, row in enumerate(eligible)
    }


def _weekly_matchup_rows(week=1, position="ALL"):
    payload = _defensive_stats_snapshot()
    schedule = _weekly_schedule_lookup(payload, week)
    offense_rows, _ = _offensive_stats_rows(season=2026, scoring="PPR")
    positions = {"RB", "WR", "TE"} if position == "ALL" else {position}
    offense_rows = [
        row for row in offense_rows
        if (
            row.get("position") in positions
            and _off_num(row.get("fantasy_points")) > 0
            and (
                _off_num(row.get("carries")) > 0
                or _off_num(row.get("targets")) > 0
                or _off_num(row.get("receptions")) > 0
                or _off_num(row.get("receiving_yards")) > 0
            )
        )
    ]
    skill_grades = {
        **_matchup_percentile_grades(offense_rows, "RB"),
        **_matchup_percentile_grades(offense_rows, "WR"),
        **_matchup_percentile_grades(offense_rows, "TE"),
    }
    teams = payload.get("teams", {}) or {}
    offensive_lines = payload.get("offensive_lines", {}) or {}
    receiver_splits = payload.get("receiver_splits", {}) or {}
    league_splits = payload.get("league_receiver_splits", {}) or {}

    position_allowed_averages = {}
    for pos in ("RB", "WR", "TE"):
        values = [
            _off_num(((team.get("allowed_by_position") or {}).get(pos) or {}).get("ppr_per_target"))
            for team in teams.values()
            if ((team.get("allowed_by_position") or {}).get(pos) or {}).get("ppr_per_target") is not None
        ]
        position_allowed_averages[pos] = sum(values) / len(values) if values else 1.5

    prepared = []
    for player in offense_rows:
        name = str(player.get("name") or "").strip()
        player_position = str(player.get("position") or "").upper()
        team = _def_team_code(player.get("team"))
        game = schedule.get(team)
        if not name or not game:
            continue
        opponent = game["opponent"]
        defense = dict(teams.get(opponent) or {})
        line = dict(offensive_lines.get(team) or {})
        defenders = _weekly_defender_candidates(payload, opponent, player_position)
        primary = defenders[0] if defenders else {}

        man_rate = _off_num(defense.get("man_rate"))
        zone_rate = _off_num(defense.get("zone_rate"))
        dominant_label = "ZONE_COVERAGE" if zone_rate >= man_rate else "MAN_COVERAGE"
        dominant_name = "Zone" if dominant_label == "ZONE_COVERAGE" else "Man"
        dominant_rate = max(man_rate, zone_rate)
        player_history = receiver_splits.get(_pr_norm(name), {}) or {}
        split = ((player_history.get("splits") or {}).get(dominant_label) or {})
        baseline = (((league_splits.get(player_position) or {}).get(dominant_label)) or {})
        player_ppr_target = split.get("ppr_per_target")
        baseline_ppr_target = _off_num(baseline.get("ppr_per_target"), 1.5)
        if player_ppr_target is None:
            player_ppr_target = baseline_ppr_target
            split_basis = "Position baseline"
        else:
            split_basis = "2025 player split"
        coverage_fit = _def_clamp(
            (_off_num(player_ppr_target) - baseline_ppr_target) * 12,
            -12,
            12,
        )

        allowed = ((defense.get("allowed_by_position") or {}).get(player_position) or {})
        allowed_ppr_target = _off_num(allowed.get("ppr_per_target"), position_allowed_averages[player_position])
        allowed_fit = _def_clamp(
            (allowed_ppr_target - position_allowed_averages[player_position]) * 10,
            -10,
            10,
        )
        skill_grade = _off_num(skill_grades.get(_pr_norm(name)), 50)
        secondary_grade = _off_num(defense.get("secondary_grade"), 50)
        defender_grade = _off_num(primary.get("coverage_grade") or primary.get("defense_grade"), 50)
        pass_pro_grade = _off_num(line.get("pass_protection_grade"), 50)
        run_block_grade = _off_num(line.get("run_blocking_grade"), 50)
        pass_rush_grade = _off_num(defense.get("pass_rush_grade"), 50)
        run_defense_grade = _off_num(defense.get("run_defense_grade"), 50)
        front_grade = _off_num(defense.get("front_grade"), 50)
        pass_trench_score = _def_clamp(50 + (pass_pro_grade - pass_rush_grade) * 0.55)
        run_trench_score = _def_clamp(50 + (run_block_grade - run_defense_grade) * 0.55)
        rush_share = _off_num(player.get("rush_share"))
        opportunity_share = _off_num(player.get("opportunity_share"))
        red_zone_carry_share = player.get("red_zone_carry_share")
        if red_zone_carry_share in (None, ""):
            red_zone_carry_share = rush_share
        red_zone_carry_share = _off_num(red_zone_carry_share)
        workload_grade = _def_clamp(
            20 + rush_share * 0.45 + opportunity_share * 0.25 + red_zone_carry_share * 0.20
        )
        receiving_matchup_grade = _def_clamp(
            50
            + (allowed_ppr_target - position_allowed_averages[player_position]) * 20
            + _off_num(player.get("target_share")) * 0.20
        )
        run_defense_advantage = _def_clamp(100 - run_defense_grade)

        if player_position == "RB":
            # RB model: 25% player, 40% OL/front comparison, 20% opponent
            # run defense, 10% workload, and 5% receiving matchup.
            score = _def_clamp(
                skill_grade * 0.25
                + run_trench_score * 0.40
                + run_defense_advantage * 0.20
                + workload_grade * 0.10
                + receiving_matchup_grade * 0.05
            )
            matchup_model = "RUNNING_BACK"
        else:
            score = _def_clamp(
                50
                + (skill_grade - 50) * 0.30
                + (50 - secondary_grade) * 0.28
                + (50 - defender_grade) * 0.12
                + coverage_fit
                + allowed_fit
                + (pass_trench_score - 50) * 0.12
            )
            matchup_model = "RECEIVER"
        grade = _def_letter_grade(score)
        if score >= 72:
            verdict = "Strong advantage"
        elif score >= 58:
            verdict = "Favorable"
        elif score >= 44:
            verdict = "Neutral"
        elif score >= 32:
            verdict = "Difficult"
        else:
            verdict = "Major challenge"

        top_coverage = str(defense.get("top_coverage") or "").replace("_", " ").title()
        coverage_note = (
            f"{opponent} used {dominant_name.lower()} on {dominant_rate:.1f}% of charted dropbacks"
            + (f" and leaned most on {top_coverage}." if top_coverage else ".")
            + f" {name} produced {_off_num(player_ppr_target):.2f} PPR points per target against {dominant_name.lower()} ({split_basis.lower()})."
        )
        if player_position == "RB":
            defender_note = (
                f"{opponent}'s defensive front grade is {front_grade:.1f} "
                f"(rank #{int(_off_num(defense.get('front_rank'), 0)) or '—'}), with a "
                f"{run_defense_grade:.1f} run-defense grade. The RB receiving matchup allows "
                f"{allowed_ppr_target:.2f} PPR points per target."
            )
        elif primary:
            defender_note = (
                f"Likely primary matchup: {primary.get('name')} ({primary.get('role')}) — "
                f"{_off_num(primary.get('snap_share')):.1f}% snap share, "
                f"{int(_off_num(primary.get('coverage_targets')))} coverage targets, "
                f"{_off_num(primary.get('passer_rating_allowed')):.1f} passer rating allowed in 2025."
            )
        else:
            defender_note = "No returning high-snap coverage defender was available in the bundled current roster."
        if player_position == "RB":
            trench_note = (
                f"{team} projected run-blocking grade {run_block_grade:.1f} "
                f"(rank #{int(_off_num(line.get('run_blocking_rank'), 0)) or '—'}) versus "
                f"{opponent} run-defense grade {run_defense_grade:.1f} "
                f"(rank #{int(_off_num(defense.get('run_defense_rank'), 0)) or '—'}); "
                f"run-trench advantage score {run_trench_score:.1f}. "
                f"That is a {verdict.lower()} RB matchup."
            )
        else:
            trench_note = (
                f"Pass protection grade {pass_pro_grade:.1f} versus {opponent} pass-rush grade {pass_rush_grade:.1f}; "
                f"pass-trench advantage score {pass_trench_score:.1f}."
            )

        prepared.append({
            "name": name,
            "position": player_position,
            "team": team,
            "opponent": opponent,
            "week": int(week),
            "gameday": game.get("gameday"),
            "gametime": game.get("gametime"),
            "location": game.get("location"),
            "projected_points": _off_round(player.get("fantasy_points"), 1),
            "offense_data_type": player.get("data_type") or "projection",
            "matchup_model": matchup_model,
            "carries": player.get("carries"),
            "rushing_yards": player.get("rushing_yards"),
            "yards_per_carry": player.get("yards_per_carry"),
            "target_share": player.get("target_share"),
            "rush_share": player.get("rush_share"),
            "opportunity_share": player.get("opportunity_share"),
            "red_zone_carry_share": player.get("red_zone_carry_share"),
            "red_zone_touch_share": player.get("red_zone_touch_share"),
            "air_yards_share": player.get("air_yards_share"),
            "skill_grade": round(skill_grade, 1),
            "workload_grade": workload_grade,
            "receiving_matchup_grade": receiving_matchup_grade,
            "matchup_score": score,
            "matchup_grade": grade,
            "verdict": verdict,
            "primary_defender": primary.get("name") or "Coverage unit",
            "primary_defender_role": primary.get("role") or "DB/LB",
            "defender_grade": round(defender_grade, 1),
            "defender_snap_share": primary.get("snap_share"),
            "defender_targets": primary.get("coverage_targets"),
            "defender_rating_allowed": primary.get("passer_rating_allowed"),
            "defenders": [
                {
                    "name": item.get("name"), "role": item.get("role"),
                    "coverage_grade": item.get("coverage_grade"),
                    "defense_grade": item.get("defense_grade"),
                    "snap_share": item.get("snap_share"),
                    "coverage_targets": item.get("coverage_targets"),
                    "passer_rating_allowed": item.get("passer_rating_allowed"),
                    "yards_per_target_allowed": item.get("yards_per_target_allowed"),
                }
                for item in defenders
            ],
            "secondary_grade": round(secondary_grade, 1),
            "secondary_rank": defense.get("secondary_rank"),
            "front_grade": round(front_grade, 1),
            "front_rank": defense.get("front_rank"),
            "position_ppr_per_target_allowed": round(allowed_ppr_target, 2),
            "man_rate": defense.get("man_rate"),
            "zone_rate": defense.get("zone_rate"),
            "top_coverage": defense.get("top_coverage"),
            "dominant_coverage": dominant_name,
            "player_ppr_per_target_vs_dominant": round(_off_num(player_ppr_target), 2),
            "coverage_split_basis": split_basis,
            "pass_protection_grade": round(pass_pro_grade, 1),
            "pass_rush_grade": round(pass_rush_grade, 1),
            "pass_trench_score": pass_trench_score,
            "run_blocking_grade": round(run_block_grade, 1),
            "run_blocking_rank": line.get("run_blocking_rank"),
            "run_defense_grade": round(run_defense_grade, 1),
            "run_defense_rank": defense.get("run_defense_rank"),
            "opponent_yards_per_carry": defense.get("yards_per_carry"),
            "opponent_rush_epa_per_carry": defense.get("rush_epa_per_carry"),
            "opponent_stuff_rate": defense.get("stuff_rate"),
            "opponent_explosive_run_rate": defense.get("explosive_run_rate"),
            "run_trench_score": run_trench_score,
            "coverage_note": coverage_note,
            "defender_note": defender_note,
            "trench_note": trench_note,
        })

    prepared.sort(key=lambda row: (-_off_num(row.get("matchup_score")), -_off_num(row.get("projected_points")), row.get("name", "")))
    for rank, row in enumerate(prepared, 1):
        row["matchup_rank"] = rank
    return prepared, payload


@app.get("/weekly-matchups")
def weekly_matchups_page():
    return page("weekly_matchups.html", matchup_weeks=range(1, 19))


@app.get("/api/weekly-matchups")
def weekly_matchups_api():
    try:
        week = max(1, min(18, int(request.args.get("week") or 1)))
    except (TypeError, ValueError):
        week = 1
    position = str(request.args.get("position") or "ALL").upper()
    if position not in {"ALL", "RB", "WR", "TE"}:
        position = "ALL"
    rows, payload = _weekly_matchup_rows(week=week, position=position)
    offense_data_type = "actual" if any(str(row.get("offense_data_type") or "").lower() == "actual" for row in rows) else "projection"
    return jsonify(
        ok=True,
        week=week,
        position=position,
        count=len(rows),
        rows=rows,
        metadata={
            "model_version": "RB Model V2",
            "season": payload.get("matchup_season", 2026),
            "baseline_season": payload.get("season", 2025),
            "offense_data_type": offense_data_type,
            "source": payload.get("source") or "Gridiron IQ matchup model",
            "license_note": payload.get("license_note") or "",
            "line_projection_type": (
                "current-season performance"
                if int(payload.get("season") or 0) == int(payload.get("matchup_season") or 2026)
                else "latest-complete-season performance projection"
            ),
            "line_projection_note": (
                "The offensive-line run grade uses team rushing EPA, yards per carry, stuff rate and explosive-run rate. "
                "Before current-season samples are available it is a performance-based preseason projection; the weekly refresh automatically switches to current-season results."
            ),
            "assignment_note": "Primary defenders are likely matchups based on current roster role, snap share and coverage usage; they are not guaranteed shadow assignments.",
        },
    )


def _build_pr_position_rows_uncached(position="", limit=1000, platform="ESPN"):
    """
    Build the current fantasy-player universe from three reliable signals:

      1. a current NFL team assignment
      2. meaningful 2025 production
      3. a valid 2026 platform ADP ranking

    Sleeper's broad player database contains many historical records whose
    active flag is not sufficient by itself. Stats and projections enrich the
    pool, but inactive historical names cannot enter without a current signal.
    """
    position = str(position or "").upper()
    platform = str(platform or "ESPN").upper()

    stats_players = _stats_2025_snapshot().get("players", {}) or {}
    adp_payload = _platform_2026_adp_data(platform)
    adp_players = adp_payload.get("players", {}) or {}
    adp_source = adp_payload.get("source") or platform

    master_payload = _master_players_2026()
    master_players = (
        master_payload.get("players", {})
        if isinstance(master_payload, dict)
        else {}
    )

    directory = _pr_players()
    news_index = _player_news_index()
    news_players = news_index.get("players", {}) if isinstance(news_index, dict) else {}
    pool = {}

    def valid_position(value):
        pos = str(value or "").upper()
        if pos == "DST":
            pos = "DEF"
        return pos if pos in {"QB", "RB", "WR", "TE", "K", "DEF"} else ""

    def positive_number(value):
        try:
            return float(value or 0) > 0
        except Exception:
            return False

    def valid_adp(row):
        if not isinstance(row, dict):
            return False
        try:
            return 0 < float(row.get("adp", 999) or 999) < 999
        except Exception:
            return False

    def meaningful_stats(row):
        if not isinstance(row, dict):
            return False
        return (
            positive_number(row.get("games"))
            or positive_number(row.get("fantasy_points_ppr"))
            or positive_number(row.get("passing_yards"))
            or positive_number(row.get("rushing_yards"))
            or positive_number(row.get("receiving_yards"))
        )

    def add_or_update(norm, values, source):
        if not norm or not isinstance(values, dict):
            return
        record = pool.setdefault(norm, {
            "player_key": norm,
            "data_sources": set(),
        })
        record["data_sources"].add(source)

        for key, value in values.items():
            if value in (None, "", [], {}):
                continue
            # Current directory and master data have priority for team/bio.
            if key not in record or source in {"directory", "master"}:
                record[key] = value

    # Current directory records only enter when they have a current team, 2025
    # production, or valid ADP. The broad active flag alone is not trusted.
    for player_id, current in directory.items():
        if not isinstance(current, dict):
            continue

        name = str(
            current.get("full_name")
            or " ".join(
                value for value in [
                    current.get("first_name"),
                    current.get("last_name"),
                ] if value
            )
            or ""
        ).strip()
        if not name:
            continue

        norm = _pr_norm(name)
        stats = stats_players.get(norm, {}) or {}
        adp_row = adp_players.get(norm, {}) or {}

        pos = valid_position(
            current.get("position")
            or ((current.get("fantasy_positions") or [""])[0])
            or stats.get("position")
            or adp_row.get("position")
        )
        if not pos:
            continue

        team = str(
            current.get("team")
            or adp_row.get("team")
            or stats.get("team")
            or ""
        ).upper()

        has_current_team = bool(team and team not in {"FA", "N/A", "NONE"})
        has_stats = meaningful_stats(stats)
        has_adp = valid_adp(adp_row)

        if not (has_current_team or has_stats or has_adp):
            continue

        add_or_update(norm, {
            "player_id": str(player_id),
            "name": name,
            "position": pos,
            "team": team or "FA",
            "age": current.get("age"),
            "college": current.get("college"),
            "years_exp": current.get("years_exp"),
            "status": current.get("status"),
            "injury_status": current.get("injury_status"),
            "rookie": bool(current.get("rookie")),
        }, "directory")

    # Add every player who produced meaningful 2025 statistics. This recovers
    # legitimate players missing from the current directory.
    for norm, stats in stats_players.items():
        if not meaningful_stats(stats):
            continue

        pos = valid_position(stats.get("position"))
        if not pos:
            continue

        master = master_players.get(norm, {}) or {}
        adp_row = adp_players.get(norm, {}) or {}

        add_or_update(norm, {
            "name": stats.get("name") or master.get("name")
                or adp_row.get("name") or norm,
            "position": pos,
            "team": master.get("team") or adp_row.get("team")
                or stats.get("team") or "FA",
        }, "stats")

    # Add ranked 2026 players such as rookies who have no 2025 production.
    for norm, adp_row in adp_players.items():
        if not valid_adp(adp_row):
            continue

        master = master_players.get(norm, {}) or {}
        pos = valid_position(
            adp_row.get("position")
            or master.get("position")
        )
        if not pos:
            continue

        add_or_update(norm, {
            "player_id": str(adp_row.get("player_id") or ""),
            "name": adp_row.get("name") or adp_row.get("player_name")
                or master.get("name") or norm,
            "position": pos,
            "team": master.get("team") or adp_row.get("team") or "FA",
            "rookie": bool(master.get("rookie")),
        }, "adp")

    rows = []

    for norm, player in pool.items():
        stats = stats_players.get(norm, {}) or {}
        adp_row = adp_players.get(norm, {}) or {}
        master = master_players.get(norm, {}) or {}

        pos = valid_position(
            player.get("position")
            or master.get("position")
            or stats.get("position")
            or adp_row.get("position")
        )
        if not pos:
            continue
        if position and pos != position:
            continue

        try:
            adp = float(adp_row.get("adp", 999) or 999)
        except Exception:
            adp = 999.0

        projection = master.get("projection") or {}
        if not isinstance(projection, dict):
            projection = {}

        projected_stats = {
            "games": projection.get("games") or 17,
            "fantasy_points_ppr": (
                projection.get("ppr_points")
                or projection.get("fantasy_points_ppr")
                or projection.get("fantasy_points")
                or projection.get("points")
                or 0
            ),
            "passing_yards": projection.get("passing_yards")
                or projection.get("pass_yards") or 0,
            "passing_tds": projection.get("passing_tds")
                or projection.get("pass_tds") or 0,
            "interceptions": projection.get("interceptions") or 0,
            "carries": projection.get("carries")
                or projection.get("rush_attempts") or 0,
            "rushing_yards": projection.get("rushing_yards")
                or projection.get("rush_yards") or 0,
            "rushing_tds": projection.get("rushing_tds")
                or projection.get("rush_tds") or 0,
            "targets": projection.get("targets") or 0,
            "receptions": projection.get("receptions") or 0,
            "receiving_yards": projection.get("receiving_yards")
                or projection.get("rec_yards") or 0,
            "receiving_tds": projection.get("receiving_tds")
                or projection.get("rec_tds") or 0,
        }

        try:
            projection_total = float(
                projected_stats.get("fantasy_points_ppr", 0) or 0
            )
        except Exception:
            projection_total = 0.0

        if projection_total <= 0:
            projected_stats = _fast_2026_projection_from_2025(stats, pos)

        injury_status = player.get("injury_status") or master.get("injury_status") or ""
        news_row = news_players.get(norm, {}) if isinstance(news_players, dict) else {}
        recent_news = news_row.get("news", []) if isinstance(news_row, dict) else []
        recent_news = [item for item in recent_news if isinstance(item, dict)]
        latest_news = recent_news[0] if recent_news else {}

        rows.append({
            "player_key": norm,
            "player_id": player.get("player_id") or "",
            "name": player.get("name") or stats.get("name")
                or adp_row.get("name") or norm,
            "team": master.get("team") or player.get("team")
                or adp_row.get("team") or stats.get("team") or "FA",
            "position": pos,
            "adp": round(adp, 1) if 0 < adp < 999 else 999,
            "position_adp": adp_row.get("position_adp")
                or adp_row.get("positional_rank") or "",
            "adp_source": adp_source,
            "games": stats.get("games", 0),
            "fantasy_points": stats.get("fantasy_points", 0),
            "fantasy_points_ppr": stats.get(
                "fantasy_points_ppr",
                stats.get("fantasy_points", 0),
            ),
            "completions": stats.get("completions", 0),
            "attempts": stats.get("attempts", 0),
            "passing_yards": stats.get("passing_yards", 0),
            "passing_tds": stats.get("passing_tds", 0),
            "interceptions": stats.get("interceptions", 0),
            "carries": stats.get("carries", 0),
            "rushing_yards": stats.get("rushing_yards", 0),
            "rushing_tds": stats.get("rushing_tds", 0),
            "targets": stats.get("targets", 0),
            "receptions": stats.get("receptions", 0),
            "receiving_yards": stats.get("receiving_yards", 0),
            "receiving_tds": stats.get("receiving_tds", 0),
            "proj_2026_ppr": round(
                float(projected_stats.get("fantasy_points_ppr", 0) or 0),
                1,
            ),
            "projection_2026": projected_stats,
            "proj_2026_pass_yards": projected_stats.get("passing_yards", 0),
            "proj_2026_pass_tds": projected_stats.get("passing_tds", 0),
            "proj_2026_interceptions": projected_stats.get("interceptions", 0),
            "proj_2026_carries": projected_stats.get("carries", 0),
            "proj_2026_rush_yards": projected_stats.get("rushing_yards", 0),
            "proj_2026_rush_tds": projected_stats.get("rushing_tds", 0),
            "proj_2026_targets": projected_stats.get("targets", 0),
            "proj_2026_receptions": projected_stats.get("receptions", 0),
            "proj_2026_rec_yards": projected_stats.get("receiving_yards", 0),
            "proj_2026_rec_tds": projected_stats.get("receiving_tds", 0),
            "age": player.get("age") or master.get("age"),
            "college": player.get("college") or master.get("college"),
            "years_exp": player.get("years_exp") or master.get("years_exp"),
            "number": player.get("number") or master.get("number"),
            "depth_chart_position": player.get("depth_chart_position")
                or master.get("depth_chart_position") or "",
            "depth_chart_order": player.get("depth_chart_order")
                or master.get("depth_chart_order"),
            "depth_chart_source": player.get("depth_chart_source")
                or master.get("depth_chart_source") or "",
            "status": player.get("status") or master.get("status"),
            "injury_status": injury_status,
            "injury_body_part": master.get("injury_body_part") or "",
            "practice_participation": master.get("practice_participation") or "",
            "practice_description": master.get("practice_description") or "",
            "has_injury": _has_active_injury(injury_status),
            "has_news": bool(recent_news),
            "news_count": len(recent_news),
            "latest_news_title": latest_news.get("title") or "",
            "latest_news_summary": latest_news.get("summary") or "",
            "latest_news_published": latest_news.get("published") or "",
            "latest_news_source": latest_news.get("source") or "",
            "latest_news_url": latest_news.get("url") or "",
            "rookie": bool(player.get("rookie") or master.get("rookie")),
            "data_sources": sorted(player.get("data_sources", set())),
        })

    rows.sort(key=lambda row: (
        float(row.get("adp", 999)),
        -float(row.get("proj_2026_ppr", 0) or 0),
        row.get("name", ""),
    ))

    return rows[:max(1, min(int(limit or 5000), 5000))]



_PR_ROWS_CACHE = {}
_PR_ROWS_CACHE_TTL = 300
_PR_PROFILE_CACHE = {}
_PR_PROFILE_CACHE_TTL = 300


def _pr_data_signature(platform):
    """Return a lightweight signature for files that affect Player Research."""
    paths = [
        STATS_2025_SNAPSHOT_FILE,
        _local_platform_adp_path(platform),
        MASTER_PLAYERS_2026_FILE,
        BUNDLED_MASTER_PLAYERS_2026_FILE,
        PLAYER_CACHE_FILE,
        BUNDLED_PLAYER_CACHE_FILE,
        PLAYER_NEWS_INDEX_FILE,
        BUNDLED_PLAYER_NEWS_INDEX_FILE,
    ]
    signature = []
    for path in paths:
        try:
            stat = path.stat()
            signature.append((str(path), stat.st_mtime_ns, stat.st_size))
        except Exception:
            signature.append((str(path), 0, 0))
    return tuple(signature)


def _clear_pr_rows_cache():
    _PR_ROWS_CACHE.clear()
    _PR_PROFILE_CACHE.clear()


def _pr_position_rows(position="", limit=1000, platform="ESPN"):
    """
    Return cached merged player rows.

    The expensive merge is performed once per platform and repeated only when
    a source file changes or the five-minute cache expires.
    """
    position = str(position or "").upper()
    platform = str(platform or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    now = time.time()
    signature = _pr_data_signature(platform)
    cached = _PR_ROWS_CACHE.get(platform)

    if (
        cached
        and cached.get("signature") == signature
        and now - cached.get("created_at", 0) < _PR_ROWS_CACHE_TTL
    ):
        all_rows = cached.get("rows", [])
    else:
        all_rows = _build_pr_position_rows_uncached(
            "",
            limit=5000,
            platform=platform,
        )
        _PR_ROWS_CACHE[platform] = {
            "signature": signature,
            "created_at": now,
            "rows": all_rows,
        }

    if position:
        rows = [row for row in all_rows if row.get("position") == position]
    else:
        rows = list(all_rows)

    return rows[:max(1, min(int(limit or 1000), 5000))]



def player_research_adp_status():
    platform = str(request.args.get("platform") or _league_platform()).upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    data = _platform_2026_adp_data(platform)
    players = data.get("players", {})

    loaded_adp = sum(
        1 for value in players.values()
        if _fp_float(value.get("adp")) is not None and float(value.get("adp", 999)) < 999
    )

    return jsonify(
        ok=bool(players),
        platform=platform,
        status=data.get("status"),
        source=data.get("source"),
        updated_at=data.get("updated_at"),
        player_count=len(players),
        players_with_platform_adp=loaded_adp,
        api_configured=_fp_api_status()["configured"],
        required_environment_variable=FANTASYPROS_API_KEY_ENV,
        warning=data.get("warning", ""),
        warnings=data.get("warnings", []),
    )

@app.post("/api/player-research/adp/refresh")
def player_research_adp_refresh():
    body = request.get_json(silent=True) or {}
    platform = str(body.get("platform") or _league_platform()).upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    app.logger.info("Starting 2026 ADP update platform=%s", platform)

    try:
        if platform == "ESPN":
            # ESPN ADP is captured during the authenticated League Sync.
            # Reuse that result instead of storing or replaying ESPN cookies.
            data = _load_espn_native_adp()

            if not data or not data.get("players"):
                # Public sources remain a fallback for users who have not synced.
                data = _platform_2026_adp_data("ESPN", force=True)
            else:
                data = dict(data)
                data["status"] = "synced"
                data["source"] = (
                    data.get("source")
                    or "ESPN ADP captured during authenticated league sync"
                )

                platform_path = _local_platform_adp_path("ESPN")
                temp_path = platform_path.with_suffix(platform_path.suffix + ".tmp")
                temp_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temp_path.replace(platform_path)
        else:
            data = _platform_2026_adp_data("YAHOO", force=True)

        players = data.get("players", {}) or {}
        ranked_count = sum(
            1 for item in players.values()
            if 0 < float(item.get("adp", 999) or 999) < 999
        )

        _clear_pr_rows_cache()

        app.logger.info(
            "Completed ADP update platform=%s source=%s players=%s ranked=%s status=%s",
            platform,
            data.get("source"),
            len(players),
            ranked_count,
            data.get("status"),
        )

        return jsonify(
            ok=bool(players),
            season=2026,
            platform=platform,
            source=data.get("source"),
            status=data.get("status"),
            updated_at=data.get("updated_at"),
            player_count=len(players),
            players_with_platform_adp=ranked_count,
            message=(
                f"Loaded {ranked_count} ranked {platform} players."
                if ranked_count
                else "No ranked ADP players were returned."
            ),
            requires_espn_sync=(
                platform == "ESPN"
                and (not data or data.get("status") == "unavailable")
            ),
        )
    except Exception as exc:
        app.logger.exception("2026 ADP update failed platform=%s", platform)
        return jsonify(
            ok=False,
            platform=platform,
            error=str(exc),
            message=(
                "Sync ESPN again under League Sync. The authenticated sync "
                "will update the ESPN ADP dataset."
                if platform == "ESPN"
                else "Yahoo ADP could not be updated."
            ),
        ), 500

@app.get("/api/player-research/position")
def player_research_position():
    position = request.args.get("position", "").strip().upper()
    allowed = {"", "QB", "RB", "WR", "TE", "K", "DEF"}
    if position not in allowed:
        return jsonify(ok=False, error="Unsupported position."), 400

    platform = str(request.args.get("platform") or _league_platform()).upper()
    rows = _pr_position_rows(position, platform=platform)
    return jsonify(
        ok=True,
        position=position or "ALL",
        count=len(rows),
        players=rows,
    )


def _pr_projection(history, position):
    """
    Build a simple 17-game 2026 projection from recent production.
    Uses the most recent three seasons available, weighted toward 2025.
    """
    if not history:
        return {
            "method": "Insufficient historical data",
            "games": 17,
            "position": position,
        }

    recent = sorted(history, key=lambda x: x["season"], reverse=True)[:3]
    raw_weights = [0.60, 0.28, 0.12][:len(recent)]
    total_weight = sum(raw_weights)
    weights = [w / total_weight for w in raw_weights]

    fields = [
        "passing_yards", "passing_tds", "interceptions",
        "rushing_yards", "rushing_tds", "carries",
        "receptions", "targets", "receiving_yards", "receiving_tds",
        "fantasy_points", "fantasy_points_ppr",
    ]

    proj = {"games": 17, "position": position}
    for field in fields:
        per_game = 0.0
        for weight, season in zip(weights, recent):
            games = max(1, int(season.get("games") or 1))
            per_game += weight * (_pr_num(season.get(field)) / games)
        proj[field] = round(per_game * 17, 1)

    proj["method"] = "Gridiron IQ weighted recent-production model"
    return proj


def _pr_trend(history):
    if len(history) < 2:
        return {"direction": "Not enough data", "change_pct": 0}

    ordered = sorted(history, key=lambda x: x["season"])
    old, new = ordered[-2], ordered[-1]
    old_pts = old.get("fantasy_points_ppr") or old.get("fantasy_points") or 0
    new_pts = new.get("fantasy_points_ppr") or new.get("fantasy_points") or 0

    pct = round((new_pts - old_pts) / old_pts * 100, 1) if old_pts else 0
    direction = "Rising" if pct > 5 else "Declining" if pct < -5 else "Stable"
    return {"direction": direction, "change_pct": pct}


def _pr_profile(player_id):
    players = _pr_players()
    p = players.get(str(player_id))
    if not p:
        return None

    name = p.get("full_name") or " ".join(
        x for x in [p.get("first_name"), p.get("last_name")] if x
    )
    if not name:
        return None

    position = str(
        p.get("position")
        or ((p.get("fantasy_positions") or [""])[0])
        or ""
    ).upper()
    if position == "DST":
        position = "DEF"

    master = _player_research_master_row(name)
    stats_2025 = _player_research_stats_2025(name)
    history = _pr_history(name)
    projection = _player_research_projection_2026(name, master.get("position") or position)
    adp_info = _player_research_adp(name, _league_platform(), master.get("position") or position)

    bio = {
        "player_id": str(player_id),
        "name": name,
        "position": master.get("position") or position,
        "team": master.get("team") or p.get("team") or "FA",
        "number": master.get("number") or p.get("number"),
        "age": master.get("age") if master.get("age") is not None else p.get("age"),
        "college": master.get("college") or p.get("college"),
        "years_exp": master.get("years_exp") if master.get("years_exp") is not None else p.get("years_exp"),
        "status": master.get("status") or p.get("status"),
        "injury_status": master.get("injury_status") or p.get("injury_status"),
        "depth_chart_position": master.get("depth_chart_position") or p.get("depth_chart_position"),
        "depth_chart_order": master.get("depth_chart_order") or p.get("depth_chart_order"),
        "depth_chart_source": master.get("depth_chart_source") or "",
        "rookie": bool(master.get("rookie") or p.get("rookie")),
        "adp": adp_info.get("adp"),
        "position_adp": adp_info.get("position_adp"),
        "adp_source": adp_info.get("source"),
    }

    current_news = _player_research_news(name)
    injury = _player_research_injury(name)

    return {
        "bio": bio,
        "previous_year": stats_2025,
        "history": history,
        "projection": projection,
        "trend": _pr_trend(history),
        "news": current_news.get("news", []),
        "news_updated_at": current_news.get("updated_at", ""),
        "injury": injury,
        "data_notes": [
            "2026 current team: 2026 master player database.",
            "ADP: selected ESPN/Yahoo platform dataset.",
            "2025 stats: local historical stats snapshot.",
            "2026 projections: FantasyPros when available, otherwise Gridiron IQ fallback model.",
        ],
    }



def _player_research_profile_by_name(player_name, platform="ESPN"):
    norm = _pr_norm(player_name)
    platform = str(platform or "ESPN").upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"

    signature = (_pr_data_signature(platform), _career_stats_signature())
    cache_key = (platform, norm)
    cached = _PR_PROFILE_CACHE.get(cache_key)
    if (
        cached
        and cached.get("signature") == signature
        and time.time() - cached.get("created_at", 0) < _PR_PROFILE_CACHE_TTL
    ):
        return cached.get("profile")

    row = next(
        (
            item for item in _pr_position_rows("", limit=1000, platform=platform)
            if item.get("player_key") == norm
        ),
        None,
    )
    if not row:
        return None

    career = _career_stats_snapshot()
    history = _pr_history(row["name"], career)
    recent_news = _indexed_player_news(row["name"])
    news_index = _player_news_index()
    master = _player_research_master_row(row["name"])
    previous_year = dict(_player_research_stats_2025(row["name"]) or {})
    projection = dict(row.get("projection_2026") or {})
    projection.update({
        "season": 2026,
        "games": projection.get("games") or 17,
        "fantasy_points_ppr": row.get("proj_2026_ppr", 0),
        "passing_yards": row.get("proj_2026_pass_yards", 0),
        "passing_tds": row.get("proj_2026_pass_tds", 0),
        "interceptions": row.get("proj_2026_interceptions", 0),
        "carries": row.get("proj_2026_carries", 0),
        "rushing_yards": row.get("proj_2026_rush_yards", 0),
        "rushing_tds": row.get("proj_2026_rush_tds", 0),
        "targets": row.get("proj_2026_targets", 0),
        "receptions": row.get("proj_2026_receptions", 0),
        "receiving_yards": row.get("proj_2026_rec_yards", 0),
        "receiving_tds": row.get("proj_2026_rec_tds", 0),
        "method": projection.get("method") or "2026 source projection or Gridiron IQ fallback",
    })
    profile = {
        "bio": {
            key: row.get(key)
            for key in (
                "player_key", "player_id", "name", "position", "team",
                "age", "college", "years_exp", "status", "injury_status",
                "rookie", "adp", "position_adp", "number",
                "depth_chart_position", "depth_chart_order",
                "depth_chart_source",
            )
        },
        "adp_source": row.get("adp_source") or platform,
        "previous_year": previous_year,
        "history": history,
        "projection": projection,
        "trend": _pr_trend(history),
        "injury": {
            "status": row.get("injury_status") or "",
            "body_part": row.get("injury_body_part") or "",
            "practice": row.get("practice_participation") or "",
            "description": row.get("practice_description") or "",
            "source": "Current player database",
        },
        "news": recent_news,
        "news_updated_at": news_index.get("updated_at", ""),
        "news_available": bool(recent_news),
        "data_sources": row.get("data_sources", []),
        "career_loaded_seasons": career.get("loaded_seasons", []),
        "career_updated_at": career.get("updated_at", ""),
        "data_notes": [
            "Current team, injury and depth chart refresh daily.",
            f"ADP uses the selected {platform} dataset.",
            "2025 statistics are actual regular-season totals.",
            "2026 statistics are preseason projections until current-season actuals are published.",
            "Career history displays every imported season available for this player.",
        ],
    }
    _PR_PROFILE_CACHE[cache_key] = {
        "signature": signature,
        "created_at": time.time(),
        "profile": profile,
    }
    return profile


@app.get("/api/player-research/profile-by-name/<path:player_name>")
def player_research_profile_by_name_api(player_name):
    platform = str(request.args.get("platform") or _league_platform()).upper()
    if platform not in {"ESPN", "YAHOO"}:
        platform = "ESPN"
    profile = _player_research_profile_by_name(player_name, platform)
    if not profile:
        return jsonify(ok=False, error="Player not found."), 404
    response = jsonify(ok=True, profile=profile)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/player-research/profile/<player_id>")
def player_research_profile(player_id):
    profile = _pr_profile(player_id)
    if not profile:
        return jsonify(ok=False, error="Player not found."), 404
    return jsonify(ok=True, profile=profile)



from player_research_db import register as register_player_research_database
register_player_research_database(app)

from fantasy_analytics_routes import register as register_fantasy_analytics
register_fantasy_analytics(app)


@app.errorhandler(404)
def not_found(_): return page("error.html",code=404,message="Page not found."),404

@app.errorhandler(500)
def server_error(error):
    if request.path.startswith("/api/"):
        original = getattr(error, "original_exception", None)
        app.logger.exception("Unhandled API error on %s", request.path)
        return jsonify(
            ok=False,
            error=str(original or error),
            message="The server could not complete this request.",
            path=request.path,
        ), 500
    return page("error.html", code=500, message="Something went wrong. Check Render logs."), 500

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","8000")),debug=os.getenv("FLASK_DEBUG")=="1")
