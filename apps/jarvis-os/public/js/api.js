/**
 * One seam between the interface and whichever backend serves it.
 *
 * - Standalone (`server.py`, port 4719): the app's own `/api/*` routes.
 * - Nerva hub (`/os` on the hub, port 8080): the hub injects
 *   `<meta name="jarvis-os-hub" content="<base path>">`. Vault routes then live under
 *   `/api/os/*`, chat goes through the hub's own `/chat` (orchestrator, guards and
 *   approval gates), and speech through the hub's `/tts`.
 */

const hubMeta = document.querySelector('meta[name="jarvis-os-hub"]');

/** True when the page is served by the Nerva hub rather than the standalone server. */
export const HUB = hubMeta !== null;

const HUB_ROOT = HUB ? (hubMeta.getAttribute("content") || "").replace(/\/+$/, "") : "";

// Hub routes are written out in full: the hub's route-coverage gate looks for each one.
const HUB_ROUTES = {
  "/status": "/api/os/status",
  "/brain": "/api/os/brain",
  "/brain/note": "/api/os/brain/note",
  "/brain/retrieve": "/api/os/brain/retrieve",
  "/brain/capture": "/api/os/brain/capture",
};

function apiUrl(path) {
  if (!HUB) return `/api${path}`;
  const [name, query] = path.split("?");
  const route = HUB_ROUTES[name];
  // Provider config and CLI sign-in exist only on the standalone server.
  if (!route) throw new Error(`"${name}" is not available when served by the hub`);
  return HUB_ROOT + route + (query ? `?${query}` : "");
}

function authHeaders() {
  if (!HUB) return {};
  // Same key the hub's own HUD stores the user token under (agents/web/static/auth.js).
  let token = "";
  try {
    token = localStorage.getItem("hud.user_token") || "";
  } catch (_) {
    /* storage unavailable: a localhost hub needs no token */
  }
  return token ? { "X-User-Token": token } : {};
}

// An owner signed in through the hub's browser session (cookie, no stored token) must echo
// the session's CSRF token on every write; the hub refuses cookie-authenticated POSTs without it.
let csrfToken = null;

async function loadCsrfToken(force = false) {
  if (csrfToken !== null && !force) return csrfToken;
  csrfToken = "";
  try {
    const res = await fetch(`${HUB_ROOT}/api/auth/session`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (res.ok) {
      const session = await res.json();
      csrfToken = session && session.signed_in ? session.csrf || "" : "";
    }
  } catch (_) {
    /* no session to read: a localhost hub needs none */
  }
  return csrfToken;
}

async function postJson(url, body, retried = false) {
  const headers = { "Content-Type": "application/json", ...authHeaders() };
  // Sent only when no header credential rides along, as the hub's own client does.
  if (HUB && !headers["X-User-Token"]) {
    const csrf = await loadCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(body ?? {}),
  });
  // A stale token (the session was re-opened in another tab) is re-read once.
  if (HUB && res.status === 403 && !retried && headers["X-CSRF-Token"]) {
    let detail = "";
    try {
      detail = String((await res.clone().json()).detail || "");
    } catch (_) {
      /* not a JSON refusal */
    }
    if (detail.startsWith("csrf") && (await loadCsrfToken(true))) return postJson(url, body, true);
  }
  return res;
}

/** GET a vault/status route, e.g. `apiGet("/brain?reindex=1")`. */
export function apiGet(path) {
  return fetch(apiUrl(path), { headers: authHeaders() });
}

/** POST a vault/config route, e.g. `apiPost("/brain/capture", {...})`. */
export function apiPost(path, body) {
  return postJson(apiUrl(path), body);
}

/**
 * Ask the assistant. Resolves to `{ reply, action, provider }`, or `null` when the
 * backend has no answer and the caller should fall back to a local galaxy search.
 */
export async function chat({ prompt, brain, context }) {
  if (!HUB) {
    const res = await apiPost("/chat", { prompt, brain, context });
    const data = await res.json();
    return data && data.reply && data.mode !== "local" ? data : null;
  }

  // Hub: fetch the matching vault notes, then hand them to the orchestrator as fenced
  // attachments (content, never the owner's words) beside the question as typed.
  let grounding = { attachments: [], focus: null };
  try {
    const res = await apiGet(`/brain/retrieve?q=${encodeURIComponent(prompt)}`);
    if (res.ok) grounding = await res.json();
  } catch (_) {
    /* no vault grounding this turn */
  }

  const body = { message: prompt.slice(0, 4096) };
  if (Array.isArray(grounding.attachments) && grounding.attachments.length) {
    body.attachments = grounding.attachments;
  }
  const res = await postJson(`${HUB_ROOT}/chat`, body);
  if (!res.ok) {
    throw new Error(`hub chat answered ${res.status}`);
  }
  const data = await res.json();
  if (!data || !data.reply) return null;

  const focusGalaxy = grounding.focus && context && context.activeView === "galaxy";
  return {
    reply: data.reply,
    action: focusGalaxy
      ? { type: "focus_hub", params: { query: grounding.focus } }
      : { type: "none", params: {} },
    provider: "nerva hub",
  };
}

/**
 * Synthesize speech. Resolves to an audio `Response`, or `null` when the caller should
 * use the browser's own speech synthesis.
 */
export async function tts(text) {
  const res = HUB
    ? await postJson(`${HUB_ROOT}/tts`, { text: text.slice(0, 4096), lang: /[ăâîșț]/i.test(text) ? "ro" : "en" })
    : await apiPost("/tts", { text });
  const ctype = res.headers.get("Content-Type") || "";
  return res.ok && res.status === 200 && ctype.startsWith("audio/") ? res : null;
}

/**
 * In hub mode the provider chain, API keys and vault paths belong to the hub, so the
 * standalone-only settings are hidden instead of offering controls that do nothing.
 */
export function applyBackendMode() {
  if (!HUB) return;
  document.body.dataset.backend = "hub";
  for (const el of document.querySelectorAll("[data-standalone-only]")) {
    el.hidden = true;
  }
  for (const id of ["cfg-vault-path", "cfg-nerva-path"]) {
    const input = document.getElementById(id);
    if (input) input.readOnly = true;
  }
}
