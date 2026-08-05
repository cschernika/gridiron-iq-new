{% extends "base.html" %}
{% block title %}AI Mock Draft Simulator | Gridiron IQ{% endblock %}
{% block body %}
<style>
.ms{--p:#5d3df5;--t:#132033;--m:#68778e;--l:#dfe5ef;--g:#16a34a;color:var(--t)}
.ms-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;margin-bottom:16px}.ms-k{color:var(--p);font-size:11px;font-weight:900;letter-spacing:.09em}.ms h1{font-size:36px;margin:5px 0}.ms p{color:var(--m)}
.ms-grid{display:grid;grid-template-columns:.7fr 1.3fr;gap:16px}.ms-card{background:#fff;border:1px solid var(--l);border-radius:16px;padding:18px}.ms-form{display:grid;grid-template-columns:1fr 1fr;gap:10px}.ms-form label{font-size:10px;color:var(--m);font-weight:800}.ms-form input,.ms-form select{width:100%;box-sizing:border-box;border:1px solid var(--l);border-radius:9px;padding:10px;background:#fff;margin-top:5px}
.ms-btn{border:1px solid var(--l);border-radius:10px;padding:10px 13px;background:#fff;font-weight:900;cursor:pointer}.ms-btn.primary{border:0;background:linear-gradient(90deg,#2d70f4,#6038f3);color:#fff}.ms-full{width:100%;margin-top:12px}
.ms-live{display:none;grid-template-columns:1.45fr .75fr;gap:16px;margin-top:16px}.ms-tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}.ms-search{flex:1;min-width:180px;border:1px solid var(--l);border-radius:9px;padding:9px}.ms-tabs{display:flex;gap:6px}.ms-tabs button{border:0;border-radius:999px;padding:7px 10px;background:#f0f3f8;font-weight:800}.ms-tabs button.active{background:var(--p);color:#fff}
.ms-table-wrap{overflow:auto;max-height:610px}.ms-table{width:100%;border-collapse:collapse;min-width:700px}.ms-table th,.ms-table td{padding:9px 7px;border-bottom:1px solid #e7eaf1;text-align:left;font-size:10px}.ms-table th{font-size:8px;color:var(--m);position:sticky;top:0;background:#fff}.ms-pick{border:0;border-radius:8px;background:var(--p);color:#fff;padding:7px 9px;font-weight:900}
.ms-stat{background:#f7f8fc;border-radius:11px;padding:11px;margin-bottom:10px}.ms-stat span,.ms-stat strong{display:block}.ms-stat span{font-size:9px;color:var(--m)}.ms-stat strong{font-size:22px;margin-top:3px}.ms-roster{width:100%;border-collapse:collapse}.ms-roster td,.ms-roster th{padding:7px 4px;border-bottom:1px solid #e8ebf1;font-size:10px;text-align:left}
.ms-saved{margin-top:16px}.ms-saved-row{display:grid;grid-template-columns:1fr 130px 80px;gap:10px;padding:10px;border-bottom:1px solid #e7eaf1;font-size:11px}.ms-link{color:#4637e5;font-weight:900;text-decoration:none}

.ms-board-card{margin-top:16px;background:#fff;border:1px solid var(--l);border-radius:16px;padding:16px}
.ms-board-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-end;margin-bottom:12px}
.ms-board-head h2{margin:4px 0 0;font-size:21px}
.ms-board-scroll{overflow:auto;border:1px solid #e7eaf1;border-radius:12px}
.ms-board{display:grid;gap:0;min-width:1500px}
.ms-team-col{border-right:1px solid #e7eaf1;background:#fff;min-width:118px}
.ms-team-col.you{background:#f7f4ff}
.ms-team-head{position:sticky;top:0;z-index:2;background:#f7f8fb;border-bottom:1px solid #e3e7ee;padding:9px 8px;min-height:58px}
.ms-team-col.you .ms-team-head{background:#eee9ff}
.ms-team-head b,.ms-team-head span{display:block}
.ms-team-head b{font-size:10px}
.ms-team-head span{font-size:8px;color:var(--m);margin-top:2px;text-transform:uppercase}
.ms-board-pick{padding:8px;border-bottom:1px solid #edf0f5;min-height:58px}
.ms-board-pick.current{outline:2px solid var(--p);outline-offset:-2px;background:#f8f6ff}
.ms-board-pick .rd{font-size:8px;color:var(--m)}
.ms-board-pick .pn{font-size:10px;font-weight:900;margin-top:3px;line-height:1.2}
.ms-board-pick .pp{font-size:8px;color:var(--m);margin-top:2px}
.ms-board-empty{padding:8px;min-height:58px;border-bottom:1px solid #edf0f5;color:#b0bac7;font-size:9px}
.ms-board-legend{font-size:10px;color:var(--m)}

@media(max-width:900px){.ms-grid,.ms-live{grid-template-columns:1fr}}@media(max-width:620px){.ms-form{grid-template-columns:1fr}}
</style>
<div class="ms">
<div class="ms-head"><div><div class="ms-k">AI DRAFT SIMULATOR</div><h1>Mock Draft Lab</h1><p>Choose ESPN or Yahoo, select any draft slot, and draft against 11 AI-controlled teams with different draft strategies, roster needs and platform ADP.</p></div></div>

<div id="setup" class="ms-grid">
<div class="ms-card"><div class="ms-k">DRAFT SETTINGS</div><h2>Start a Mock Draft</h2>
<div class="ms-form">
<label>League<select id="league">{% for item in draft_leagues %}<option value="{{ item.key }}" {% if item.key == active_league_key %}selected{% endif %}>{{ item.name }} — {{ item.platform }}</option>{% endfor %}</select></label>
<label>Draft Position<input id="slot" type="number" min="1" max="{{ mock_context.teams }}" value="{{ mock_context.draft_slot }}"></label>
<label>Teams<input id="teams" value="{{ mock_context.teams }}" disabled></label>
<label>Rounds<select id="rounds"><option>10</option><option selected>12</option><option>15</option></select></label>
</div>
<button id="start" class="ms-btn primary ms-full">Start AI Mock Draft</button>
</div>
<div class="ms-card"><div class="ms-k">AI OPPONENTS</div><h2>11 Different Draft Personalities</h2><p>Opponent teams use a mix of balanced, RB-heavy, WR-heavy, Zero-RB, Hero-RB, early-QB, late-QB and best-player approaches. Picks also account for platform ADP, roster construction, 2025 production and 2026 projection.</p><p>The AI intentionally adds controlled randomness so repeated mocks do not produce the exact same board.</p></div>
</div>

<div id="live" class="ms-live">
<div class="ms-card">
<div class="ms-tools"><input id="search" class="ms-search" placeholder="Search available players..."><div id="tabs" class="ms-tabs"><button class="active" data-pos="">All</button><button data-pos="QB">QB</button><button data-pos="RB">RB</button><button data-pos="WR">WR</button><button data-pos="TE">TE</button></div></div>
<div class="ms-table-wrap"><table class="ms-table"><thead><tr><th>Player</th><th>Pos</th><th>NFL</th><th>Platform ADP</th><th>Proj</th><th>Pick Score</th><th></th></tr></thead><tbody id="players"></tbody></table></div>
</div>
<div class="ms-card">
<div class="ms-stat"><span>ON THE CLOCK</span><strong id="pick">—</strong></div>
<div class="ms-stat"><span>LIVE GRADE</span><strong id="grade">—</strong></div>
<button id="auto-rest" class="ms-btn ms-full">AI Auto-Draft My Remaining Picks</button>
<h3>Your Roster</h3><table class="ms-roster"><tbody id="roster"></tbody></table>
<div id="complete" style="display:none"><a id="review" class="ms-btn primary ms-full" href="#">Review Completed Draft</a></div>
</div>
</div>


<div id="draft-board-card" class="ms-board-card" style="display:none">
  <div class="ms-board-head">
    <div>
      <div class="ms-k">LIVE DRAFT BOARD</div>
      <h2>All Teams Picking Beside You</h2>
    </div>
    <div class="ms-board-legend">Your team is highlighted. Each column is one draft slot.</div>
  </div>
  <div class="ms-board-scroll">
    <div id="draft-board" class="ms-board"></div>
  </div>
</div>

<div class="ms-card ms-saved"><div class="ms-k">SAVED MOCKS</div><h2>Previous Drafts</h2>
{% for m in manual_mocks %}<div class="ms-saved-row"><span>{{ m.league_name }} · Slot {{ m.draft_slot }} · {{ m.status }}</span><span>Grade {{ (m.grade or {}).get('overall','—') }}</span><a class="ms-link" href="/mock-draft/review/{{ m.id }}">Review →</a></div>{% else %}<p>No saved drafts yet.</p>{% endfor %}
</div>
</div>
<script>
(()=>{
  const $ = id => document.getElementById(id);
  let id = null, available = [], pos = "";

  async function api(url,opt={}){
    const r=await fetch(url,{headers:{"Content-Type":"application/json"},...opt});
    const d=await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(d.error||"Request failed");
    return d;
  }

  $("start").onclick=async()=>{
    const d=await api("/api/mock-draft/manual/start",{
      method:"POST",
      body:JSON.stringify({
        league_key:$("league").value,
        draft_slot:+$("slot").value,
        rounds:+$("rounds").value
      })
    });
    id=d.mock.id;
    $("setup").style.display="none";
    $("live").style.display="grid";
    $("draft-board-card").style.display="block";
    await refresh();
  };

  async function refresh(){
    const d=await api(`/api/mock-draft/manual/${id}`);
    available=d.available||[];
    renderPlayers();

    $("grade").textContent=(d.grade||{}).overall||"—";
    $("pick").textContent=d.current_pick
      ? `Round ${d.current_pick.round} · Pick #${d.current_pick.overall}`
      : "Draft Complete";

    $("roster").innerHTML=(d.roster||[]).map(p=>`
      <tr><td>${p.round}</td><td><b>${p.name}</b></td><td>${p.pos}</td></tr>
    `).join("");

    if(d.mock.status==="complete"){
      $("complete").style.display="block";
      $("review").href=`/mock-draft/review/${id}`;
    }

    await renderBoard(d.current_pick);
  }

  async function renderBoard(currentPick){
    if(!id) return;
    const d=await api(`/api/mock-draft/manual/${id}/board`);
    const teams=d.teams||[];
    const rounds=Number((d.mock||{}).rounds||12);

    const bySlot={};
    teams.forEach(t=>{
      bySlot[t.slot]=t;
      t.pickByRound={};
      (t.roster||[]).forEach(p=>{t.pickByRound[p.round]=p;});
    });

    $("draft-board").style.gridTemplateColumns=`repeat(${teams.length}, minmax(118px,1fr))`;
    $("draft-board").innerHTML=teams.map(team=>{
      let cells="";
      for(let round=1;round<=rounds;round++){
        const pick=team.pickByRound[round];
        const isCurrent=currentPick &&
          Number(currentPick.slot)===Number(team.slot) &&
          Number(currentPick.round)===round;

        if(pick){
          cells+=`
            <div class="ms-board-pick ${isCurrent?"current":""}">
              <div class="rd">R${pick.round} · #${pick.overall}</div>
              <div class="pn">${pick.player}</div>
              <div class="pp">${pick.pos} · ${pick.team}</div>
            </div>`;
        }else{
          cells+=`
            <div class="ms-board-empty ${isCurrent?"current":""}">
              R${round}${isCurrent?" · ON CLOCK":""}
            </div>`;
        }
      }

      return `
        <div class="ms-team-col ${team.label==="Your Team"?"you":""}">
          <div class="ms-team-head">
            <b>${team.label}</b>
            <span>Slot ${team.slot}${team.strategy && team.strategy!=="you" ? " · "+team.strategy : ""}</span>
          </div>
          ${cells}
        </div>`;
    }).join("");
  }

  function renderPlayers(){
    const q=$("search").value.toLowerCase();
    $("players").innerHTML=available
      .filter(p=>(!q||p.name.toLowerCase().includes(q))&&(!pos||p.pos===pos))
      .slice(0,160)
      .map(p=>`
        <tr>
          <td><b>${p.name}</b></td>
          <td>${p.pos}</td>
          <td>${p.team}</td>
          <td>${p.adp}</td>
          <td>${p.projection}</td>
          <td>${p.pick_score}</td>
          <td><button class="ms-pick" data-p="${p.name.replace(/"/g,'&quot;')}">Draft</button></td>
        </tr>`).join("");

    document.querySelectorAll(".ms-pick").forEach(b=>b.onclick=async()=>{
      b.disabled=true;
      try{
        await api(`/api/mock-draft/manual/${id}/pick`,{
          method:"POST",
          body:JSON.stringify({player:b.dataset.p})
        });
        await refresh();
      }catch(e){
        alert(e.message);
        b.disabled=false;
      }
    });
  }

  $("search").oninput=renderPlayers;

  document.querySelectorAll("#tabs button").forEach(b=>b.onclick=()=>{
    document.querySelectorAll("#tabs button").forEach(x=>x.classList.remove("active"));
    b.classList.add("active");
    pos=b.dataset.pos;
    renderPlayers();
  });

  $("auto-rest").onclick=async()=>{
    if(!confirm("Let Gridiron IQ AI make all of your remaining picks?")) return;
    await api("/api/mock-draft/manual/autodraft-rest",{
      method:"POST",
      body:JSON.stringify({mock_id:id})
    });
    await refresh();
  };
})();
</script>
{% endblock %}
