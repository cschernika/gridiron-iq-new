const $ = (id) => document.getElementById(id);
async function api(url, options={}) {
  const response = await fetch(url, {headers:{"Content-Type":"application/json", ...(options.headers||{})}, ...options});
  const data = await response.json().catch(()=>({}));
  if(!response.ok) throw new Error(data.detail || data.error || `Request failed (${response.status})`);
  return data;
}
function show(id, value, ok=true) {
  const el=$(id); if(!el) return;
  el.textContent=typeof value==="string"?value:JSON.stringify(value,null,2);
  el.style.background=ok?"#eef8f1":"#fdebed";
  el.style.color=ok?"#176737":"#9e2635";
}
$("menu-button")?.addEventListener("click",()=>document.querySelector(".sidebar")?.classList.toggle("open"));

function espnPayload(){return{
  league_id:$("espn-league-id")?.value||"",
  season:$("espn-season")?.value||"",
  swid:$("espn-swid")?.value||"",
  espn_s2:$("espn-s2")?.value||""
}}
$("test-espn")?.addEventListener("click",async()=>{show("espn-result","Testing…");try{show("espn-result",await api("/api/espn/test",{method:"POST",body:JSON.stringify(espnPayload())}))}catch(e){show("espn-result",e.message,false)}});
$("sync-espn")?.addEventListener("click",async()=>{show("espn-result","Syncing…");try{show("espn-result",await api("/api/espn/sync",{method:"POST",body:JSON.stringify(espnPayload())}))}catch(e){show("espn-result",e.message,false)}});
$("sync-sleeper")?.addEventListener("click",async()=>{show("sleeper-result","Syncing…");try{show("sleeper-result",await api("/api/sleeper/sync",{method:"POST",body:JSON.stringify({league_id:$("sleeper-league-id").value})}))}catch(e){show("sleeper-result",e.message,false)}});
$("connect-demo")?.addEventListener("click",async()=>{try{show("demo-result",await api("/api/demo/connect",{method:"POST",body:"{}"}))}catch(e){show("demo-result",e.message,false)}});
document.querySelectorAll(".disconnect").forEach(b=>b.addEventListener("click",async()=>{await api("/api/league/disconnect",{method:"POST",body:JSON.stringify({platform:b.dataset.platform,league_id:b.dataset.league})});location.reload()}));

const search=$("player-search"), pos=$("position-filter");
function filterPlayers(){document.querySelectorAll("#draft-table tbody tr").forEach(row=>{const q=(search?.value||"").toLowerCase(),p=pos?.value||"";row.style.display=(!q||row.dataset.name.includes(q))&&(!p||row.dataset.pos===p)?"":"none"})}
search?.addEventListener("input",filterPlayers);pos?.addEventListener("change",filterPlayers);
document.querySelectorAll(".draft-toggle").forEach(btn=>btn.addEventListener("click",()=>{const row=btn.closest("tr");row.classList.toggle("drafted");btn.textContent=row.classList.contains("drafted")?"Drafted":"Available"}));
$("reset-draft")?.addEventListener("click",()=>{document.querySelectorAll("#draft-table tbody tr").forEach(row=>{row.classList.remove("drafted");row.querySelector(".draft-toggle").textContent="Available"})});
$("recommend-draft")?.addEventListener("click",async()=>{const drafted=[...document.querySelectorAll("#draft-table tbody tr.drafted .player-name")].map(x=>x.textContent.trim());try{const d=await api("/api/draft/recommend",{method:"POST",body:JSON.stringify({drafted,position:pos?.value||""})});$("draft-recommendations").innerHTML=d.recommendations.map(x=>`<b>${x.name}</b> (${x.pos}, Tier ${x.tier}, ADP ${x.adp})`).join(" &nbsp; · &nbsp; ")||"No matching players remain."}catch(e){$("draft-recommendations").textContent=e.message}});

$("run-lineup")?.addEventListener("click",async()=>{try{const d=await api("/api/lineup/optimize",{method:"POST",body:JSON.stringify({risk:$("lineup-risk").value})});$("lineup-summary").textContent=`Projected starter total: ${d.projected_total} points · ${d.risk} profile`;$("lineup-body").innerHTML=d.lineup.map(r=>`<tr><td>${r.slot}</td><td><b>${r.player}</b></td><td>${r.projection}</td><td>${r.confidence}%</td></tr>`).join("")}catch(e){$("lineup-summary").textContent=e.message}});
$("run-waivers")?.addEventListener("click",async()=>{try{const d=await api("/api/waivers/analyze",{method:"POST",body:JSON.stringify({budget:$("faab-budget").value})});$("waiver-summary").textContent=`Maximum calculated bids use your remaining $${d.budget} FAAB budget.`;$("waiver-body").innerHTML=d.recommendations.map(r=>`<tr><td><b>${r.player}</b></td><td>${r.position}</td><td>${r.rostered}</td><td>${r.faab} (max $${r.max_bid})</td><td>${r.grade}</td><td>${r.reason}</td></tr>`).join("")}catch(e){$("waiver-summary").textContent=e.message}});
$("analyze-trade")?.addEventListener("click",async()=>{show("trade-result","Analyzing…");try{show("trade-result",await api("/api/trade/analyze",{method:"POST",body:JSON.stringify({give:$("trade-give").value,receive:$("trade-receive").value,scoring:$("trade-scoring").value})}))}catch(e){show("trade-result",e.message,false)}});
