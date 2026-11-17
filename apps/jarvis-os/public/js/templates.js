/**
 * Every HTML string the page builds from data it does not own.
 *
 * Vault note titles, paths, model names, and the parameters a model returns for an
 * action (a campaign name, an objective) are untrusted text. They are written into the
 * page through these builders only, and every value passes through `escapeHtml`, so
 * such text is always rendered as text and can never become markup or an attribute.
 *
 * Pure functions with no DOM access: they run unchanged under Node for the regression
 * test (tests/test_jarvis_os_templates.py).
 */

const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };

/** Text safe for both element content and a quoted attribute value. */
export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"'`]/g, (ch) => ENTITIES[ch]);
}

function index(value) {
  const n = Number(value);
  return Number.isInteger(n) ? n : -1;
}

export function hubRowsHtml(hubs, nodes) {
  return (hubs || [])
    .map((h) => {
      const nodeIdx =
        h.nodeIndex !== undefined ? h.nodeIndex : (nodes || []).findIndex((n) => n.title === h.title);
      const color = escapeHtml(h.color);
      return `
        <div class="hub-row" data-node-idx="${index(nodeIdx)}">
          <div class="hub-left">
            <span class="hub-dot" style="background:${color}; box-shadow:0 0 6px ${color};"></span>
            <span>${escapeHtml(h.title)}</span>
          </div>
          <span class="hub-count">${escapeHtml(h.displayCount)}</span>
        </div>
      `;
    })
    .join("");
}

export function filterRowsHtml(categories) {
  return (categories || [])
    .map(
      (c) => `
      <div class="filter-row" data-cat="${escapeHtml(c.id)}">
        <div class="hub-left">
          <span class="hub-dot" style="background:${escapeHtml(c.color)}"></span>
          <span>${escapeHtml(c.id)}</span>
        </div>
        <span class="hub-count">${escapeHtml(c.count)}</span>
      </div>
    `
    )
    .join("");
}

export function sourceCardsHtml(sources) {
  return (sources || [])
    .map((s) => {
      const isConn = s.status === "connected";
      return `
        <div class="source-item-card">
          <div class="source-item-top">
            <span>${escapeHtml(s.name)}</span>
            <span class="conn-pill ${isConn ? "connected" : ""}">${escapeHtml(s.status)}</span>
          </div>
          <div class="source-item-path">${escapeHtml(s.path)}</div>
          <div class="source-item-detail">${escapeHtml(s.detail)}</div>
        </div>
      `;
    })
    .join("");
}

export function modelOptionsHtml(models) {
  return (models || [])
    .map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)} (Local)</option>`)
    .join("");
}

/** The Ads Manager table. `name` and `objective` can come straight from a model's action. */
export function campaignRowsHtml(campaigns) {
  return (campaigns || [])
    .map(
      (c, i) => `
      <tr class="${c.isDraft ? "draft-row" : ""}">
        <td><input type="checkbox" ${c.on ? "checked" : ""} data-idx="${i}" /></td>
        <td><strong>${escapeHtml(c.name)}</strong> ${c.isDraft ? '<span style="color:#059669;font-size:11px;font-weight:700;">[DRAFT READY]</span>' : ""}</td>
        <td>● ${escapeHtml(c.delivery)}</td>
        <td>${escapeHtml(c.objective)}</td>
        <td>${escapeHtml(c.budget)}/day</td>
        <td>${escapeHtml(c.results)}</td>
        <td>${escapeHtml(c.reach)}</td>
        <td>${escapeHtml(c.cpr)}</td>
      </tr>
    `
    )
    .join("");
}
