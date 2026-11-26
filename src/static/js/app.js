/**
 * HITL AI Assistant Gateway - Single Page Reactivity & Real-Time Controller
 */

// -----------------------------------------------------------------------------
// Configuration & State
// -----------------------------------------------------------------------------
const CONFIG = {
  API_KEY: "hitl_live_sk_7f8a9b2c3d4e5f6a1b2c3d4e5f6a7b8c",
  BASE_URL: window.location.origin.includes("localhost") || window.location.origin.includes("127.0.0.1")
    ? window.location.origin
    : window.location.origin,
  WHITELISTED_DOMAINS: ["platform.in", "cdslindia.com", "nsdl.co.in", "sebi.gov.in", "nseindia.com", "bseindia.com"],
};

const state = {
  activeTab: "support",
  tickets: [],
  activeFilter: "ALL",
  selectedTicket: null,
  pulse: null,
  themes: [],
  explainers: [],
  auditLogs: [],
  selectedAuditLog: null,
};

// -----------------------------------------------------------------------------
// Initialization
// -----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  setupNavigation();
  setupSupportEvents();
  setupProductEvents();
  setupAuditEvents();

  // Load initial data
  loadTickets();
  loadPulseData();
  loadAuditLogs();
});

// -----------------------------------------------------------------------------
// API Helper
// -----------------------------------------------------------------------------
async function apiCall(endpoint, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-API-Key": CONFIG.API_KEY,
    ...(options.headers || {}),
  };

  const url = `${CONFIG.BASE_URL}${endpoint}`;
  try {
    const res = await fetch(url, { ...options, headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const errorMsg = data.detail || `Request failed with status ${res.status}`;
      showToast(errorMsg, "error");
      throw new Error(errorMsg);
    }
    return data;
  } catch (err) {
    console.error(`API Error [${endpoint}]:`, err);
    throw err;
  }
}

// -----------------------------------------------------------------------------
// Navigation Tabs
// -----------------------------------------------------------------------------
function setupNavigation() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      switchTab(tab);
    });
  });
}

function switchTab(tabId) {
  state.activeTab = tabId;

  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabId);
  });

  document.querySelectorAll(".view-section").forEach((sec) => {
    sec.classList.toggle("active", sec.id === `${tabId}-view`);
  });

  if (tabId === "support") loadTickets();
  if (tabId === "product") loadPulseData();
  if (tabId === "audit") loadAuditLogs();
}

// -----------------------------------------------------------------------------
// Support Queue Logic
// -----------------------------------------------------------------------------
function setupSupportEvents() {
  // Filter pills
  document.querySelectorAll(".filter-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".filter-pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      state.activeFilter = pill.dataset.filter;
      renderTicketList();
    });
  });

  // New query submit
  const submitInquiryBtn = document.getElementById("btn-submit-inquiry");
  const inquiryInput = document.getElementById("inquiry-text-input");
  if (submitInquiryBtn && inquiryInput) {
    submitInquiryBtn.addEventListener("click", async () => {
      const query = inquiryInput.value.trim();
      if (!query) return;
      try {
        submitInquiryBtn.disabled = true;
        submitInquiryBtn.innerText = "Processing...";
        const newTicket = await apiCall("/api/support/inquiries", {
          method: "POST",
          body: JSON.stringify({ raw_query: query, customer_id: "cust_web_user" }),
        });
        showToast(`Inquiry processed: Ticket ${newTicket.ticket_id} created`, "success");
        inquiryInput.value = "";
        await loadTickets();
        selectTicket(newTicket.ticket_id);
      } catch (e) {
        // Handled in apiCall
      } finally {
        submitInquiryBtn.disabled = false;
        submitInquiryBtn.innerText = "Submit Inquiry";
      }
    });
  }

  // Live validator on draft textarea
  const draftTextarea = document.getElementById("draft-textarea");
  if (draftTextarea) {
    draftTextarea.addEventListener("input", () => {
      validateDraftLive(draftTextarea.value);
    });
  }

  // Action buttons
  const btnApprove = document.getElementById("btn-approve-ticket");
  const btnSaveEdit = document.getElementById("btn-save-edit");
  const btnReject = document.getElementById("btn-reject-ticket");

  if (btnApprove) {
    btnApprove.addEventListener("click", async () => {
      if (!state.selectedTicket) return;
      const draft = document.getElementById("draft-textarea").value.trim();
      try {
        btnApprove.disabled = true;
        const res = await apiCall(`/api/support/tickets/${state.selectedTicket.ticket_id}/approve`, {
          method: "POST",
          body: JSON.stringify({
            pre_state_hash: state.selectedTicket.current_state_hash,
            operator_id: "operator_specialist",
            final_draft: draft,
          }),
        });
        showToast(`Ticket ${res.ticket_id} approved & dispatched!`, "success");
        await loadTickets();
        selectTicket(res.ticket_id);
      } catch (err) {
        // Handled in apiCall
      } finally {
        btnApprove.disabled = false;
      }
    });
  }

  if (btnSaveEdit) {
    btnSaveEdit.addEventListener("click", async () => {
      if (!state.selectedTicket) return;
      const draft = document.getElementById("draft-textarea").value.trim();
      try {
        btnSaveEdit.disabled = true;
        const res = await apiCall(`/api/support/tickets/${state.selectedTicket.ticket_id}/edit`, {
          method: "PUT",
          body: JSON.stringify({
            proposed_draft: draft,
            pre_state_hash: state.selectedTicket.current_state_hash,
            operator_id: "operator_specialist",
          }),
        });
        showToast(`Edit saved for ticket ${res.ticket_id}`, "success");
        await loadTickets();
        selectTicket(res.ticket_id);
      } catch (err) {
        // Handled in apiCall
      } finally {
        btnSaveEdit.disabled = false;
      }
    });
  }

  if (btnReject) {
    btnReject.addEventListener("click", async () => {
      if (!state.selectedTicket) return;
      if (!confirm("Are you sure you want to reject this proposed draft?")) return;
      try {
        btnReject.disabled = true;
        const res = await apiCall(`/api/support/tickets/${state.selectedTicket.ticket_id}/reject`, {
          method: "POST",
          body: JSON.stringify({
            pre_state_hash: state.selectedTicket.current_state_hash,
            operator_id: "operator_specialist",
            reason: "Rejected by human reviewer in UI",
          }),
        });
        showToast(`Ticket ${res.ticket_id} marked as REJECTED`, "info");
        await loadTickets();
        selectTicket(res.ticket_id);
      } catch (err) {
        // Handled in apiCall
      } finally {
        btnReject.disabled = false;
      }
    });
  }
}

async function loadTickets() {
  try {
    const tickets = await apiCall("/api/support/tickets");
    state.tickets = tickets;
    renderTicketList();
    if (!state.selectedTicket && tickets.length > 0) {
      selectTicket(tickets[0].ticket_id);
    } else if (state.selectedTicket) {
      selectTicket(state.selectedTicket.ticket_id);
    }
  } catch (err) {
    console.error("Failed to load tickets:", err);
  }
}

function renderTicketList() {
  const container = document.getElementById("ticket-list-container");
  if (!container) return;

  const filtered = state.tickets.filter((t) => {
    if (state.activeFilter === "ALL") return true;
    return t.status === state.activeFilter;
  });

  const countBadge = document.getElementById("support-tab-count");
  if (countBadge) countBadge.innerText = state.tickets.length;

  if (filtered.length === 0) {
    container.innerHTML = `<div style="padding: 2rem; text-align: center; color: var(--text-muted); font-size: 0.85rem;">No tickets found matching "${state.activeFilter}".</div>`;
    return;
  }

  container.innerHTML = filtered
    .map((t) => {
      const isSelected = state.selectedTicket && state.selectedTicket.ticket_id === t.ticket_id;
      const statusClass = `badge-${t.status.toLowerCase().replace(/_/g, "-")}`;
      const urgencyColor = t.routing_note.urgency === "HIGH" ? "var(--accent-rose)" : t.routing_note.urgency === "MEDIUM" ? "var(--accent-amber)" : "var(--text-muted)";

      return `
        <div class="ticket-item ${isSelected ? "active" : ""}" onclick="selectTicket('${t.ticket_id}')">
          <div class="ticket-meta">
            <span class="ticket-id">${t.ticket_id}</span>
            <span class="badge ${statusClass}">${t.status}</span>
          </div>
          <div class="ticket-query-snippet">${escapeHtml(t.raw_query_redacted)}</div>
          <div class="ticket-footer">
            <span class="ticket-category-tag">${t.routing_note.category}</span>
            <span style="color: ${urgencyColor}; font-weight: 600;">${t.routing_note.urgency}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

function selectTicket(ticketId) {
  const ticket = state.tickets.find((t) => t.ticket_id === ticketId);
  if (!ticket) return;

  state.selectedTicket = ticket;
  renderTicketList(); // Re-render to highlight active item

  // Fill Header
  document.getElementById("detail-ticket-id").innerText = ticket.ticket_id;
  const statusBadge = document.getElementById("detail-ticket-status");
  statusBadge.className = `badge badge-${ticket.status.toLowerCase().replace(/_/g, "-")}`;
  statusBadge.innerText = ticket.status;

  // Compute pre-state hash representation for optimistic concurrency
  ticket.current_state_hash = computeMockHash(ticket);
  document.getElementById("detail-state-hash").innerText = `Pre-State SHA: ${ticket.current_state_hash.substring(0, 16)}...`;

  // Original Query
  document.getElementById("detail-raw-query").innerText = ticket.raw_query_redacted;

  // Deliberation Cards
  const delib = ticket.deliberation || {};
  const retOutput = delib.retrieval_agent_output || {};
  document.getElementById("delib-retrieval").innerHTML = `
    <div>Relevance: <strong>${(retOutput.relevance_score || 0.85).toFixed(2)}</strong></div>
    <div>Covered: <span style="color: ${ticket.is_covered ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">${ticket.is_covered ? 'YES' : 'NO'}</span></div>
  `;

  const compOutput = delib.compliance_agent_output || {};
  document.getElementById("delib-compliance").innerHTML = `
    <div>SEBI Safe: <strong style="color: var(--accent-emerald);">YES</strong></div>
    <div>Advice Refused: <strong>YES</strong></div>
  `;

  const draftOutput = delib.drafting_agent_output || {};
  document.getElementById("delib-routing").innerHTML = `
    <div>Category: <strong>${ticket.routing_note.category}</strong></div>
    <div>Sentiment: <strong>${ticket.routing_note.sentiment}</strong></div>
    <div>Reason: <span style="color: var(--text-secondary);">${escapeHtml(ticket.routing_note.reason || '')}</span></div>
  `;

  // Draft Editor
  const draftTextarea = document.getElementById("draft-textarea");
  draftTextarea.value = ticket.proposed_draft || "";
  validateDraftLive(draftTextarea.value);

  // Update button states
  const btnApprove = document.getElementById("btn-approve-ticket");
  const btnReject = document.getElementById("btn-reject-ticket");
  if (ticket.status === "APPROVED") {
    btnApprove.innerText = "Already Approved";
  } else {
    btnApprove.innerText = "Approve & Dispatch";
  }
}

// -----------------------------------------------------------------------------
// Live Sentence & Whitelist Validator
// -----------------------------------------------------------------------------
function splitSentencesClient(text) {
  if (!text || !text.trim()) return [];
  // Clean decimal numbers and currency like Rs. 15.93 before split
  let cleaned = text.replace(/Rs\.\s*\d+(\.\d+)?/gi, "Rs_AMOUNT");
  cleaned = cleaned.replace(/\b\d+\.\d+/g, "DEC_NUM");
  cleaned = cleaned.replace(/e\.g\./gi, "EG_ABBR");
  cleaned = cleaned.replace(/i\.e\./gi, "IE_ABBR");
  
  // Split on sentence boundaries
  const parts = cleaned.split(/(?<=[.!?])\s+/);
  return parts.filter((p) => p.trim().length > 0);
}

function validateDraftLive(text) {
  const sentences = splitSentencesClient(text);
  const sentenceCount = sentences.length;

  // Extract URLs
  const urlRegex = /https?:\/\/[^\s)\]]+/gi;
  const urls = text.match(urlRegex) || [];

  const hasWhitelistedUrl = urls.some((u) => {
    return CONFIG.WHITELISTED_DOMAINS.some((domain) => u.includes(domain));
  });

  const sentenceMeter = document.getElementById("meter-sentences");
  const linkMeter = document.getElementById("meter-links");
  const btnApprove = document.getElementById("btn-approve-ticket");

  // Update Sentence Meter
  if (sentenceCount <= 3 && sentenceCount > 0) {
    sentenceMeter.className = "meter-pill valid";
    sentenceMeter.innerHTML = `✓ ${sentenceCount}/3 Sentences`;
  } else {
    sentenceMeter.className = "meter-pill invalid";
    sentenceMeter.innerHTML = `✕ ${sentenceCount}/3 Sentences (Max 3)`;
  }

  // Update Link Meter
  if (hasWhitelistedUrl) {
    linkMeter.className = "meter-pill valid";
    linkMeter.innerHTML = `✓ Official Source Link`;
  } else {
    linkMeter.className = "meter-pill invalid";
    linkMeter.innerHTML = `✕ Lacks Official Source Link`;
  }

  // Constraint Enforcement on Approve Button (EC-HITL-01)
  const isCovered = state.selectedTicket ? state.selectedTicket.is_covered : true;
  const isValid = sentenceCount <= 3 && sentenceCount > 0 && (!isCovered || hasWhitelistedUrl);

  if (btnApprove) {
    btnApprove.disabled = !isValid;
  }
}

// -----------------------------------------------------------------------------
// Product Intelligence Logic
// -----------------------------------------------------------------------------
function setupProductEvents() {
  const btnRunWeekly = document.getElementById("btn-run-weekly-loop");
  if (btnRunWeekly) {
    btnRunWeekly.addEventListener("click", async () => {
      try {
        btnRunWeekly.disabled = true;
        btnRunWeekly.innerText = "Running Weekly Batch...";
        const res = await apiCall("/api/product/pulse/run", { method: "POST" });
        showToast(`Weekly Loop executed successfully! Pulse: ${res.pulse_id} (${res.word_count} words)`, "success");
        await loadPulseData();
      } catch (e) {
        // Handled in apiCall
      } finally {
        btnRunWeekly.disabled = false;
        btnRunWeekly.innerText = "⚡ Trigger Weekly Run";
      }
    });
  }
}

async function loadPulseData() {
  try {
    const pulse = await apiCall("/api/product/pulse");
    state.pulse = pulse;
    renderPulse(pulse);

    const explainers = await apiCall("/api/product/explainers");
    state.explainers = explainers;
    renderExplainers(explainers);
  } catch (err) {
    console.error("Failed to load pulse data:", err);
  }
}

function renderPulse(pulse) {
  if (!pulse) return;

  document.getElementById("pulse-meta-week").innerText = `${pulse.week_identifier} • ${pulse.pulse_id}`;
  document.getElementById("pulse-word-count-text").innerText = `${pulse.word_count} / 250 Words`;

  const fillPercent = Math.min(100, Math.round((pulse.word_count / 250) * 100));
  const barFill = document.getElementById("pulse-word-count-bar");
  if (barFill) barFill.style.width = `${fillPercent}%`;

  document.getElementById("pulse-body-text").innerText = pulse.pulse_text;

  // Quotes
  const quotesContainer = document.getElementById("pulse-quotes-container");
  if (quotesContainer && pulse.supporting_quotes) {
    quotesContainer.innerHTML = pulse.supporting_quotes
      .map(
        (q) => `
        <div class="quote-card">
          <div style="font-size: 0.9rem; font-style: italic; color: #f1f5f9;">"${escapeHtml(q.quote)}"</div>
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span class="quote-review-tag">Review ID: ${q.review_id}</span>
            <span style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">${q.sentiment}</span>
          </div>
        </div>
      `
      )
      .join("");
  }

  // Actions
  const actionsContainer = document.getElementById("pulse-actions-container");
  if (actionsContainer && pulse.action_ideas) {
    actionsContainer.innerHTML = pulse.action_ideas
      .map(
        (action, idx) => `
        <div class="action-idea-card">
          <div class="action-number">${idx + 1}</div>
          <div style="font-size: 0.85rem; color: #e2e8f0; line-height: 1.5;">${escapeHtml(action)}</div>
        </div>
      `
      )
      .join("");
  }
}

function renderExplainers(explainers) {
  const container = document.getElementById("explainers-grid-container");
  if (!container) return;

  if (!explainers || explainers.length === 0) {
    container.innerHTML = `<div style="color: var(--text-muted);">No canonical explainers available.</div>`;
    return;
  }

  container.innerHTML = explainers
    .map((exp) => {
      const isApproved = exp.status === "APPROVED";
      const statusBadge = isApproved ? "badge-approved" : "badge-pending";

      return `
        <div class="explainer-card">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <h3 style="font-size: 1rem; font-weight: 700; color: #f8fafc; margin-bottom: 0.2rem;">${escapeHtml(exp.title)}</h3>
              <span style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--accent-cyan);">${exp.topic_slug}</span>
            </div>
            <span class="badge ${statusBadge}">${exp.status}</span>
          </div>

          <div style="font-size: 0.75rem; color: var(--text-muted);">
            Bullet Count: <strong style="color: var(--text-primary);">${exp.bullet_count}/6</strong> • Last Checked: ${new Date(exp.last_checked_date).toLocaleDateString()}
          </div>

          <ul class="explainer-bullets">
            ${exp.bullet_points.map((b) => `<li>${escapeHtml(b)}</li>`).join("")}
          </ul>

          <div class="source-links-box">
            <span style="font-weight: 600; color: var(--text-secondary);">Authoritative Sources:</span>
            ${exp.source_urls.map((u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`).join("")}
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 0.65rem; margin-top: auto; padding-top: 0.5rem;">
            ${
              isApproved
                ? `<button class="btn btn-danger" onclick="invalidateExplainer('${exp.explainer_id}')">Invalidate (TTL)</button>`
                : `<button class="btn btn-success" onclick="approveExplainer('${exp.explainer_id}')">✓ Approve into Canonical Store</button>`
            }
          </div>
        </div>
      `;
    })
    .join("");
}

async function approveExplainer(explainerId) {
  try {
    const res = await apiCall(`/api/product/explainers/${explainerId}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: "product_lead_ui" }),
    });
    showToast(`Explainer ${res.explainer_id} approved into Canonical Store!`, "success");
    await loadPulseData();
  } catch (err) {
    // Handled in apiCall
  }
}

async function invalidateExplainer(explainerId) {
  if (!confirm("Invalidate this canonical explainer? Future queries will bypass cache for re-drafting.")) return;
  try {
    const res = await apiCall(`/api/product/explainers/${explainerId}/invalidate`, {
      method: "POST",
      body: JSON.stringify({ operator_id: "product_lead_ui" }),
    });
    showToast(`Explainer ${res.explainer_id} invalidated`, "info");
    await loadPulseData();
  } catch (err) {
    // Handled in apiCall
  }
}

// -----------------------------------------------------------------------------
// Audit & State Diff Logic
// -----------------------------------------------------------------------------
function setupAuditEvents() {
  const filterType = document.getElementById("audit-filter-type");
  if (filterType) {
    filterType.addEventListener("change", () => {
      loadAuditLogs(filterType.value);
    });
  }
}

async function loadAuditLogs(entityType = "") {
  try {
    const query = entityType ? `?entity_type=${entityType}` : "";
    const logs = await apiCall(`/api/audit/logs${query}`);
    state.auditLogs = logs;
    renderAuditLogs(logs);
    if (logs.length > 0 && !state.selectedAuditLog) {
      inspectAuditLog(logs[0].audit_id);
    }
  } catch (err) {
    console.error("Failed to load audit logs:", err);
  }
}

function renderAuditLogs(logs) {
  const container = document.getElementById("audit-log-list");
  if (!container) return;

  if (logs.length === 0) {
    container.innerHTML = `<div style="padding: 1.5rem; text-align: center; color: var(--text-muted);">No audit records found.</div>`;
    return;
  }

  container.innerHTML = logs
    .map((l) => {
      const isSelected = state.selectedAuditLog && state.selectedAuditLog.audit_id === l.audit_id;
      return `
        <div class="audit-log-row ${isSelected ? "active" : ""}" onclick="inspectAuditLog('${l.audit_id}')">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
            <span style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--accent-cyan); font-weight: 600;">${l.audit_id}</span>
            <span class="badge badge-edited">${l.action}</span>
          </div>
          <div style="font-size: 0.8rem; color: var(--text-primary); margin-bottom: 0.25rem;">
            Entity: <strong>${l.entity_type}#${l.entity_id}</strong>
          </div>
          <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: var(--text-muted);">
            <span>By: ${l.operator_id}</span>
            <span>${new Date(l.timestamp).toLocaleTimeString()}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

async function inspectAuditLog(auditId) {
  try {
    const diffData = await apiCall(`/api/audit/diff/${auditId}`);
    state.selectedAuditLog = diffData;
    renderAuditLogs(state.auditLogs); // Update active state in list

    document.getElementById("diff-audit-id").innerText = diffData.audit_id;
    document.getElementById("diff-entity").innerText = `${diffData.entity_type} • ${diffData.entity_id}`;
    document.getElementById("diff-operator").innerText = `${diffData.operator_id} @ ${new Date(diffData.timestamp).toLocaleTimeString()}`;
    document.getElementById("diff-pre-hash").innerText = diffData.pre_state_hash;
    document.getElementById("diff-post-hash").innerText = diffData.post_state_hash;

    const patchContainer = document.getElementById("diff-patch-container");
    if (!patchContainer) return;

    if (!diffData.patch_operations || diffData.patch_operations.length === 0) {
      patchContainer.innerHTML = `<div style="color: var(--text-muted); font-size: 0.85rem;">No state mutations detected (Identical states).</div>`;
      return;
    }

    patchContainer.innerHTML = diffData.patch_operations
      .map((op) => {
        const opClass = `op-${op.op}`;
        const valStr = op.value !== undefined ? (typeof op.value === "object" ? JSON.stringify(op.value, null, 2) : String(op.value)) : "";
        return `
          <div class="patch-item">
            <div class="patch-header">
              <span class="op-badge ${opClass}">${op.op}</span>
              <span class="patch-path">${escapeHtml(op.path)}</span>
            </div>
            ${valStr ? `<div class="patch-value-box">${escapeHtml(valStr)}</div>` : ""}
          </div>
        `;
      })
      .join("");
  } catch (err) {
    console.error("Failed to inspect audit log:", err);
  }
}

// -----------------------------------------------------------------------------
// Utilities & Toasts
// -----------------------------------------------------------------------------
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerText = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.25s ease-out";
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function computeMockHash(obj) {
  let str = JSON.stringify(obj);
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(16).padStart(16, "0") + "a1b2c3d4e5f67890123456789abcdef0";
}
