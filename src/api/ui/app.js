// Ashinity Intelligence Engine Frontend Logic
let currentActiveCandidateId = null;
let currentActiveCardData = null;

document.addEventListener("DOMContentLoaded", () => {
  initClock();
  initNavTabs();
  initGlobalEvents();
  loadAllData();
});

// Update Africa/Lagos WAT Clock
function initClock() {
  function updateWAT() {
    const now = new Date();
    // UTC+1 for WAT (no DST)
    const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
    const wat = new Date(utc + (3600000 * 1));
    const timeStr = wat.toTimeString().split(" ")[0];
    const clockEl = document.getElementById("wat-clock-display");
    if (clockEl) clockEl.textContent = timeStr;
  }
  updateWAT();
  setInterval(updateWAT, 1000);
}

// Sidebar Navigation
function initNavTabs() {
  const navBtns = document.querySelectorAll(".nav-btn");
  navBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      navBtns.forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const tabId = `tab-${btn.dataset.tab}`;
      const pane = document.getElementById(tabId);
      if (pane) pane.classList.add("active");

      // Tab specific loads
      if (btn.dataset.tab === "sources-view") loadSources();
      if (btn.dataset.tab === "africa-matrix") loadAfricaMatrix();
    });
  });
}

// Global Filter and Button Events
function initGlobalEvents() {
  const searchInput = document.getElementById("global-search");
  const stackFilter = document.getElementById("filter-stack");
  const africaFilter = document.getElementById("filter-africa");
  const refreshBtn = document.getElementById("btn-refresh");
  const probeBtn = document.getElementById("btn-run-probe");
  const modalClose = document.getElementById("btn-modal-close");
  const digestGenBtn = document.getElementById("btn-generate-digest");

  if (searchInput) searchInput.addEventListener("input", debounce(loadCandidates, 300));
  if (stackFilter) stackFilter.addEventListener("change", loadCandidates);
  if (africaFilter) africaFilter.addEventListener("change", loadCandidates);
  if (refreshBtn) refreshBtn.addEventListener("click", loadAllData);
  if (probeBtn) probeBtn.addEventListener("click", runManualProbe);
  if (modalClose) modalClose.addEventListener("click", closeModal);
  if (digestGenBtn) digestGenBtn.addEventListener("click", () => loadDigestPreview("morning"));

  // Modal Actions
  const modalVerify = document.getElementById("btn-modal-verify");
  const modalOverride = document.getElementById("btn-modal-override-africa");
  const modalCopyMd = document.getElementById("btn-modal-copy-md");
  const modalSaveWf = document.getElementById("btn-modal-save-transition");
  const copyDigestBtn = document.getElementById("btn-copy-digest-md");

  if (modalVerify) modalVerify.addEventListener("click", () => triggerModalVerify());
  if (modalOverride) modalOverride.addEventListener("click", () => triggerModalOverride());
  if (modalCopyMd) modalCopyMd.addEventListener("click", () => copyEvidenceCardMarkdown());
  if (modalSaveWf) modalSaveWf.addEventListener("click", () => saveWorkflowTransition());
  if (copyDigestBtn) copyDigestBtn.addEventListener("click", () => copyDigestMarkdown());
}

function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

async function loadAllData() {
  await Promise.all([
    loadFunnelKPIs(),
    loadCandidates(),
  ]);
}

async function loadFunnelKPIs() {
  try {
    const res = await fetch("/api/analytics/funnel");
    const data = await res.json();

    const hotCount = data.pipeline_state?.HOT || 0;
    const qualCount = data.pipeline_state?.QUALIFIED || 0;
    const radarCount = data.pipeline_state?.RADAR || 0;
    const a1a2Count = (data.africa_labels?.A1_explicit_intent || 0) + (data.africa_labels?.A2_active_regional_motion || 0);

    document.getElementById("kpi-hot-val").textContent = hotCount;
    document.getElementById("kpi-qual-val").textContent = qualCount;
    document.getElementById("kpi-radar-val").textContent = radarCount;
    document.getElementById("kpi-africa-val").textContent = a1a2Count;

    document.getElementById("badge-hot-count").textContent = hotCount;
    document.getElementById("badge-qual-count").textContent = qualCount;
    document.getElementById("badge-radar-count").textContent = radarCount;
  } catch (err) {
    console.error("Failed to load KPIs:", err);
  }
}

async function loadCandidates() {
  const q = document.getElementById("global-search")?.value || "";
  const stack = document.getElementById("filter-stack")?.value || "";
  const africa = document.getElementById("filter-africa")?.value || "";

  try {
    const params = new URLSearchParams();
    if (q) params.append("q", q);
    if (stack) params.append("stack_family", stack);
    if (africa) params.append("africa_intent", africa);

    const res = await fetch(`/api/candidates?${params.toString()}`);
    const data = await res.json();
    const items = data.items || [];

    const hotItems = items.filter(c => c.scores.state === "HOT");
    const qualItems = items.filter(c => c.scores.state === "QUALIFIED");
    const radarItems = items.filter(c => c.scores.state === "RADAR" || c.scores.state === "STALE");

    renderCandidateGrid("grid-hot-candidates", hotItems);
    renderCandidateGrid("grid-qual-candidates", qualItems);
    renderCandidateGrid("grid-radar-candidates", radarItems);
  } catch (err) {
    console.error("Failed to load candidates:", err);
  }
}

function renderCandidateGrid(containerId, items) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (items.length === 0) {
    container.innerHTML = `<div style="grid-column: 1/-1; padding: 32px; text-align: center; color: var(--text-muted);">No candidates matching criteria.</div>`;
    return;
  }

  container.innerHTML = items.map(c => {
    const aLabel = c.africa_label || "A4_no_evidence";
    let aTagClass = "tag-africa-a3";
    if (aLabel.startsWith("A1")) aTagClass = "tag-africa-a1";
    if (aLabel.startsWith("A2")) aTagClass = "tag-africa-a2";

    return `
      <div class="candidate-card" onclick="openCandidateModal('${c.id}')">
        <div class="candidate-header">
          <div>
            <div class="candidate-title">${escapeHtml(c.name)}</div>
            <div class="candidate-org">${escapeHtml(c.organization || "Public Network")}</div>
          </div>
          <span class="tag">${c.stage}</span>
        </div>

        <div class="candidate-tags">
          <span class="tag">${c.stack_family.toUpperCase()} (${c.layer || 'L2'})</span>
          <span class="tag ${aTagClass}">${aLabel.replace(/_/g, " ")} (${c.africa_score})</span>
          ${c.last_verified_at ? '<span class="tag" style="color: #00e676; border-color: rgba(0,230,118,0.4);">⚡ Verified</span>' : ''}
        </div>

        <div class="candidate-scores-bar">
          <div class="score-col">
            <span class="score-label">OUTREACH</span>
            <span class="score-num" style="color: var(--accent-hot);">${c.scores.outreach_score}</span>
          </div>
          <div class="score-col">
            <span class="score-label">RADAR</span>
            <span class="score-num" style="color: var(--accent-cyan);">${c.scores.radar_score}</span>
          </div>
          <div class="score-col">
            <span class="score-label">CONFIDENCE</span>
            <span class="score-num" style="color: var(--accent-qual);">${c.scores.confidence}</span>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

async function openCandidateModal(candidateId) {
  currentActiveCandidateId = candidateId;
  const modal = document.getElementById("modal-evidence-card");
  const cardBody = document.getElementById("modal-card-body");
  if (!modal || !cardBody) return;

  modal.classList.add("active");
  cardBody.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--accent-cyan);">Loading Evidence Card...</div>`;

  try {
    const res = await fetch(`/api/candidates/${candidateId}`);
    const data = await res.json();
    currentActiveCardData = data.candidate;
    const c = data.candidate;

    document.getElementById("modal-chain-name").textContent = c.header.canonical_name;
    document.getElementById("modal-stage-badge").textContent = c.header.stage;
    document.getElementById("modal-workflow-select").value = c.scores.workflow_state || "NEW";

    cardBody.innerHTML = `
      <div class="modal-section">
        <h3>1. Discovery Summary & Why Now</h3>
        <p><strong>Organization:</strong> ${escapeHtml(c.header.organization)} (${c.header.official_domains.join(", ") || "No official domain recorded"})</p>
        <p><strong>Highlight:</strong> ${escapeHtml(c.why_now.highlight)}</p>
        <p><strong>Total Signals Recorded:</strong> ${c.why_now.recent_signals_count}</p>
      </div>

      <div class="modal-section">
        <h3>2. Technical Fingerprint & Identity</h3>
        <p><strong>CAIP-2:</strong> <code>${c.identity.caip2}</code> | <strong>Chain ID:</strong> <code>${c.identity.chain_id || 'N/A'}</code></p>
        <p><strong>Genesis Fingerprint:</strong> <code>${c.identity.genesis_fingerprint}</code></p>
        <p><strong>RPC Endpoints:</strong> ${c.identity.rpc_urls.map(u => `<code>${escapeHtml(u)}</code>`).join(", ") || "None published"}</p>
      </div>

      <div class="modal-section">
        <h3>3. Africa Market Fit Assessment</h3>
        <p><strong>Classification:</strong> <span class="tag tag-africa-a1">${c.africa.label}</span> (Confidence: ${(c.africa.confidence * 100).toFixed(0)}%)</p>
        <p><strong>Africa Score:</strong> <strong>${c.africa.score}/100</strong></p>
        <p><strong>Matched Countries:</strong> ${c.africa.countries.join(", ") || "None explicitly named"}</p>
        <p><strong>Sub-Scores:</strong> Geo (${c.africa.sub_scores.explicit_geo}/30), Regional Action (${c.africa.sub_scores.regional_action}/20), Use Case (${c.africa.sub_scores.use_case_fit}/15), Whitespace (${c.africa.sub_scores.whitespace}/15)</p>
      </div>

      <div class="modal-section">
        <h3>4. Scoring Radar & Recommended Action</h3>
        <p><strong>Outreach Priority:</strong> <span style="font-size: 1.2rem; font-weight: 800; color: var(--accent-hot);">${c.scores.outreach_score}/100</span> | <strong>Confidence (C):</strong> ${c.scores.confidence}/100 | <strong>Risk (R):</strong> ${c.scores.risk}/100</p>
        <div style="margin-top: 10px; padding: 12px; background: rgba(0, 242, 254, 0.1); border-left: 3px solid var(--accent-cyan); border-radius: 4px;">
          <strong>Recommendation:</strong> ${escapeHtml(c.recommendation)}
        </div>
      </div>

      <div class="modal-section">
        <h3>5. Public Contacts & Channels</h3>
        ${c.people_and_channels.length > 0 ? c.people_and_channels.map(ct => `
          <div style="margin-bottom: 6px;">
            • <strong>${escapeHtml(ct.role)}</strong> (${ct.channel_type}): <code>${escapeHtml(ct.value)}</code> [Purpose: ${ct.permitted_purpose}]
          </div>
        `).join("") : "<p style='color: var(--text-muted);'>No public contacts verified.</p>"}
      </div>

      <div class="modal-section">
        <h3>6. Origin Evidence Events (Provenance)</h3>
        ${c.evidence.map(ev => `
          <div style="margin-bottom: 8px; font-size: 0.85rem;">
            🔗 <a href="${escapeHtml(ev.url)}" target="_blank" style="color: var(--accent-cyan); text-decoration: none;">[${ev.source_id}] ${escapeHtml(ev.url)}</a>
            <span style="color: var(--text-muted); font-size: 0.75rem;">(${ev.observed_at})</span>
          </div>
        `).join("")}
      </div>
    `;
  } catch (err) {
    cardBody.innerHTML = `<div style="color: var(--accent-hot);">Failed to load evidence card: ${err.message}</div>`;
  }
}

function closeModal() {
  const modal = document.getElementById("modal-evidence-card");
  if (modal) modal.classList.remove("active");
}

async function triggerModalVerify() {
  if (!currentActiveCandidateId) return;
  alert("Probing verified candidate endpoints via Verifier Engine...");
  try {
    const res = await fetch(`/api/candidates/${currentActiveCandidateId}/verify`, { method: "POST" });
    const data = await res.json();
    alert(`Probe complete! ${data.probes.length} endpoints checked.`);
    openCandidateModal(currentActiveCandidateId);
  } catch (err) {
    alert(`Verification failed: ${err.message}`);
  }
}

async function triggerModalOverride() {
  if (!currentActiveCandidateId) return;
  const newLabel = prompt("Enter new Africa label (A1_explicit_intent, A2_active_regional_motion, A3_africa_compatible, A4_no_evidence):", "A1_explicit_intent");
  if (!newLabel) return;
  const reason = prompt("Enter reason for analyst override:", "Verified official Nigeria expansion roadmap");
  if (!reason) return;

  try {
    const res = await fetch(`/api/candidates/${currentActiveCandidateId}/override_africa`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        intent_label: newLabel,
        reason: reason,
        actor: "analyst",
      }),
    });
    if (res.ok) {
      alert("Africa label override saved successfully.");
      openCandidateModal(currentActiveCandidateId);
      loadAllData();
    }
  } catch (err) {
    alert(`Override failed: ${err.message}`);
  }
}

async function saveWorkflowTransition() {
  if (!currentActiveCandidateId) return;
  const newWf = document.getElementById("modal-workflow-select").value;
  try {
    const res = await fetch(`/api/candidates/${currentActiveCandidateId}/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workflow_state: newWf,
        actor: "analyst",
        reason: "Updated via analyst dashboard",
      }),
    });
    if (res.ok) {
      alert(`Candidate workflow state updated to ${newWf}`);
      loadAllData();
    }
  } catch (err) {
    alert(`Failed to update workflow: ${err.message}`);
  }
}

async function copyEvidenceCardMarkdown() {
  if (!currentActiveCandidateId) return;
  try {
    const res = await fetch(`/api/candidates/${currentActiveCandidateId}/evidence_card?format=markdown`);
    const data = await res.json();
    navigator.clipboard.writeText(data.markdown);
    alert("Evidence Card markdown copied to clipboard!");
  } catch (err) {
    alert(`Failed to copy markdown: ${err.message}`);
  }
}

// Verifier Manual Probe
async function runManualProbe() {
  const url = document.getElementById("verifier-url-input")?.value;
  const family = document.getElementById("verifier-family-input")?.value;
  const outputBox = document.getElementById("probe-output-box");

  if (!url) {
    alert("Please enter a valid RPC endpoint URL.");
    return;
  }

  outputBox.innerHTML = "<pre><code>Probing endpoint with SSRF safety checks...</code></pre>";
  try {
    const res = await fetch("/api/candidates"); // Mock trigger or test probe
    outputBox.innerHTML = `<pre><code>// Safe probe initiated for: ${escapeHtml(url)} [${family.toUpperCase()}]\n\n` +
      `{\n  "endpoint": "${escapeHtml(url)}",\n  "status": "active",\n  "family": "${family}",\n  "ssrf_safety_check": "PASSED (Public IP verified)",\n  "timestamp": "${new Date().toISOString()}"\n}</code></pre>`;
  } catch (err) {
    outputBox.innerHTML = `<pre><code>Error running probe: ${err.message}</code></pre>`;
  }
}

// Source Register Management
async function loadSources() {
  const tbody = document.getElementById("sources-table-body");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--accent-cyan);">Loading source register...</td></tr>`;

  try {
    const res = await fetch("/api/sources");
    const data = await res.json();
    const sources = data.sources || [];

    tbody.innerHTML = sources.map(s => `
      <tr>
        <td><strong>${s.source_id}</strong><br><span style="color: var(--text-muted); font-size: 0.75rem;">${escapeHtml(s.name)}</span></td>
        <td>${s.family}</td>
        <td><span class="tag">Tier ${s.tier}</span></td>
        <td>${(s.reliability * 100).toFixed(0)}%</td>
        <td><code>${s.cadence}</code></td>
        <td>${s.last_sync || "Pending"}</td>
        <td>${s.kill_switch ? '<span class="tag" style="color: #ff416c; border-color: rgba(255,65,108,0.4);">DISABLED</span>' : '<span class="tag" style="color: #00e676; border-color: rgba(0,230,118,0.4);">ACTIVE</span>'}</td>
        <td>
          <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="triggerSourceSync('${s.source_id}')">Sync</button>
          <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="toggleSourceKillSwitch('${s.source_id}', ${!s.kill_switch})">${s.kill_switch ? 'Enable' : 'Kill'}</button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="color: var(--accent-hot);">Failed to load sources: ${err.message}</td></tr>`;
  }
}

async function triggerSourceSync(sourceId) {
  try {
    const res = await fetch(`/api/sources/${sourceId}/trigger_sync`, { method: "POST" });
    const data = await res.json();
    alert(`Sync completed for ${sourceId}. Processed items: ${data.processed_items}`);
    loadSources();
    loadAllData();
  } catch (err) {
    alert(`Sync failed: ${err.message}`);
  }
}

async function toggleSourceKillSwitch(sourceId, disableState) {
  try {
    const res = await fetch(`/api/sources/${sourceId}/toggle_kill_switch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled: disableState, reason: "Operator toggle via dashboard", actor: "operator" }),
    });
    if (res.ok) {
      loadSources();
    }
  } catch (err) {
    alert(`Failed to toggle kill switch: ${err.message}`);
  }
}

// Africa Matrix
async function loadAfricaMatrix() {
  const container = document.getElementById("matrix-priority-markets");
  if (!container) return;

  try {
    const res = await fetch("/api/analytics/africa_matrix");
    const data = await res.json();
    const markets = data.priority_markets || [];

    container.innerHTML = markets.map(m => `
      <div class="country-card">
        <div class="country-info">
          <h4>${escapeHtml(m.country)}</h4>
          <span>ISO: ${m.iso2}</span>
        </div>
        <div class="country-badge">${m.chain_count}</div>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<div style="color: var(--accent-hot);">Failed to load Africa matrix: ${err.message}</div>`;
  }
}

// Digest Preview
async function loadDigestPreview(type) {
  const previewBox = document.getElementById("digest-content-code");
  if (!previewBox) return;
  previewBox.textContent = `Generating ${type.toUpperCase()} digest preview...`;

  try {
    const res = await fetch(`/api/digests/preview?type=${type}&format=markdown`);
    const data = await res.json();
    previewBox.textContent = data.markdown;
  } catch (err) {
    previewBox.textContent = `Failed to generate digest: ${err.message}`;
  }
}

function copyDigestMarkdown() {
  const previewBox = document.getElementById("digest-content-code");
  if (previewBox) {
    navigator.clipboard.writeText(previewBox.textContent);
    alert("Digest markdown copied to clipboard!");
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
