(() => {
  "use strict";

  const page = document.querySelector(".pr2-page");
  if (!page) return;

  const state = {
    position: document.querySelector(".pr2-tabs button.active")?.dataset.position || "",
    platform: page.dataset.platform || "ESPN",
    controller: null
  };

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  })[char]);

  const number = (value, decimals = 0) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed === 0) return '<span class="pr2-empty">—</span>';
    return parsed.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals
    });
  };

  function showAlert(message, error = false) {
    const alert = $("pr2-alert");
    if (!message) {
      alert.hidden = true;
      return;
    }
    alert.textContent = message;
    alert.className = `pr2-alert${error ? " error" : ""}`;
    alert.hidden = false;
  }

  function renderRows(players) {
    const body = $("pr2-body");
    if (!players.length) {
      body.innerHTML = '<tr><td colspan="15" class="pr2-loading">No matching players were found.</td></tr>';
      return;
    }

    body.innerHTML = players.map(player => `
      <tr>
        <td>${Number(player.adp) < 999 ? number(player.adp, 1) : '<span class="pr2-empty">NR</span>'}</td>
        <td>${esc(player.position_adp || "—")}</td>
        <td><span class="pr2-player">${esc(player.name)}</span></td>
        <td>${esc(player.team || "FA")}</td>
        <td><span class="pr2-position">${esc(player.position)}</span></td>
        <td>${number(player.games)}</td>
        <td>${number(player.fantasy_points_ppr, 1)}</td>
        <td>${number(player.passing_yards, 0)}</td>
        <td>${number(player.passing_tds, 0)}</td>
        <td>${number(player.rushing_yards, 0)}</td>
        <td>${number(player.rushing_tds, 0)}</td>
        <td>${number(player.receptions, 0)}</td>
        <td>${number(player.receiving_yards, 0)}</td>
        <td>${number(player.receiving_tds, 0)}</td>
        <td><strong>${number(player.proj_2026_ppr, 1)}</strong></td>
      </tr>
    `).join("");
  }

  async function loadPlayers() {
    state.controller?.abort();
    state.controller = new AbortController();

    $("pr2-body").innerHTML = '<tr><td colspan="15" class="pr2-loading">Loading player data…</td></tr>';
    showAlert("");

    const params = new URLSearchParams({
      position: state.position,
      platform: state.platform,
      q: $("pr2-search").value.trim(),
      sort: $("pr2-sort").value,
      direction: $("pr2-direction").value,
      limit: "2000"
    });

    try {
      const response = await fetch(`/api/player-research/table?${params}`, {
        signal: state.controller.signal,
        headers: {"Accept":"application/json"}
      });
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        throw new Error(`Server returned ${response.status} instead of JSON.`);
      }

      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || payload.message || "Unable to load players.");
      }

      renderRows(payload.players || []);
      $("pr2-count").textContent = payload.count ?? 0;
      $("pr2-platform").textContent = payload.platform || state.platform;
      $("pr2-stats-status").textContent = payload.updated_at?.stats_2025 ? "Loaded" : "Not loaded";
      $("pr2-adp-status").textContent = payload.updated_at?.adp_2026 ? "Loaded" : "Not loaded";

      document.querySelectorAll("[data-count-for]").forEach(node => {
        if (node.dataset.countFor === "ALL") {
          node.textContent = payload.selected_position === "ALL" ? payload.count : node.textContent;
        } else if (payload.selected_position === "ALL") {
          node.textContent = payload.position_counts?.[node.dataset.countFor] || 0;
        } else if (node.dataset.countFor === payload.selected_position) {
          node.textContent = payload.count;
        }
      });

      const sources = payload.sources || {};
      $("pr2-source-note").textContent =
        `2025 stats: ${sources.stats_2025 || "not loaded"} · ` +
        `2026 projections: ${sources.projections_2026 || "not loaded"} · ` +
        `ADP: ${sources.adp_2026 || "not loaded"}`;

      if (payload.warnings?.length) {
        showAlert(payload.warnings.join(" "));
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      renderRows([]);
      showAlert(error.message, true);
    }
  }

  let searchTimer;
  $("pr2-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadPlayers, 250);
  });
  $("pr2-sort").addEventListener("change", loadPlayers);
  $("pr2-direction").addEventListener("change", loadPlayers);
  $("pr2-refresh-table").addEventListener("click", loadPlayers);

  document.querySelectorAll(".pr2-tabs button").forEach(button => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".pr2-tabs button").forEach(node => node.classList.toggle("active", node === button));
      state.position = button.dataset.position || "";
      const url = new URL(window.location.href);
      state.position ? url.searchParams.set("position", state.position) : url.searchParams.delete("position");
      history.replaceState({}, "", url);
      loadPlayers();
    });
  });

  $("pr2-league-select").addEventListener("change", event => {
    const url = new URL(window.location.href);
    url.searchParams.set("league", event.target.value);
    window.location.href = url.toString();
  });

  loadPlayers();
})();