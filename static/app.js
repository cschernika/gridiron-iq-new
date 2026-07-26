const $=id=>document.getElementById(id);
async function api(url,options={}){const r=await fetch(url,{headers:{"Content-Type":"application/json"},...options});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.error||`Request failed (${r.status})`);return d}
function show(id,v,ok=true){const e=$(id);if(!e)return;e.textContent=typeof v==="string"?v:JSON.stringify(v,null,2);e.style.color=ok?"#176737":"#9e2635"}
function espn(){return{league_id:$("espn-league-id")?.value||"",season:$("espn-season")?.value||"",swid:$("espn-swid")?.value||"",espn_s2:$("espn-s2")?.value||""}}
$("test-espn")?.addEventListener("click",async()=>{show("espn-result","Testing…");try{show("espn-result",await api("/api/espn/test",{method:"POST",body:JSON.stringify(espn())}))}catch(e){show("espn-result",e.message,false)}})
$("sync-espn")?.addEventListener("click",async()=>{show("espn-result","Syncing and saving snapshot…");try{show("espn-result",await api("/api/espn/sync",{method:"POST",body:JSON.stringify(espn())}));setTimeout(()=>location.href="/app",1200)}catch(e){show("espn-result",e.message,false)}})
$("disconnect-league")?.addEventListener("click",async()=>{await api("/api/league/disconnect",{method:"POST",body:"{}"});location.reload()})
const search=$("player-search"),pos=$("position-filter");
function filterPlayers(){document.querySelectorAll("#draft-table tbody tr").forEach(row=>{const q=(search?.value||"").toLowerCase(),p=pos?.value||"";row.style.display=(!q||row.dataset.name.includes(q))&&(!p||row.dataset.pos===p)?"":"none"})}
search?.addEventListener("input",filterPlayers);pos?.addEventListener("change",filterPlayers)
document.querySelectorAll(".draft-toggle").forEach(btn=>btn.addEventListener("click",()=>{const row=btn.closest("tr");row.classList.toggle("drafted");btn.textContent=row.classList.contains("drafted")?"Drafted":"Available"}))
$("reset-draft")?.addEventListener("click",()=>document.querySelectorAll("#draft-table tbody tr").forEach(row=>{row.classList.remove("drafted");row.querySelector(".draft-toggle").textContent="Available"}))
$("recommend-draft")?.addEventListener("click",async()=>{const drafted=[...document.querySelectorAll("#draft-table tbody tr.drafted .player-name")].map(x=>x.textContent.trim());const d=await api("/api/draft/recommend",{method:"POST",body:JSON.stringify({drafted,position:pos?.value||""})});$("draft-recommendations").innerHTML=`<b>${d.scoring}</b>: `+d.recommendations.map(x=>`${x.name} (${x.pos}, Tier ${x.tier})`).join(" · ")})
