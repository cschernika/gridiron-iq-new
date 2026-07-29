from __future__ import annotations

import json, os, uuid
from collections import Counter
from datetime import datetime, timezone
from math import exp
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

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

def page(template, **ctx):
    snap = load_snapshot()
    connected = bool(snap)
    league = snap.get("league") if snap else None
    settings = snap.get("settings") if snap else None
    teams = snap.get("teams",[]) if snap else []
    return render_template(
        template, user=USER, connected=connected, league=league,
        league_settings=settings, teams=teams, user_team=user_team(teams),
        analytics=DEMO, **ctx
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

@app.get("/lineup-optimizer")
def lineup_optimizer(): return page("lineup.html")

@app.get("/waiver-assistant")
def waiver_assistant(): return page("waivers.html")

@app.get("/trade-analyzer")
def trade_analyzer(): return page("trade.html", league_data=league_summary())

@app.get("/matchup-analyzer")
def matchup_analyzer(): return page("matchups.html")

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
            adp_info = {
                "ok": bool(native_adp.get("players")),
                "player_count": len(native_adp.get("players", {})),
                "source": native_adp.get("source"),
                "updated_at": native_adp.get("updated_at"),
            }
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

def _manual_mock_store():
    try:
        if MANUAL_MOCK_FILE.exists():
            data = json.loads(MANUAL_MOCK_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}

def _save_manual_mock_store(store):
    MANUAL_MOCK_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")

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

    if master_players:
        players = []
        for norm, p in master_players.items():
            pos = str(p.get("position") or "").upper()
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
                "name": p.get("name"),
                "pos": pos,
                "team": p.get("team") or "FA",
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
    adp_data = _platform_2026_adp_data(platform)
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

def _manual_player_pick_score(mock, player):
    roster = _manual_user_roster(mock)
    counts = Counter(p["pos"] for p in roster)
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
    # Uses the Player Research/nflverse helpers when available.
    result = {name: 0.0 for name in names}
    try:
        if "_pr_rows" not in globals() or "_pr_aggregate" not in globals():
            return result
        rows = _pr_rows(2025)
        for name in names:
            stats = _pr_aggregate(rows, name) or {}
            result[name] = round(float(stats.get("fantasy_points_ppr") or stats.get("fantasy_points") or 0), 1)
    except Exception:
        pass
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

def _mock_platform_adp(context):
    platform = "YAHOO" if "YAHOO" in str(context.get("platform", "")).upper() else "ESPN"
    data = _platform_2026_adp_data(platform)
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

def _mock_ai_score(player, context, team_roster, overall_pick, round_no, total_rounds, style):
    platform, adp_data = _mock_platform_adp(context)
    adp_row = adp_data.get("players", {}).get(_pr_norm(player["name"]), {})
    platform_adp = adp_row.get("adp")
    try:
        platform_adp = float(platform_adp)
    except Exception:
        platform_adp = float(player.get("adp", 999))

    projection = float(player.get("projection", 0) or 0)
    prior = _stats_2025_for_name(player["name"]) or {}
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

def _mock_ai_pick(mock, order_row):
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

    scored = []
    for player in available:
        score, platform_adp = _mock_ai_score(
            player, context, roster, overall, round_no, total_rounds, style
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
    while True:
        row = _manual_current_order_row(mock)
        if row is None:
            mock["status"] = "complete"
            break

        if int(row["slot"]) == int(mock["draft_slot"]):
            mock["status"] = "your_pick"
            break

        pick = _mock_ai_pick(mock, row)
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

            context = dict(CONTEXTS.get(mock["league_key"], CONTEXTS["espn-gramps"]))
            roster = [
                p for p in mock.get("picks", [])
                if int(p.get("slot", 0)) == int(mock["draft_slot"])
            ]
            scored = []
            for player in available:
                score, platform_adp = _mock_ai_score(
                    player, context, roster, row["overall"], row["round"],
                    mock["rounds"], "balanced"
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
            pick = _mock_ai_pick(mock, row)
            if not pick:
                mock["status"] = "complete"
                break
            mock.setdefault("picks", []).append(pick)

    _manual_finalize_if_complete(mock)
    _manual_mock_save(mock)
    return jsonify(ok=True, mock=mock, grade=mock.get("grade"))

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

    return jsonify(ok=True, mock=mock, player_pool_count=len(mock.get("player_pool", [])))


@app.get("/api/mock-draft/manual/<mock_id>/board")
def manual_mock_board(mock_id):
    mock = _manual_mock_get(mock_id)
    if not mock:
        return jsonify(ok=False, error="Mock draft not found."), 404

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

    return jsonify(ok=True, mock=mock, teams=list(teams.values()))

@app.get("/api/mock-draft/manual/<mock_id>")
def manual_mock_state(mock_id):
    mock = _manual_mock_get(mock_id)
    if not mock:
        return jsonify(ok=False, error="Mock draft not found."), 404

    row = _manual_current_order_row(mock)
    available = _manual_available(mock)
    platform = "YAHOO" if "YAHOO" in str(mock.get("platform", "")).upper() else "ESPN"
    platform_adp = _pr_adp_lookup(platform)

    # Apply the ADP that matches the selected league platform.
    scored = []
    for p in available:
        item = dict(p)
        item["adp"] = platform_adp.get(_pr_norm(item["name"]), item.get("adp", 999))
        item["adp_source"] = platform
        item["pick_score"] = _manual_player_pick_score(mock, item)
        scored.append(item)
    # Draft board is ranked by ADP (lowest/best ADP first).
    # Pick Score remains visible as Gridiron IQ's roster-aware recommendation.
    scored.sort(key=lambda x: (float(x.get("adp", 9999)), int(x.get("rank", 9999))))

    return jsonify(
        ok=True,
        mock=mock,
        current_pick=row,
        roster=_manual_user_roster(mock),
        available=scored,
        grade=_manual_grade(mock),
        pick_report=_manual_pick_report(mock),
    )

@app.post("/api/mock-draft/manual/<mock_id>/pick")
def manual_mock_pick(mock_id):
    mock = _manual_mock_get(mock_id)
    if not mock:
        return jsonify(ok=False, error="Mock draft not found."), 404

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
    platform_adp = _pr_adp_lookup(platform)
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

    return jsonify(ok=True, mock=mock, grade=mock.get("grade"))

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

    return jsonify(ok=True, mock=mock)

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

        score = (
            58
            + production_signal
            + history_signal
            + adp_signal
            + need * 0.10
            + scarcity_num * 0.05
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
        f"chance of surviving to your next pick: {best['survival_probability']}%."
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
        "rationale": rationale,
        "next_best": scored[1:4],
    }

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
import re
import time

PLAYER_CACHE_FILE = DATA_DIR / "sleeper_players_cache.json"
PLAYER_CACHE_TTL = 24 * 60 * 60

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
    Prefer the 2026 master database after it has been refreshed.
    Fall back to cached/live Sleeper so Player Research remains usable.
    """
    try:
        master = _master_players_2026()
        if master.get("players"):
            out = {}
            for idx, p in enumerate(master["players"].values(), 1):
                out[str(p.get("sleeper_id") or p.get("fantasypros_id") or idx)] = {
                    "full_name": p.get("name"),
                    "position": p.get("position"),
                    "fantasy_positions": p.get("fantasy_positions") or [p.get("position")],
                    "team": p.get("team") or "FA",
                    "status": p.get("status") or "Active",
                    "age": p.get("age"),
                    "years_exp": p.get("years_exp"),
                    "college": p.get("college"),
                    "injury_status": p.get("injury_status"),
                    "rookie": p.get("rookie", False),
                }
            return out
    except Exception:
        pass

    try:
        if PLAYER_CACHE_FILE.exists() and (time.time() - PLAYER_CACHE_FILE.stat().st_mtime) < PLAYER_CACHE_TTL:
            cached = json.loads(PLAYER_CACHE_FILE.read_text(encoding="utf-8"))
            if cached:
                return cached
    except Exception:
        pass

    try:
        r = requests.get("https://api.sleeper.app/v1/players/nfl?active=true", timeout=30)
        r.raise_for_status()
        data = r.json()
        if data:
            try:
                PLAYER_CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass
            return data
    except Exception:
        pass

    try:
        if PLAYER_CACHE_FILE.exists():
            cached = json.loads(PLAYER_CACHE_FILE.read_text(encoding="utf-8"))
            if cached:
                return cached
    except Exception:
        pass

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
        "passing_yards": total("passing_yards"),
        "passing_tds": total("passing_tds"),
        "interceptions": total("interceptions"),
        "rushing_yards": total("rushing_yards"),
        "rushing_tds": total("rushing_tds"),
        "carries": total("carries") or total("rushing_attempts"),
        "receptions": total("receptions"),
        "targets": total("targets"),
        "receiving_yards": total("receiving_yards"),
        "receiving_tds": total("receiving_tds"),
        "fantasy_points": total("fantasy_points"),
        "fantasy_points_ppr": total("fantasy_points_ppr"),
    }

def _pr_history(player_name):
    """
    Request-safe career history.

    2025 comes from the local JSON snapshot.
    Older seasons are displayed only if their CSV files are already cached.
    No historical download is started while a user waits for the player page.
    """
    out = []

    for season in (2022, 2023, 2024):
        cache = DATA_DIR / f"player_stats_{season}.csv"
        if not cache.exists():
            continue
        try:
            rows = list(csv.DictReader(io.StringIO(cache.read_text(encoding="utf-8"))))
            stats = _pr_aggregate(rows, player_name)
            if stats:
                out.append({"season": season, **stats})
        except Exception:
            continue

    stats_2025 = _stats_2025_for_name(player_name)
    if stats_2025:
        clean = {
            k: v for k, v in stats_2025.items()
            if k not in {"name", "player_id", "team", "position"}
        }
        out.append({"season": 2025, **clean})

    return out


STATS_2025_SNAPSHOT_FILE = DATA_DIR / "nfl_player_stats_2025.json"

STATS_2025_FIELDS = (
    "games", "completions", "attempts", "passing_yards", "passing_tds",
    "interceptions", "carries", "rushing_yards", "rushing_tds",
    "targets", "receptions", "receiving_yards", "receiving_tds",
    "fantasy_points", "fantasy_points_ppr"
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

    if not STATS_2025_SNAPSHOT_FILE.exists():
        return empty

    try:
        raw = STATS_2025_SNAPSHOT_FILE.read_text(encoding="utf-8")
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
            damaged = STATS_2025_SNAPSHOT_FILE.with_suffix(
                STATS_2025_SNAPSHOT_FILE.suffix + ".invalid"
            )
            if damaged.exists():
                damaged.unlink()
            STATS_2025_SNAPSHOT_FILE.replace(damaged)
        except Exception:
            pass
        return empty


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



# ============================================================
# 2026 MASTER PLAYER DATABASE + REFRESH ENGINE
# ============================================================
MASTER_PLAYERS_2026_FILE = DATA_DIR / "nfl_players_2026.json"

def _master_players_2026():
    try:
        if MASTER_PLAYERS_2026_FILE.exists():
            payload = json.loads(MASTER_PLAYERS_2026_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
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
PLAYER_NEWS_CACHE_TTL = 15 * 60

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
        timeout=25,
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

def _player_research_news(player_name):
    cache = _news_cache_path(player_name)

    try:
        if cache.exists() and (time.time() - cache.stat().st_mtime) < PLAYER_NEWS_CACHE_TTL:
            return json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        pass

    master = _player_research_master_row(player_name)
    fp_id = master.get("fantasypros_id")
    warnings = []
    news = []

    queries = []
    if fp_id:
        queries.append({"player_id": fp_id, "limit": 15})
    queries.append({"player": player_name, "limit": 15})
    queries.append({"limit": 100})

    for params in queries:
        try:
            payload = _fp_public_get("nfl/news", params=params)
            rows = _extract_fp_list(payload, ("news","articles","results","data"))
            matched = [
                _normalize_player_news(row)
                for row in rows
                if _player_news_matches(row, player_name, fp_id)
            ]
            if matched:
                news = matched[:10]
                break
        except Exception as exc:
            warnings.append(str(exc))

    result = {
        "player": player_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "news": news,
        "warnings": warnings[-2:],
    }

    try:
        cache.write_text(json.dumps(result, indent=2), encoding="utf-8")
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
    return jsonify(ok=True, **_player_research_news(player_name))

def _player_research_data_status(platform="ESPN"):
    platform = str(platform or "ESPN").upper()
    master = _master_players_2026()
    stats = _stats_2025_snapshot()
    adp = _platform_2026_adp_data(platform)

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
    }


@app.get("/api/player-research/data-status")
def player_research_data_status_api():
    platform = str(request.args.get("platform") or _league_platform()).upper()
    return jsonify(ok=True, **_player_research_data_status(platform))


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

    return page(
        "player_research.html",
        selected_position=selected_position,
        draft_leagues=draft_leagues(),
        active_league_key=league_key,
        active_platform=platform,
        active_scoring=context.get("scoring", ""),
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
        limit = min(2500, max(1, int(request.args.get("limit", 2000))))
    except Exception:
        limit = 2000

    rows = _pr_position_rows(position, limit=min(limit, 1000), platform=platform)

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
    rows = rows[:limit]

    stats = _stats_2025_snapshot()
    adp = _platform_2026_adp_data(platform)
    counts = Counter(row.get("position") for row in rows)

    return jsonify(
        ok=True,
        platform=platform,
        selected_position=position or "ALL",
        count=len(rows),
        position_counts=dict(counts),
        players=rows,
        sources={
            "stats_2025": stats.get("source", ""),
            "projections_2026": "FantasyPros or Gridiron IQ history-based projection",
            "adp_2026": adp.get("source", ""),
        },
        updated_at={
            "stats_2025": stats.get("updated_at", ""),
            "adp_2026": adp.get("updated_at", ""),
        },
        warnings=[x for x in [adp.get("warning", "")] if x],
    )

@app.get("/api/diagnostics/player-research")
def diagnostics_player_research():
    platform = _league_platform()
    directory = _pr_players()
    stats = _stats_2025_snapshot()
    adp = _platform_2026_adp_data(platform)
    return jsonify(
        ok=bool(directory),
        fast_mode=True,
        player_directory_count=len(directory),
        stats_2025_count=len(stats.get("players", {})),
        adp_player_count=len(adp.get("players", {})),
        platform=platform,
        adp_source=adp.get("source"),
        note="Player Research no longer parses historical CSV files during page load.",
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

    urls = [
        # ESPN default PPR player pool.
        f"https://fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3?view=kona_player_info",
    ]
    if league_id:
        urls.append(
            f"https://fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{int(league_id)}?view=kona_player_info"
        )

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
            payload = response.json()

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

                if adp in (None, ""):
                    continue

                try:
                    adp = round(float(adp), 2)
                except Exception:
                    continue

                rank = None
                rank_sets = p.get("draftRanksByRankType") or {}
                for rank_key in ("PPR", "STANDARD"):
                    rank_info = rank_sets.get(rank_key) or {}
                    if rank_info.get("rank") is not None:
                        try:
                            rank = int(rank_info["rank"])
                        except Exception:
                            pass
                        break

                players[_pr_norm(name)] = {
                    "name": name,
                    "adp": adp,
                    "rank": rank,
                    "position_adp": "",
                    "source": "ESPN",
                }

            if players:
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
      1. saved platform dataset
      2. ESPN native ADP for ESPN leagues
      3. FantasyPros API
      4. last successful saved dataset
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
            if not force:
                payload["status"] = payload.get("status") or "local"
                return payload
    except Exception:
        cached = None

    errors = []

    # ESPN's own market ADP does not require FantasyPros.
    if platform == "ESPN":
        try:
            native = _fetch_espn_native_adp(season=2026)
            if native.get("players"):
                path.write_text(json.dumps(native, indent=2), encoding="utf-8")
                return native
        except Exception as exc:
            errors.append(f"ESPN native ADP: {exc}")

        try:
            native_cached = _load_espn_native_adp()
            if native_cached and native_cached.get("players"):
                native_cached["status"] = "cached"
                native_cached["warning"] = " | ".join(errors)
                path.write_text(json.dumps(native_cached, indent=2), encoding="utf-8")
                return native_cached
        except Exception as exc:
            errors.append(f"ESPN native cache: {exc}")

    # FantasyPros remains available when the API key is configured.
    try:
        return _fp_build_platform_dataset(platform)
    except Exception as exc:
        errors.append(f"FantasyPros: {exc}")

    if cached and cached.get("players"):
        cached["status"] = "cached"
        cached["warning"] = " | ".join(errors)
        return cached

    return {
        "season": 2026,
        "platform": platform,
        "scoring": "PPR" if platform == "ESPN" else "Half PPR",
        "source": "No 2026 ADP source available",
        "updated_at": "",
        "players": {},
        "status": "unavailable",
        "warning": " | ".join(errors),
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

def _pr_position_rows(position="", limit=500, platform="ESPN"):
    position = str(position or "").upper()
    platform = str(platform or "ESPN").upper()

    stats_snapshot = _stats_2025_snapshot()
    stats_players = stats_snapshot.get("players", {})
    adp_snapshot = _platform_2026_adp_data(platform)
    adp_players = adp_snapshot.get("players", {})

    master = _master_players_2026()
    master_players = master.get("players", {}) if isinstance(master, dict) else {}
    directory = _pr_players()

    pool = {}
    if master_players:
        pool.update({
            norm: player
            for norm, player in master_players.items()
            if isinstance(player, dict)
        })
    else:
        for _, player in directory.items():
            if not isinstance(player, dict):
                continue
            name = (
                player.get("full_name")
                or " ".join(
                    part for part in [
                        player.get("first_name"),
                        player.get("last_name"),
                    ] if part
                )
            ).strip()
            if not name:
                continue
            pool[_pr_norm(name)] = {
                "name": name,
                "position": player.get("position")
                or ((player.get("fantasy_positions") or [""])[0]),
                "team": player.get("team") or "FA",
                "rookie": bool(player.get("rookie")),
            }

    rows = []
    for norm, player in pool.items():
        name = str(player.get("name") or player.get("full_name") or "").strip()
        if not name:
            continue

        pos = str(player.get("position") or player.get("pos") or "").upper()
        if pos == "DST":
            pos = "DEF"
        if pos not in {"QB", "RB", "WR", "TE", "K", "DEF"}:
            continue
        if position and pos != position:
            continue

        stats = stats_players.get(norm, {}) or {}
        adp_row = adp_players.get(norm, {}) or {}

        try:
            adp = float(adp_row.get("adp", 999) or 999)
        except Exception:
            adp = 999.0

        projection_data = player.get("projection") or {}
        if isinstance(projection_data, dict):
            projected_points = (
                projection_data.get("ppr_points")
                or projection_data.get("fantasy_points")
                or projection_data.get("points")
                or 0
            )
        else:
            projected_points = projection_data or 0

        try:
            projected_points = float(projected_points or 0)
        except Exception:
            projected_points = 0.0

        if projected_points <= 0:
            try:
                projected_points = float(
                    _player_research_projection_2026(name, pos) or 0
                )
            except Exception:
                projected_points = 0.0

        rows.append({
            "name": name,
            "team": player.get("team") or stats.get("team") or "FA",
            "position": pos,
            "adp": round(adp, 1) if adp < 999 else 999,
            "position_adp": adp_row.get("position_adp")
                or adp_row.get("positional_rank")
                or "",
            "games": stats.get("games", 0),
            "fantasy_points": stats.get("fantasy_points", 0),
            "fantasy_points_ppr": stats.get(
                "fantasy_points_ppr",
                stats.get("fantasy_points", 0),
            ),
            "passing_yards": stats.get("passing_yards", 0),
            "passing_tds": stats.get("passing_tds", 0),
            "interceptions": stats.get("interceptions", 0),
            "rushing_yards": stats.get("rushing_yards", 0),
            "rushing_tds": stats.get("rushing_tds", 0),
            "receptions": stats.get("receptions", 0),
            "receiving_yards": stats.get("receiving_yards", 0),
            "receiving_tds": stats.get("receiving_tds", 0),
            "targets": stats.get("targets", 0),
            "proj_2026_ppr": round(projected_points, 1),
            "rookie": bool(player.get("rookie")),
        })

    rows.sort(key=lambda row: (
        float(row.get("adp", 999)),
        -float(row.get("proj_2026_ppr", 0) or 0),
        row.get("name", ""),
    ))
    return rows[:max(1, min(int(limit or 500), 1000))]


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

    data = _platform_2026_adp_data(platform, force=True)

    return jsonify(
        ok=bool(data.get("players")),
        season=2026,
        platform=platform,
        scoring=data.get("scoring"),
        source=data.get("source"),
        status=data.get("status"),
        updated_at=data.get("updated_at"),
        player_count=len(data.get("players", {})),
        api_configured=_fp_api_status()["configured"],
        warning=data.get("warning", ""),
        warnings=data.get("warnings", []),
    )

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


@app.get("/api/player-research/profile/<player_id>")
def player_research_profile(player_id):
    profile = _pr_profile(player_id)
    if not profile:
        return jsonify(ok=False, error="Player not found."), 404
    return jsonify(ok=True, profile=profile)


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