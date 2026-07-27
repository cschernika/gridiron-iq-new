from __future__ import annotations

import json, os
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
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
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

def team_dict(team):
    roster = getattr(team, "roster", None) or []
    return {
        "team_name": str(getattr(team,"team_name","Unnamed Team")).strip(),
        "owner": str(getattr(team,"owner","") or ""),
        "wins": int(getattr(team,"wins",0) or 0),
        "losses": int(getattr(team,"losses",0) or 0),
        "ties": int(getattr(team,"ties",0) or 0),
        "points_for": round(float(getattr(team,"points_for",0) or 0),2),
        "roster_size": len(roster),
    }

def user_team(teams):
    return next((t for t in teams if "chad" in t["team_name"].lower()), None)

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

@app.get("/lineup-optimizer")
def lineup_optimizer(): return page("lineup.html")

@app.get("/waiver-assistant")
def waiver_assistant(): return page("waivers.html")

@app.get("/trade-analyzer")
def trade_analyzer(): return page("trade.html")

@app.get("/matchup-analyzer")
def matchup_analyzer(): return page("matchups.html")

@app.get("/league-intelligence")
def league_intelligence(): return page("league_intelligence.html")

@app.get("/reports")
def reports(): return page("reports.html")

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
        return jsonify(ok=True,message="ESPN league synced.",league=league,settings=settings,user_team=user_team(teams),teams=teams)
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

@app.post("/api/draft/pro/recommend")
def draft_recommend_api():
    data=request.get_json(silent=True) or {}; key=data.get("league_key") or "espn-gramps"; context=dict(CONTEXTS.get(key,CONTEXTS["espn-gramps"]))
    context["draft_slot"]=int(data.get("draft_slot") or context["draft_slot"]); context["round"]=int(data.get("round") or context["round"]); context["pick_in_round"]=int(data.get("pick_in_round") or context["pick_in_round"]); context["next_picks"]=next_picks(context["draft_slot"],context["teams"],context["round"])
    rec=recommendation(context,draft_state(key),context["round"],context["pick_in_round"],str(data.get("strategy") or "balanced"))
    return jsonify(ok=True,recommendation=rec,context=context)

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

@app.errorhandler(404)
def not_found(_): return page("error.html",code=404,message="Page not found."),404

@app.errorhandler(500)
def server_error(_): return page("error.html",code=500,message="Something went wrong. Check Render logs."),500

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","8000")),debug=os.getenv("FLASK_DEBUG")=="1")
