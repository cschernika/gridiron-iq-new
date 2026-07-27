(function(){
  const $ = id => document.getElementById(id);
  const json = async (url, options={}) => {
    const r = await fetch(url, {
      headers: {"Content-Type":"application/json", ...(options.headers||{})},
      ...options
    });
    const data = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(data.error || data.detail || `Request failed (${r.status})`);
    return data;
  };

  const getDraftState = () => ({
    league_key: $("dc-league-select")?.value || "",
    draft_slot: Number($("dc-draft-slot")?.value || 1),
    round: Number($("dc-round")?.value || 1),
    pick_in_round: Number($("dc-pick")?.value || 1),
    strategy: $("dc-strategy")?.value || "balanced"
  });

  async function refreshRecommendation(){
    try{
      const data = await json("/api/draft/pro/recommend", {
        method:"POST",
        body:JSON.stringify(getDraftState())
      });
      $("dc-best-player").textContent = data.recommendation.player.name;
      $("dc-best-position").textContent = data.recommendation.player.pos;
      $("dc-best-team").textContent = `${data.recommendation.player.team} · Tier ${data.recommendation.player.tier}`;
      $("dc-best-score").textContent = data.recommendation.score;
      $("dc-confidence").textContent = `${data.recommendation.confidence}% confidence`;
      $("dc-adp-value").textContent = data.recommendation.adp_value;
      $("dc-roster-fit").textContent = data.recommendation.roster_fit;
      $("dc-scarcity").textContent = data.recommendation.scarcity;
      $("dc-tier-risk").textContent = data.recommendation.tier_risk;
      $("dc-rationale").textContent = data.recommendation.rationale;
      $("dc-survival-probability").textContent = `${data.recommendation.survival_probability}%`;
      $("dc-next-best-list").innerHTML = data.recommendation.next_best
        .map(p=>`<button type="button" class="dc-chip">${p.name} · ${p.pos}</button>`).join("");
      $("dc-next-picks-list").innerHTML = data.context.next_picks.map(x=>`<b>${x}</b>`).join("");
    }catch(err){
      $("dc-rationale").textContent = err.message;
    }
  }

  $("dc-refresh-recommendation")?.addEventListener("click", refreshRecommendation);
  $("dc-draft-slot")?.addEventListener("change", refreshRecommendation);
  $("dc-round")?.addEventListener("change", refreshRecommendation);
  $("dc-pick")?.addEventListener("change", refreshRecommendation);
  $("dc-strategy")?.addEventListener("change", refreshRecommendation);

  $("dc-league-select")?.addEventListener("change", async ()=>{
    const key = $("dc-league-select").value;
    try{
      const data = await json(`/api/draft/pro/context?league_key=${encodeURIComponent(key)}`);
      $("dc-league-name").textContent = data.context.league_name;
      $("dc-platform").textContent = data.context.platform;
      $("dc-scoring").textContent = data.context.scoring;
      $("dc-teams").textContent = data.context.teams;
      $("dc-draft-type").textContent = data.context.draft_type;
      $("dc-draft-slot").max = data.context.teams;
      location.href = `/draft-center?league=${encodeURIComponent(key)}`;
    }catch(err){ console.error(err); }
  });

  const search = $("dc-player-search");
  const pos = $("dc-position-filter");
  const tier = $("dc-tier-filter");

  function filterRows(){
    document.querySelectorAll("#dc-player-body tr").forEach(row=>{
      const q = (search?.value || "").toLowerCase();
      const p = pos?.value || "";
      const t = tier?.value || "";
      const show =
        (!q || row.dataset.name.includes(q)) &&
        (!p || row.dataset.pos === p) &&
        (!t || row.dataset.tier === t);
      row.style.display = show ? "" : "none";
    });
  }

  search?.addEventListener("input", filterRows);
  pos?.addEventListener("change", filterRows);
  tier?.addEventListener("change", filterRows);

  document.querySelectorAll(".dc-draft-toggle").forEach(btn=>{
    btn.addEventListener("click", async ()=>{
      const player = btn.dataset.player;
      const drafted = !btn.classList.contains("is-drafted");
      try{
        const data = await json("/api/draft/pro/mark", {
          method:"POST",
          body:JSON.stringify({
            player,
            drafted,
            league_key:$("dc-league-select")?.value || ""
          })
        });
        const row = btn.closest("tr");
        btn.classList.toggle("is-drafted", drafted);
        row.classList.toggle("drafted", drafted);
        btn.textContent = drafted ? "Drafted" : "Available";
        await refreshRecommendation();
        if(data.reload) location.reload();
      }catch(err){ alert(err.message); }
    });
  });

  $("dc-reset-draft")?.addEventListener("click", async ()=>{
    if(!confirm("Reset all tracked draft picks?")) return;
    await json("/api/draft/pro/reset", {
      method:"POST",
      body:JSON.stringify({league_key:$("dc-league-select")?.value || ""})
    });
    location.reload();
  });

  $("dc-run-sim")?.addEventListener("click", async ()=>{
    const box = $("dc-sim-result");
    box.innerHTML = "<strong>Running simulation…</strong><span>Evaluating roster construction paths.</span>";
    try{
      const data = await json("/api/draft/pro/simulate", {
        method:"POST",
        body:JSON.stringify({
          ...getDraftState(),
          strategy:$("dc-sim-strategy")?.value || "balanced"
        })
      });
      box.innerHTML = `<strong>${data.result.headline}</strong><span>${data.result.summary}</span>`;
    }catch(err){
      box.innerHTML = `<strong>Simulation failed</strong><span>${err.message}</span>`;
    }
  });
})();
