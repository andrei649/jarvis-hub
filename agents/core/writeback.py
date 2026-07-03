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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from .autonomy.dry_run import preview_task
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

# target → the secret name whose value is injected at execution time.
_CREDENTIAL: dict[str, str] = {
    "notion": "notion_api_key",
    "github": "github_token",
    "google_calendar": "google_oauth_token",
}

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
    return target or "external"


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
        return {"status": "deferred", "target": target, "action": action,
                "note": "no live write-back client configured — host seam"}


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
        spec = build_request(target, action, fields, credentials)
        _assert_allowed_host(spec["url"])   # SSRF guard before any request
        http = self._http
        if http is None:  # pragma: no cover - real network path
            from .http_client import PluginHTTPClient
            http = PluginHTTPClient.for_plugin(f"writeback_{target}")
        resp = await http.request(spec["method"], spec["url"],
                                  headers=spec["headers"], json=spec["json"])
        resp.raise_for_status()
        out: dict = {"status": "ok", "http_status": getattr(resp, "status_code", None)}
        try:
            out["response"] = resp.json()
        except Exception:
            # non-JSON response body → omit it from the result
            pass
        return out


# ── the broker ───────────────────────────────────────────────────────────────

class WriteBackBroker:
    """Governs external write-backs: request → gated task → approve → execute."""

    KIND_PREFIX = "writeback."

    def __init__(self, enqueue: Optional[Callable] = None, agent: str = "pepper",
                 secret_broker=None, client=None, audit=None, kernel=None) -> None:
        # enqueue(agent, kind, title, payload=, risk_tier=, autonomy_level=, origin=) -> id
        self._enqueue = enqueue
        self.agent = agent
        self._secrets = secret_broker
        self._client = client or NullWriteBackClient()
        self._audit = audit
        self._kernel = kernel   # ORIZONT-24 K1: bound kernel.authorize (default-off)

    # ── catalog ──────────────────────────────────────────────────────────────

    @staticmethod
    def supports(target: str, action: str) -> bool:
        return ((target or "").lower(), (action or "").lower()) in _CATALOG

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
        spec = _CATALOG.get((target, action))
        if spec is None:
            return {"ok": False, "reason": "unknown_target_action",
                    "supported": sorted(f"{t}.{a}" for (t, a) in _CATALOG)}

        clean, missing = _sanitize_fields(spec, fields)
        if missing:
            return {"ok": False, "reason": "missing_fields", "missing": missing,
                    "required": list(spec.required)}

        kind = f"{self.KIND_PREFIX}{target}.{action}"
        cred_name = _CREDENTIAL.get(target, "")
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
        target = payload.get("system") or payload.get("target")
        action = payload.get("action")
        fields = payload.get("fields") or {}
        if not self.supports(target, action):
            return {"status": "failed", "reason": "unknown_target_action",
                    "target": target, "action": action}
        # Credentials are resolved here — at action time, behind approval. The
        # worker only dispatches APPROVED tasks, so reaching this point means the
        # human (or policy) already approved the write.
        credentials = self._resolve_credentials(payload)
        try:
            result = await self._client.write(target, action, fields, credentials)
        except Exception:
            logger.warning("write-back execute failed", exc_info=True)
            return {"status": "failed", "reason": "client_error",
                    "target": target, "action": action}
        self._record("writeback.execute", f"{target}.{action}", target=target)
        return {"status": "ok", "target": target, "action": action, "writeback": result}

    # ── internals ────────────────────────────────────────────────────────────

    def _resolve_credentials(self, payload: dict) -> dict:
        ref = payload.get("credential_ref") or ""
        token = ""
        if ref and self._secrets is not None:
            out = self._secrets.inject(ref, approved=True)
            if not out.get("blocked"):
                token = out.get("text", "")
        return {"token": token}

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
