"""
writeback.py — H10.30 Governed write-back integrations.

Agents write back into external systems (Notion, GitHub Issues, Google Calendar)
as native tools — but ONLY through the approval queue. This module is the
*governance* layer:

    request → validate against a known (target, action) allowlist
            → build a governed task (autonomy_level="ask", external risk tier)
            → enqueue it (held as `proposed`, never auto-run).

Nothing is written externally here. The live API call is performed by a
registered executor handler (``WriteBackBroker.execute``) that the autonomy
worker dispatches only for an **already-approved** task, and which:

  1. resolves credentials from the SecretBroker **at action time, behind
     approval** — the agent only ever stored a ``{{secret:...}}`` handle, never
     a raw token (H15.4);
  2. calls through an INJECTABLE client. The default client is offline
     (:class:`NullWriteBackClient`); the real one (:class:`HttpWriteBackClient`)
     is a thin host-side seam that maps each (target, action) onto a concrete
     HTTP request via :func:`build_request`.

Mirrors the shipped governance pattern of TranscriptWatcher (H12.25) and
PaymentBroker (H16.3): build → gate → approve → execute, with a deferred rail.
Pure-Python and offline-testable; the enqueue sink, secret broker, and live
client are all injected.

Live rail (default-off): ``JARVIS_WRITEBACK_LIVE=1`` constructs the broker with
:class:`HttpWriteBackClient` instead of the Null client. Unset, the broker is
byte-identical to before (Null client, lazy upgrade only when an approved task
resolves a real credential). The white-collar connector suite (0.66,
``writeback_connectors``: Linear/Asana/Trello/Todoist/ClickUp/Sheets/M365) is
wired through the same broker — ``request`` accepts connector targets, ``execute``
builds their requests via ``build_connector_request`` — and approved
``create_task`` / ``task.create`` tasks (H12.25 transcript watcher) are mapped
onto a Todoist/Notion write instead of falling through to the LLM handler.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from . import writeback_connectors as _wbc
from .automation_contracts import ContractTemplate, predicate
from .autonomy.dry_run import preview_task
from .env_config import env_flag
from .security.secret_broker import SecretBroker

logger = logging.getLogger("jarvis.writeback")

# SSRF guard: the live rail may only reach these fixed provider API hosts. Field
# input can shape the path but never the host (defense-in-depth + breaks the
# CodeQL SSRF taint flow).
_ALLOWED_HOSTS = frozenset({"api.notion.com", "api.github.com", "www.googleapis.com"})


def _assert_allowed_host(url: str, allowed=_ALLOWED_HOSTS) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed:
        raise ValueError(f"write-back host not allowed: {host!r}")
    return host

# External writes always ask. Tier 2 = "external" in the 4-tier policy, which
# maps to ASK; `autonomy_level="ask"` is also passed explicitly to the queue.
_RISK_TIER = 2
_KIND_PREFIX = "writeback."

# target → the secret name whose value is injected at execution time.
_CREDENTIAL: dict[str, str] = {
    "notion": "notion_api_key",
    "github": "github_token",
    "google_calendar": "google_oauth_token",
}

# Live rail flag (default-off). Read at call time, never cached (env_config rule).
LIVE_FLAG = "JARVIS_WRITEBACK_LIVE"


def live_rail_enabled() -> bool:
    """True only when the owner explicitly set ``JARVIS_WRITEBACK_LIVE``."""
    return env_flag(LIVE_FLAG)


# Kinds the H12.25 transcript watcher enqueues (``create_task``; ``task.create``
# is the dotted spelling used by the one-PR plan) — mapped onto a connector write.
TASK_CREATE_KINDS = frozenset({"create_task", "task.create"})


def _lookup(target: str, action: str):
    """Catalog spec for (target, action) from the H10.30 or the 0.66 connector catalog."""
    key = ((target or "").lower(), (action or "").lower())
    return _CATALOG.get(key) or _wbc.CATALOG.get(key)


def _is_connector(target: str, action: str) -> bool:
    key = ((target or "").lower(), (action or "").lower())
    return key not in _CATALOG and key in _wbc.CATALOG


def _credential_name(target: str) -> str:
    target = (target or "").lower()
    return _CREDENTIAL.get(target) or _wbc.credential_names(target).get("token", "")


# Field hygiene: cap sizes so a write-back can't smuggle an oversized payload.
_LIST_FIELDS = {"labels", "assignees", "attendees"}
_LONG_FIELDS = {"content": 50_000, "body": 50_000, "description": 20_000}
_STR_CAP = 2_000
_LIST_ITEM_CAP = 200
_LIST_MAX = 50


@dataclass(frozen=True)
class WriteAction:
    """A single supported write into an external system."""

    target: str
    action: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    label: str = ""


# Allowlist of supported (target, action) pairs — insertion order preserved.
_CATALOG: "dict[tuple[str, str], WriteAction]" = {}


def _reg(target: str, action: str, required, optional=(), label: str = "") -> None:
    _CATALOG[(target, action)] = WriteAction(
        target, action, tuple(required), tuple(optional), label
    )


_reg("notion", "create_page", ("title",), ("parent", "content"), "Create Notion page")
_reg("notion", "append_block", ("page_id", "text"), (), "Append to Notion page")
_reg("github", "create_issue", ("repo", "title"),
     ("body", "labels", "assignees"), "Create GitHub issue")
_reg("github", "comment_issue", ("repo", "issue", "body"), (), "Comment on GitHub issue")
_reg("google_calendar", "create_event", ("summary", "start", "end"),
     ("calendar_id", "description", "location", "attendees"), "Create Calendar event")


def _present(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, tuple, dict)):
        return len(v) > 0
    return True


def _sanitize_fields(spec: WriteAction, fields: Optional[dict]) -> "tuple[dict, list[str]]":
    """Keep only known fields, coerce + cap them, and report missing required ones."""
    fields = fields or {}
    allowed = set(spec.required) | set(spec.optional)
    clean: dict = {}
    for k in allowed:
        if k not in fields:
            continue
        v = fields[k]
        if k in _LIST_FIELDS:
            if isinstance(v, str):
                v = [v]
            if not isinstance(v, (list, tuple)):
                continue
            items = [str(x)[:_LIST_ITEM_CAP] for x in v if _present(x)][:_LIST_MAX]
            if items:
                clean[k] = items
        else:
            s = str(v)[: _LONG_FIELDS.get(k, _STR_CAP)]
            if _present(s):
                clean[k] = s
    missing = [k for k in spec.required if k not in clean]
    return clean, missing


def _human_target(target: str, fields: dict) -> str:
    """A readable target string for the preview / decision card."""
    if target == "github":
        repo = fields.get("repo", "")
        issue = fields.get("issue")
        return f"{repo}#{issue}" if issue else (repo or "github")
    if target == "notion":
        return fields.get("title") or fields.get("page_id") or "notion"
    if target == "google_calendar":
        return fields.get("summary") or "calendar event"
    for k in ("name", "content", "title", "subject", "spreadsheet_id"):
        if fields.get(k):
            return str(fields[k])[:80]
    return target or "external"


def _writeback_draft_contract_template() -> ContractTemplate:
    """Contract form of the existing governed write-back draft gate."""
    def writeback_kind(view, now):
        kind = view.get("kind")
        return isinstance(kind, str) and kind.startswith(_KIND_PREFIX)

    def system_action_allowed(view, now):
        system, action = view.get("system"), view.get("action")
        if not isinstance(system, str) or not isinstance(action, str):
            return False
        return _lookup(system, action) is not None

    def required_fields_present(view, now):
        system, action = view.get("system"), view.get("action")
        if not isinstance(system, str) or not isinstance(action, str):
            return False
        spec = _lookup(system, action)
        fields = view.get("fields")
        if spec is None or not isinstance(fields, dict):
            return False
        if _is_connector(system, action):
            return not _wbc.missing_required(spec, fields)
        return all(_present(fields.get(k)) for k in spec.required)

    def credential_ref_matches(view, now):
        system = view.get("system")
        cred_name = _credential_name(system) if isinstance(system, str) else ""
        expected = SecretBroker.reference(cred_name) if cred_name else ""
        return view.get("credential_ref") == expected

    return ContractTemplate(kind="writeback_draft", constraints=(
        predicate("writeback_kind", writeback_kind, reason="invalid_kind"),
        predicate("system_action_allowed", system_action_allowed,
                  reason="unknown_target_action"),
        predicate("required_fields_present", required_fields_present,
                  reason="missing_fields"),
        predicate("credential_ref_matches", credential_ref_matches,
                  reason="credential_ref_mismatch"),
    ), description="Admissibility for governed write-back draft requests.")


WRITEBACK_DRAFT_CONTRACT = _writeback_draft_contract_template()


# ── concrete HTTP request building (pure, offline-testable) ──────────────────

def _notion_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"}


def _github_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _bearer_json(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def build_request(target: str, action: str, fields: dict, credentials: dict) -> dict:
    """Map a (target, action, fields) write onto a concrete HTTP request.

    Pure + offline-testable. Returns ``{method, url, headers, json}``. The caller
    (:class:`HttpWriteBackClient`) performs the actual network call — this only
    builds it, which keeps the live seam thin and reviewable.
    """
    target = (target or "").lower()
    action = (action or "").lower()
    token = (credentials or {}).get("token", "")
    f = fields or {}

    if target == "notion" and action == "create_page":
        parent = f.get("parent") or ""
        body: dict = {
            "parent": ({"page_id": parent} if parent else {"workspace": True}),
            "properties": {"title": [{"text": {"content": f.get("title", "")}}]},
        }
        if f.get("content"):
            body["children"] = [{
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": str(f["content"])[:1900]}}]},
            }]
        return {"method": "POST", "url": "https://api.notion.com/v1/pages",
                "headers": _notion_headers(token), "json": body}

    if target == "notion" and action == "append_block":
        page_id = f.get("page_id", "")
        body = {"children": [{
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": str(f.get("text", ""))[:1900]}}]},
        }]}
        return {"method": "PATCH",
                "url": f"https://api.notion.com/v1/blocks/{page_id}/children",
                "headers": _notion_headers(token), "json": body}

    if target == "github" and action == "create_issue":
        repo = f.get("repo", "")
        body = {"title": f.get("title", "")}
        for k in ("body", "labels", "assignees"):
            if f.get(k):
                body[k] = f[k]
        return {"method": "POST",
                "url": f"https://api.github.com/repos/{repo}/issues",
                "headers": _github_headers(token), "json": body}

    if target == "github" and action == "comment_issue":
        repo = f.get("repo", "")
        issue = f.get("issue", "")
        return {"method": "POST",
                "url": f"https://api.github.com/repos/{repo}/issues/{issue}/comments",
                "headers": _github_headers(token), "json": {"body": f.get("body", "")}}

    if target == "google_calendar" and action == "create_event":
        cal = f.get("calendar_id") or "primary"
        body = {"summary": f.get("summary", ""),
                "start": {"dateTime": f.get("start", "")},
                "end": {"dateTime": f.get("end", "")}}
        if f.get("description"):
            body["description"] = f["description"]
        if f.get("location"):
            body["location"] = f["location"]
        if f.get("attendees"):
            body["attendees"] = [{"email": e} for e in f["attendees"]]
        return {"method": "POST",
                "url": f"https://www.googleapis.com/calendar/v3/calendars/{cal}/events",
                "headers": _bearer_json(token), "json": body}

    raise ValueError(f"unsupported write-back: {target}.{action}")


def build_any_request(target: str, action: str, fields: dict, credentials: dict) -> dict:
    """Build the concrete HTTP request for either catalog, host-allowlist enforced.

    H10.30 targets go through :func:`build_request` (``_ALLOWED_HOSTS``); 0.66
    connectors through :func:`writeback_connectors.build_connector_request`
    (``CONNECTOR_HOSTS``). Raises ``ValueError`` for unknown pairs or a URL that
    escaped its allowlist — the live client never sends such a request.
    """
    if _is_connector(target, action):
        spec = _wbc.build_connector_request((target or "").lower(), (action or "").lower(),
                                            fields, credentials)
        _assert_allowed_host(spec["url"], _wbc.CONNECTOR_HOSTS)
        return spec
    spec = build_request(target, action, fields, credentials)
    _assert_allowed_host(spec["url"])   # SSRF guard before any request
    return spec


# ── write-back clients (the deferred live rail) ──────────────────────────────

class NullWriteBackClient:
    """Offline default — records the call, performs NO network I/O.

    This is what makes the governance layer 100% offline-testable: the task
    flows all the way through approval + execution, but the terminal network
    write is a no-op until a real client is wired host-side.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def write(self, target: str, action: str, fields: dict, credentials: dict) -> dict:
        self.calls.append({"target": target, "action": action, "fields": fields,
                           "has_credential": bool((credentials or {}).get("token"))})
        # Honesty layer (Live-vs-Plumbing): a deferred write-back is a degraded
        # result — stamp it so the HUD/callers can badge it and name the fix.
        from .plugins.degradation import degraded
        cred_name = _credential_name(target) or "credential"
        return degraded(
            {"status": "deferred", "target": target, "action": action,
             "note": "no live write-back client configured — host seam"},
            reason="writeback_credential_not_configured",
            needs=[f"secret:{cred_name}"],
        )


class HttpWriteBackClient:
    """Live rail (host-side seam): builds the request and sends it over HTTP.

    The HTTP transport is injectable (``http`` must expose an async
    ``request(method, url, headers=, json=)`` like PluginHTTPClient), so this is
    still offline-testable with a mocked client; only a real, configured
    deployment performs an actual network write.
    """

    def __init__(self, http=None) -> None:
        self._http = http

    async def write(self, target: str, action: str, fields: dict, credentials: dict) -> dict:
        spec = build_any_request(target, action, fields, credentials)  # host-guarded
        http = self._http
        if http is None:  # pragma: no cover - real network path
            from .http_client import PluginHTTPClient
            http = PluginHTTPClient.for_plugin(f"writeback_{target}")
        kwargs: dict = {"headers": spec.get("headers"), "json": spec.get("json")}
        if spec.get("params"):
            kwargs["params"] = spec["params"]   # Trello: credentials as query params
        resp = await http.request(spec["method"], spec["url"], **kwargs)
        resp.raise_for_status()
        out: dict = {"status": "ok", "http_status": getattr(resp, "status_code", None)}
        try:
            out["response"] = resp.json()
        except Exception:
            # non-JSON response body → omit it from the result
            pass
        return out


# ── H12.25: approved transcript action items → connector writes ──────────────

_TASK_TEXT_CAP = 500


def _is_task_create(kind, payload: dict) -> bool:
    if isinstance(kind, str) and kind.lower() in TASK_CREATE_KINDS:
        return True
    # Kind-less callers (tests, older queues): the transcript watcher's payload shape.
    return (payload.get("action") == "create_task" and "text" in payload
            and "fields" not in payload)


def map_task_create(payload: dict) -> dict:
    """Map an H12.25 ``create_task`` payload onto a governed write-back payload.

    ``{"system": "todoist"|"notion", "text": ..., "assignee": ..., "source": ...}``
    becomes a Todoist ``create_task`` (connector suite) or a Notion
    ``create_page`` (H10.30) with the credential *handle* the executor resolves
    behind approval. Pure; unknown systems or empty text are refused with the
    reason — nothing is guessed.
    """
    system = str(payload.get("system") or "").strip().lower()
    text = str(payload.get("text") or "").strip()[:_TASK_TEXT_CAP]
    assignee = str(payload.get("assignee") or "").strip()[:120]
    source = str(payload.get("source") or "").strip()[:200]
    if not text:
        return {"ok": False, "reason": "missing_fields", "missing": ["text"]}
    if system == "todoist":
        target, action = "todoist", "create_task"
        fields: dict = {"content": text}
    elif system == "notion":
        target, action = "notion", "create_page"
        notes = [f"Assignee: {assignee}" if assignee else "",
                 f"Source: {source}" if source else ""]
        fields = {"title": text}
        content = "\n".join(n for n in notes if n)
        if content:
            fields["content"] = content
    else:
        return {"ok": False, "reason": "unknown_task_system", "system": system}
    spec = _lookup(target, action)
    if _is_connector(target, action):
        clean = _wbc.sanitize_fields(spec, fields)
    else:
        clean, _missing = _sanitize_fields(spec, fields)
    cred_name = _credential_name(target)
    return {"ok": True, "payload": {
        "system": target, "action": action, "fields": clean,
        "credential_ref": SecretBroker.reference(cred_name) if cred_name else "",
        "source": source, "target": _human_target(target, clean),
        "assignee": assignee, "mapped_from": "create_task",
    }}


# ── the broker ───────────────────────────────────────────────────────────────

class WriteBackBroker:
    """Governs external write-backs: request → gated task → approve → execute."""

    KIND_PREFIX = _KIND_PREFIX

    def __init__(self, enqueue: Optional[Callable] = None, agent: str = "pepper",
                 secret_broker=None, client=None, audit=None, kernel=None,
                 http=None) -> None:
        # enqueue(agent, kind, title, payload=, risk_tier=, autonomy_level=, origin=) -> id
        self._enqueue = enqueue
        self.agent = agent
        self._secrets = secret_broker
        # An explicitly injected client (tests, custom rails) is never replaced;
        # only the default NullWriteBackClient may lazily upgrade to the live rail.
        self._client_injected = client is not None
        # Live rail behind the flag: JARVIS_WRITEBACK_LIVE=1 → the HTTP client
        # (transport injectable via ``http`` for tests). Unset → Null client,
        # byte-identical to the pre-flag behaviour.
        self.live = client is None and live_rail_enabled()
        if client is None and self.live:
            client = HttpWriteBackClient(http=http)
        self._client = client or NullWriteBackClient()
        self._audit = audit
        self._kernel = kernel   # ORIZONT-24 K1: bound kernel.authorize (default-off)

    # ── catalog ──────────────────────────────────────────────────────────────

    @staticmethod
    def supports(target: str, action: str) -> bool:
        return _lookup(target, action) is not None

    def connector_targets(self) -> list[dict]:
        """The 0.66 connector suite, exposed with the same shape as :meth:`targets`."""
        return [
            {"target": s.target, "action": s.action, "label": s.label,
             "required": list(s.required), "optional": list(s.optional),
             "kind": f"{self.KIND_PREFIX}{s.target}.{s.action}",
             "credential": _wbc.credential_names(s.target).get("token", "")}
            for s in _wbc.CATALOG.values()
        ]

    def targets(self) -> list[dict]:
        return [
            {"target": s.target, "action": s.action, "label": s.label,
             "required": list(s.required), "optional": list(s.optional),
             "kind": f"{self.KIND_PREFIX}{s.target}.{s.action}",
             "credential": _CREDENTIAL.get(s.target, "")}
            for s in _CATALOG.values()
        ]

    # ── request (governance entry point — no network) ────────────────────────

    def request(self, target: str, action: str, fields: Optional[dict] = None,
                agent: Optional[str] = None, source: str = "") -> dict:
        """Validate + enqueue a governed write-back. Never writes externally.

        With no enqueue sink this is a **preview** (validation + dry-run only).
        """
        target = (target or "").strip().lower()
        action = (action or "").strip().lower()
        spec = _lookup(target, action)
        if spec is None:
            return {"ok": False, "reason": "unknown_target_action",
                    "supported": sorted(f"{t}.{a}" for (t, a) in _CATALOG)
                    + sorted(f"{t}.{a}" for (t, a) in _wbc.CATALOG)}

        if _is_connector(target, action):
            missing = _wbc.missing_required(spec, fields or {})
            clean = _wbc.sanitize_fields(spec, fields or {})
        else:
            clean, missing = _sanitize_fields(spec, fields)
        if missing:
            return {"ok": False, "reason": "missing_fields", "missing": missing,
                    "required": list(spec.required)}

        kind = f"{self.KIND_PREFIX}{target}.{action}"
        cred_name = _credential_name(target)
        cred_ref = SecretBroker.reference(cred_name) if cred_name else ""
        human = _human_target(target, clean)
        title = f"{spec.label}: {human}" if spec.label else f"{kind} → {human}"
        payload = {
            "system": target,        # which integration (matches H12.25 "system")
            "action": action,
            "fields": clean,         # sanitized — no secrets, no stray keys
            "credential_ref": cred_ref,
            "source": source,
            "target": human,         # readable target for preview / inbox card
        }
        if _is_connector(target, action):
            # Handles only (Trello carries a second slot) — never a value.
            payload["credential_refs"] = _wbc.credential_refs(target)
        contract_payload = {
            **payload,
            "kind": kind,
            "agent": agent or self.agent,
            "risk_tier": _RISK_TIER,
        }
        try:
            decision = WRITEBACK_DRAFT_CONTRACT.evaluate(contract_payload, now=time.time())
        except Exception:
            logger.warning("write-back draft contract evaluation failed", exc_info=True)
            return {"ok": False, "reason": "contract_error", "kind": kind}
        if not decision.admissible:
            reason = decision.reason or "contract_denied"
            self._record("writeback.deny", reason, target=human)
            return {"ok": False, "reason": reason, "kind": kind}
        preview = preview_task({"kind": kind, "title": title,
                                "payload": payload, "risk_tier": _RISK_TIER})

        # ORIZONT-24 K1: route through the Action Kernel when enabled (default-off →
        # skipped, path below byte-identical to before).
        autonomy_level = "ask"
        if self._kernel is not None:
            from .action_origin import current_action_origin
            from .kernel import Action, Verdict, kernel_enabled
            if kernel_enabled():
                decision = self._kernel(Action(kind=kind, agent=agent or self.agent,
                                               title=title, payload=payload,
                                               origin=current_action_origin()))
                if decision.verdict is Verdict.DENY:
                    return {"ok": False, "reason": decision.reason, "kind": kind}
                if decision.verdict is Verdict.GRANT:
                    autonomy_level = "act"
        if self._enqueue is None:
            return {"ok": True, "queued": False, "kind": kind, "title": title,
                    "payload": payload, "preview": preview}
        try:
            task_id = self._enqueue(agent or self.agent, kind, title, payload=payload,
                                    risk_tier=_RISK_TIER, autonomy_level=autonomy_level,
                                    origin="generated")
        except Exception:
            logger.warning("write-back enqueue failed", exc_info=True)
            return {"ok": False, "reason": "enqueue_failed", "kind": kind}

        self._record("writeback.request", f"{target}.{action}", target=human)
        return {"ok": True, "queued": True, "task_id": task_id, "kind": kind,
                "title": title, "preview": preview}

    # ── execute (executor handler — only ever called on an approved task) ─────

    async def execute(self, task) -> dict:
        payload = getattr(task, "payload", None) or {}
        mapped_from = None
        if _is_task_create(getattr(task, "kind", None), payload):
            # H12.25: an APPROVED transcript action item → one connector write.
            mapped = map_task_create(payload)
            if not mapped.get("ok"):
                return {"status": "failed", "reason": mapped.get("reason", "invalid_task"),
                        "target": payload.get("system"), "action": "create_task"}
            payload = mapped["payload"]
            mapped_from = "create_task"
        target = payload.get("system") or payload.get("target")
        action = payload.get("action")
        fields = payload.get("fields") or {}
        if not self.supports(target, action):
            return {"status": "failed", "reason": "unknown_target_action",
                    "target": target, "action": action}
        target = (target or "").lower()
        action = (action or "").lower()
        # Credentials are resolved here — at action time, behind approval. The
        # worker only dispatches APPROVED tasks, so reaching this point means the
        # human (or policy) already approved the write.
        credentials = self._resolve_credentials(payload, target)
        if isinstance(self._client, HttpWriteBackClient) and not credentials.get("token"):
            # Live rail armed but the owner never stored the credential: refuse
            # with the exact missing secret rather than sending an unauthenticated
            # request (honest degradation, nothing fabricated).
            cred_name = _credential_name(target) or "credential"
            self._record("writeback.refuse", "credential_not_configured", target=target)
            return {"status": "failed", "reason": "credential_not_configured",
                    "target": target, "action": action,
                    "needs": [f"secret:{cred_name}"]}
        # Live-vs-Plumbing: the moment an approved task resolves a REAL owner
        # credential, the default Null client upgrades to the live HTTP rail —
        # no restart needed, still strictly behind the approval funnel (this
        # method only runs on approved tasks). Unconfigured stays honestly
        # deferred; injected clients are never overridden.
        if (not self._client_injected and credentials.get("token")
                and isinstance(self._client, NullWriteBackClient)):
            logger.info("write-back live rail active — credential resolved, "
                        "using HttpWriteBackClient")
            self._client = HttpWriteBackClient()
        try:
            result = await self._client.write(target, action, fields, credentials)
        except Exception:
            logger.warning("write-back execute failed", exc_info=True)
            return {"status": "failed", "reason": "client_error",
                    "target": target, "action": action}
        self._record("writeback.execute", f"{target}.{action}", target=target)
        out = {"status": "ok", "target": target, "action": action, "writeback": result}
        if mapped_from:
            out["mapped_from"] = mapped_from
        return out

    # ── internals ────────────────────────────────────────────────────────────

    def _resolve_credentials(self, payload: dict, target: str = "") -> dict:
        ref = payload.get("credential_ref") or ""
        token = ""
        if ref and self._secrets is not None:
            out = self._secrets.inject(ref, approved=True)
            if not out.get("blocked"):
                token = out.get("text", "")
        creds = {"token": token}
        if target and target not in _CREDENTIAL and _wbc.credential_names(target):
            # Connector suite: the SecretBroker resolves every slot (Trello also
            # needs ``api_key``); the draft's own ``credential_ref`` wins for ``token``.
            resolved = _wbc.resolve_credentials(target, self._secrets)
            for slot, value in resolved.items():
                if slot == "token" and token:
                    continue
                creds[slot] = value
        return creds

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "record"):
                self._audit.record(actor="writeback", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:  # pragma: no cover - audit is best-effort
            pass
