(() => {
  "use strict";
  const state = { players: [], filtered: [], selected: null, page: 1, pageSize: 20, watchlist: new Set(JSON.parse(localStorage.getItem("giq-player-watchlist") || "[]")) };
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const initials = name => name.split(/\s+/).map(x => x[0]).slice(0,2).join("").toUpperCase();

  async function fetchPlayers() {
    try {
      const response = await fetch("/api/player-research/players");
      if (!response.ok) throw new Error("Player API unavailable");
      const payload = await response.json();
      state.players = Array.isArray(payload) ? payload : payload.players || [];
    } catch (error) {
      const response = await fetch("/static/data/player_research_v2.json");
      state.players = await response.json();
    }
    populateTeams();
    populateComparison();
    applyFilters();
  }

  function populateTeams() {
    const teams = [...new Set(state.players.map(p => p.team).filter(Boolean))].sort();
    $("pr-team-filter").innerHTML = '<option value="">All teams</option>' + teams.map(t => `<option>${esc(t)}</option>`).join("");
  }

  function populateComparison() {
    $("pr-compare-select").innerHTML = '<option value="">Choose another player</option>' +
      state.players.map(p => `<option value="${esc(p.id)}">${esc(p.name)} — ${esc(p.position)}, ${esc(p.team)}</option>`).join("");
  }

  function applyFilters() {
    const query = $("pr-search-input").value.trim().toLowerCase();
    const position = $("pr-position-filter").value;
    const team = $("pr-team-filter").value;
    const watchOnly = $("pr-watch-only").checked;
    const sort = $("pr-sort").value;

    state.filtered = state.players.filter(p => {
      const haystack = `${p.name} ${p.team} ${p.position}`.toLowerCase();
      return (!query || haystack.includes(query)) &&
        (!position || p.position === position) &&
        (!team || p.team === team) &&
        (!watchOnly || state.watchlist.has(p.id));
    });

    const sorters = {
      rank: (a,b) => a.overall_rank - b.overall_rank,
      projection: (a,b) => b.projection - a.projection,
      adp: (a,b) => a.adp - b.adp,
      ceiling: (a,b) => b.ceiling - a.ceiling,
      floor: (a,b) => b.floor - a.floor,
      trend: (a,b) => b.trend - a.trend
    };
    state.filtered.sort(sorters[sort] || sorters.rank);
    state.page = 1;
    renderList();
  }

  function renderList() {
    const visible = state.filtered.slice(0, state.page * state.pageSize);
    $("pr-result-count").textContent = `${state.filtered.length} players`;
    $("pr-player-results").innerHTML = visible.map(p => `
      <button class="pr-player-row ${state.selected?.id === p.id ? "active" : ""}" data-player-id="${esc(p.id)}" role="listitem">
        <span class="pr-row-avatar">${esc(initials(p.name))}</span>
        <span class="pr-row-main"><strong>${esc(p.name)}</strong><span>${esc(p.position)} • ${esc(p.team)} • Bye ${esc(p.bye)}</span></span>
        <span class="pr-row-rank"><strong>#${esc(p.overall_rank)}</strong><span>${esc(p.grade)}</span></span>
      </button>`).join("") || '<div class="pr-empty-state"><h3>No players found</h3><p>Try clearing a filter.</p></div>';
    $("pr-load-more").hidden = visible.length >= state.filtered.length;
    document.querySelectorAll("[data-player-id]").forEach(button => button.addEventListener("click", () => selectPlayer(button.dataset.playerId)));
  }

  function selectPlayer(id) {
    const player = state.players.find(p => p.id === id);
    if (!player) return;
    state.selected = player;
    renderList();
    renderProfile(player);
  }

  function setText(id, value) { const node = $(id); if (node) node.textContent = value ?? "—"; }
  function listHtml(items) { return (items || []).map(x => `<li>${esc(x)}</li>`).join(""); }

  function renderProfile(p) {
    $("pr-empty-state").hidden = true;
    $("pr-profile").hidden = false;
    setText("pr-avatar", initials(p.name));
    setText("pr-player-name", p.name);
    setText("pr-player-meta", `${p.position} • ${p.team} • ${p.experience || "NFL"}`);
    setText("pr-overall-rank", `#${p.overall_rank}`);
    setText("pr-position-rank", `${p.position}${p.position_rank}`);
    setText("pr-projection", p.projection);
    setText("pr-adp", p.adp);
    setText("pr-grade", p.grade);
    setText("pr-grade-label", p.grade_label);
    setText("pr-verdict", p.verdict);
    setText("pr-summary", p.summary);
    setText("pr-confidence", `${p.confidence}%`);
    setText("pr-floor", p.floor);
    setText("pr-median", p.median);
    setText("pr-ceiling", p.ceiling);
    setText("pr-target-round", p.target_round);
    setText("pr-value-vs-adp", p.value_vs_adp);
    setText("pr-bye", p.bye);
    setText("pr-risk", p.risk);
    $("pr-floor-bar").style.width = `${Math.min(100, p.floor / p.ceiling * 100)}%`;
    $("pr-median-bar").style.width = `${Math.min(100, p.median / p.ceiling * 100)}%`;
    $("pr-ceiling-bar").style.width = "100%";
    $("pr-strengths").innerHTML = listHtml(p.strengths);
    $("pr-risks").innerHTML = listHtml(p.risks);
    $("pr-tags").innerHTML = (p.tags || []).map(t => `<span class="pr-tag ${esc(t.type || "")}">${esc(t.label || t)}</span>`).join("");
    renderUsage(p);
    renderMatchups(p);
    renderNews(p);
    updateWatchButton();
    $("pr-comparison").hidden = true;
  }

  function renderUsage(p) {
    $("pr-usage-metrics").innerHTML = Object.entries(p.usage || {}).map(([key, value]) => `
      <div><span>${esc(key.replaceAll("_"," "))}</span><strong>${esc(value.value ?? value)}</strong><small>${esc(value.label || "")}</small></div>`).join("");
    const values = p.recent_points || [];
    const max = Math.max(...values, 1);
    $("pr-trend-chart").innerHTML = values.map((value,index) => `<div class="pr-trend-bar" style="height:${Math.max(8, value/max*100)}%"><span>W${index+1}</span></div>`).join("");
  }

  function renderMatchups(p) {
    $("pr-matchup-list").innerHTML = (p.matchups || []).map(m => `
      <div class="pr-matchup"><span class="pr-matchup-grade grade-${esc(m.grade.toLowerCase())}">${esc(m.grade)}</span>
      <div><strong>Week ${esc(m.week)} vs ${esc(m.opponent)}</strong><span>${esc(m.note)}</span></div><strong>${esc(m.projection)} pts</strong></div>`).join("");
  }

  function renderNews(p) {
    $("pr-news-list").innerHTML = (p.news || []).map(n => `
      <div class="pr-news-item"><div><strong>${esc(n.title)}</strong><p>${esc(n.summary)}</p></div><small>${esc(n.date)}</small></div>`).join("");
  }

  function updateWatchButton() {
    if (!state.selected) return;
    const watched = state.watchlist.has(state.selected.id);
    $("pr-watch-button").setAttribute("aria-pressed", String(watched));
    $("pr-watch-button").textContent = watched ? "★ Watching" : "☆ Watch";
  }

  function toggleWatch() {
    if (!state.selected) return;
    state.watchlist.has(state.selected.id) ? state.watchlist.delete(state.selected.id) : state.watchlist.add(state.selected.id);
    localStorage.setItem("giq-player-watchlist", JSON.stringify([...state.watchlist]));
    updateWatchButton();
    if ($("pr-watch-only").checked) applyFilters();
  }

  function comparePlayers() {
    if (!state.selected) return;
    const other = state.players.find(p => p.id === $("pr-compare-select").value);
    if (!other || other.id === state.selected.id) return;
    const rows = [
      ["Overall rank", state.selected.overall_rank, other.overall_rank, "low"],
      ["Projection", state.selected.projection, other.projection, "high"],
      ["ADP", state.selected.adp, other.adp, "low"],
      ["Floor", state.selected.floor, other.floor, "high"],
      ["Ceiling", state.selected.ceiling, other.ceiling, "high"],
      ["Confidence", state.selected.confidence, other.confidence, "high"]
    ];
    $("pr-comparison").innerHTML = `<table><thead><tr><th>Metric</th><th>${esc(state.selected.name)}</th><th>${esc(other.name)}</th></tr></thead><tbody>${
      rows.map(([label,a,b,mode]) => {
        const aWin = mode === "high" ? a > b : a < b, bWin = mode === "high" ? b > a : b < a;
        return `<tr><td>${esc(label)}</td><td><strong>${aWin ? "✓ " : ""}${esc(a)}</strong></td><td><strong>${bWin ? "✓ " : ""}${esc(b)}</strong></td></tr>`;
      }).join("")
    }</tbody></table>`;
    $("pr-comparison").hidden = false;
  }

  ["pr-search-input","pr-position-filter","pr-team-filter","pr-sort","pr-watch-only"].forEach(id => $(id)?.addEventListener(id === "pr-search-input" ? "input" : "change", applyFilters));
  $("pr-clear-filters")?.addEventListener("click", () => {
    $("pr-search-input").value = ""; $("pr-position-filter").value = ""; $("pr-team-filter").value = "";
    $("pr-sort").value = "rank"; $("pr-watch-only").checked = false; applyFilters();
  });
  $("pr-load-more")?.addEventListener("click", () => { state.page += 1; renderList(); });
  $("pr-watch-button")?.addEventListener("click", toggleWatch);
  $("pr-compare-button")?.addEventListener("click", comparePlayers);
  document.querySelectorAll("[data-pr-tab]").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll("[data-pr-tab]").forEach(x => x.classList.toggle("active", x === button));
    document.querySelectorAll("[data-pr-panel]").forEach(x => x.classList.toggle("active", x.dataset.prPanel === button.dataset.prTab));
  }));
  document.addEventListener("DOMContentLoaded", fetchPlayers);
})();