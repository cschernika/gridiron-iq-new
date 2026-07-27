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

@app.get("/")
def home(): return redirect(url_for("dashboard"))

@app.get("/app")
@app.get("/dashboard")
def dashboard(): return page("dashboard.html")

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
