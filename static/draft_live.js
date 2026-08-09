(() => {
  "use strict";
  if (window.__GIQ_LIVE_DRAFT_V49__) return;
  window.__GIQ_LIVE_DRAFT_V49__ = true;
  if (location.pathname !== "/draft-center") return;

  const BUILD = "v49-live-draft-auto";
  const POLL_MS = 6000;
  let timer = null;
  let polling = false;
  let stopped = false;

  const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const lower = (value) => clean(value).toLowerCase();
  const esc = (value) => clean(value).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));

  function heading(text) {
    const wanted = lower(text);
    return Array.from(document.querySelectorAll("h1,h2,h3,h4,strong,b,p,span"))
      .find(el => lower(el.textContent) === wanted) || null;
  }

  function closestCard(el) {
    if (!el) return null;
    return el.closest("article,.card,.panel,.draft-card,.tool-card,section") || el.parentElement;
  }

  function pickStrategyCard() {
    return closestCard(heading("Pick Strategy"));
  }

  function recommendationCard() {
    return closestCard(heading("Best Pick Right Now"));
  }

  function labeledControl(card, labelText, tag) {
    if (!card) return null;
    const wanted = lower(labelText);
    const labels = Array.from(card.querySelectorAll("label"));
    for (const label of labels) {
      const txt = lower(label.textContent);
      if (!txt.startsWith(wanted)) continue;
      const control = label.querySelector(tag || "input,select");
      if (control) return control;
      const forId = label.getAttribute("for");
      if (forId) {
        const linked = document.getElementById(forId);
        if (linked) return linked;
      }
    }
    return null;
  }

  function controls() {
    const card = pickStrategyCard();
    const inputs = card ? Array.from(card.querySelectorAll("input")) : [];
    const selects = card ? Array.from(card.querySelectorAll("select")) : [];
    return {
      card,
      slot: labeledControl(card, "Draft Slot", "input") || inputs[0] || null,
      round: labeledControl(card, "Current Round", "input") || inputs[1] || null,
      pick: labeledControl(card, "Current Pick", "input") || inputs[2] || null,
      strategy: labeledControl(card, "Strategy", "select") || selects[0] || null,
    };
  }

  function activeLeagueKey() {
    const params = new URLSearchParams(location.search);
    if (params.get("league")) return params.get("league");

    // The main header has a league selector. Prefer an option value that maps
    // to the backend context keys instead of depending on a template id.
    for (const select of document.querySelectorAll("select")) {
      const value = clean(select.value);
      if (/^(espn-|yahoo-)/i.test(value)) return value;
    }
    return "espn-gramps";
  }

  function ensureStyles() {
    if (document.getElementById("giq-live-draft-style")) return;
    const style = document.createElement("style");
    style.id = "giq-live-draft-style";
    style.textContent = `
      .giq-live-auto{margin:14px 0 12px;padding:12px 14px;border:1px solid #d8def1;border-radius:14px;background:#f8faff;color:#13233b;font-size:13px;line-height:1.35}
      .giq-live-auto-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:5px}
      .giq-live-auto-title{font-weight:900;letter-spacing:.03em}
      .giq-live-auto-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:900;background:#e6ebf7;color:#53627a;white-space:nowrap}
      .giq-live-auto-badge::before{content:"";width:8px;height:8px;border-radius:50%;background:#8b98ad}
      .giq-live-auto-badge.live{background:#e6f8ed;color:#197848}.giq-live-auto-badge.live::before{background:#22b866;box-shadow:0 0 0 3px rgba(34,184,102,.12)}
      .giq-live-auto-badge.clock{background:#fff0d8;color:#9a5a00}.giq-live-auto-badge.clock::before{background:#ff9d1e;animation:giqPulse 1.1s infinite}
      .giq-live-auto-badge.error{background:#fff0f2;color:#b2394d}.giq-live-auto-badge.error::before{background:#e55368}
      .giq-live-auto-detail{color:#65748c}.giq-live-auto-detail b{color:#17243a}
      @keyframes giqPulse{0%,100%{opacity:1}50%{opacity:.35}}
      .giq-live-components{margin-top:14px;padding-top:13px;border-top:1px solid #e6eaf3}
      .giq-live-components-title{font-size:11px;font-weight:900;letter-spacing:.08em;color:#6b58e8;margin-bottom:8px}
      .giq-live-components-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}
      .giq-live-component{padding:8px 9px;border-radius:10px;background:#f6f7fc;border:1px solid #e4e7f1;min-width:0}
      .giq-live-component span{display:block;color:#748096;font-size:10px;text-transform:uppercase;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .giq-live-component b{display:block;margin-top:2px;color:#14233a;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      @media(max-width:720px){.giq-live-components-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
    `;
    document.head.appendChild(style);
  }

  function ensureStatusBox() {
    ensureStyles();
    let box = document.getElementById("giq-live-auto");
    if (box) return box;
    const c = controls();
    if (!c.card) return null;
    box = document.createElement("div");
    box.id = "giq-live-auto";
    box.className = "giq-live-auto";
    box.innerHTML = `
      <div class="giq-live-auto-top">
        <span class="giq-live-auto-title">LIVE AUTO RECOMMENDATIONS</span>
        <span id="giq-live-badge" class="giq-live-auto-badge">Checking</span>
      </div>
      <div id="giq-live-detail" class="giq-live-auto-detail">Checking the connected league for live draft picks…</div>`;

    const recalc = Array.from(c.card.querySelectorAll("button"))
      .find(btn => lower(btn.textContent).includes("recalculate recommendation"));
    if (recalc && recalc.parentNode) recalc.parentNode.insertBefore(box, recalc);
    else c.card.appendChild(box);
    return box;
  }

  function setStatus(kind, label, detail) {
    ensureStatusBox();
    const badge = document.getElementById("giq-live-badge");
    const body = document.getElementById("giq-live-detail");
    if (badge) {
      badge.className = `giq-live-auto-badge ${kind || ""}`.trim();
      badge.textContent = label;
    }
    if (body) body.innerHTML = detail;
  }

  function ensureBreakdown(rec) {
    if (!rec || !rec.player) return;
    const card = recommendationCard();
    if (!card) return;
    let box = document.getElementById("giq-live-components");
    if (!box) {
      box = document.createElement("div");
      box.id = "giq-live-components";
      box.className = "giq-live-components";
      card.appendChild(box);
    }
    const role = clean(rec.usage_role) || clean(rec.player.pos) || "Role pending";
    const group = rec.position_group || (rec.player && rec.player.position_group) || {};
    const action = clean(rec.draft_action) || (Number(rec.survival_probability) <= 25 ? "Draft Now" : "Strong Consideration");
    const groupLabel = group.strength ? `${group.strength} · urgency ${group.urgency_score ?? rec.group_urgency_score ?? "—"}/100` : (rec.group_urgency_score != null ? `${rec.group_urgency_score}/100` : "—");
    const fields = [
      ["Player Quality", rec.player_quality ?? rec.position_score ?? "—"],
      ["Scoring Potential", rec.scoring_potential ?? "—"],
      ["Roster Need", rec.roster_need_score ?? rec.roster_fit ?? "—"],
      ["League Settings Fit", rec.league_fit_score ?? "—"],
      ["Position Group", groupLabel],
      ["ADP Value", rec.adp_value ?? "—"],
      ["Expected Usage", role],
      ["Next-Round Chance", rec.survival_probability != null ? `${rec.survival_probability}%` : "—"],
      ["Recommendation", action],
    ];
    const strength = Array.isArray(group.strengths) && group.strengths.length ? group.strengths.join("; ") : "No major depth advantage";
    const weakness = Array.isArray(group.weaknesses) && group.weaknesses.length ? group.weaknesses.join("; ") : "No immediate scarcity warning";
    box.innerHTML = `
      <div class="giq-live-components-title">LIVE DECISION COMPONENTS · ${esc(rec.engine_version || "DRAFT IQ")}</div>
      <div class="giq-live-components-grid">
        ${fields.map(([k,v]) => `<div class="giq-live-component"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("")}
      </div>
      <div style="margin-top:8px;padding:9px;border:1px solid #e6e1ff;border-radius:10px;background:#faf9ff;font-size:12px;line-height:1.45">
        <b>${esc(clean(rec.player.pos) || "Position")} group intelligence</b><br>
        <span><strong>Strength:</strong> ${esc(strength)}</span><br>
        <span><strong>Weakness:</strong> ${esc(weakness)}</span>
      </div>`;
  }

  function updateControls(data) {
    const c = controls();
    if (c.round && data.current_round) c.round.value = data.current_round;
    if (c.pick && data.current_pick_in_round) c.pick.value = data.current_pick_in_round;
  }

  function params() {
    const c = controls();
    const p = new URLSearchParams();
    p.set("league_key", activeLeagueKey());
    p.set("draft_slot", c.slot && c.slot.value ? c.slot.value : "7");
    p.set("strategy", c.strategy && c.strategy.value ? c.strategy.value : "balanced");
    p.set("_", Date.now().toString());
    return p;
  }

  async function poll(force) {
    if (polling || stopped || document.hidden) return;
    polling = true;
    try {
      const response = await fetch(`/api/draft/live/status?${params().toString()}`, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {"Accept": "application/json"},
      });
      const data = await response.json();
      if (!response.ok || !data || data.ok === false) throw new Error((data && (data.error || data.detail)) || `HTTP ${response.status}`);

      if (!data.live_available) {
        setStatus("", "Manual Mode", clean(data.message) || "Sync the league to enable automatic live recommendations.");
        return;
      }

      if (data.status === "error") {
        setStatus("error", "Retrying", `${clean(data.message) || "Live draft feed is temporarily unavailable."}${data.detail ? ` <span title="${esc(data.detail)}">· details</span>` : ""}`);
        return;
      }

      updateControls(data);
      ensureBreakdown(data.recommendation);

      if (data.status === "on_clock") {
        const player = data.recommendation && data.recommendation.player ? clean(data.recommendation.player.name) : "your best option";
        setStatus("clock", "YOU'RE ON THE CLOCK", `<b>${data.pick_count}</b> picks synced. Best pick now: <b>${esc(player)}</b>. Recommendations refresh automatically every 6 seconds.`);
      } else if (data.status === "tracking") {
        const last = data.last_pick ? `${clean(data.last_pick.player)} (${clean(data.last_pick.team)})` : "—";
        setStatus("live", "Tracking ESPN", `<b>${data.pick_count}</b> picks synced · Last pick: <b>${esc(last)}</b> · Auto-refresh every 6 seconds.`);
      } else {
        setStatus("live", "Waiting for Draft", "ESPN connection is ready. Live Auto will begin as soon as the first pick appears.");
      }

      const storageKey = `giq-live-draft-revision:${activeLeagueKey()}`;
      const previous = sessionStorage.getItem(storageKey) || "";
      const revision = clean(data.revision);
      if (revision) sessionStorage.setItem(storageKey, revision);

      // The status call has already synchronized drafted players, the user's
      // roster, current pick and recommendation on the server. Reload once per
      // new real pick so every existing Draft Center panel updates together.
      if (data.pick_count > 0 && revision && (force || revision !== previous)) {
        setStatus(data.on_clock ? "clock" : "live", data.on_clock ? "YOU'RE ON THE CLOCK" : "New Pick Detected", "Updating the full Draft Center with the latest pick, roster needs and recommendation…");
        setTimeout(() => location.reload(), 450);
      }
    } catch (err) {
      setStatus("error", "Live Auto Retry", `Could not check the live draft: ${esc(err && err.message)}. Your manual <b>Recalculate Recommendation</b> button still works.`);
    } finally {
      polling = false;
    }
  }

  function wireControls() {
    const c = controls();
    [c.slot, c.strategy].filter(Boolean).forEach(el => {
      el.addEventListener("change", () => {
        const key = `giq-live-draft-revision:${activeLeagueKey()}`;
        sessionStorage.removeItem(key);
        poll(false);
      });
    });
    const recalc = c.card ? Array.from(c.card.querySelectorAll("button")).find(btn => lower(btn.textContent).includes("recalculate recommendation")) : null;
    if (recalc) recalc.addEventListener("click", () => setStatus("live", "Manual Refresh", "Recalculating with the current roster, ADP, scoring potential and position needs…"));
  }

  function start() {
    ensureStatusBox();
    wireControls();
    poll(false);
    timer = setInterval(() => poll(false), POLL_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) poll(false);
    });
    window.addEventListener("beforeunload", () => {
      stopped = true;
      if (timer) clearInterval(timer);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
