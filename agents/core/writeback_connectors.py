"""writeback_connectors.py — 0.66 SaaS Connector Breadth (white-collar suite, pure builders).

Extends the H10.30 write-back family (`writeback.py`: Notion / GitHub / Google Calendar) with
the white-collar project/task suite: **Linear · Asana · Trello · Todoist · ClickUp · Google
Sheets · Microsoft 365 (Outlook draft)**. Same discipline:

* **pure request builders** — ``build_connector_request(target, action, fields, credentials)``
  maps a validated draft onto one concrete HTTP request (method/url/headers/json). No network
  here; the live call is the owner-gated executor step behind the approval queue.
* **host allowlist** — every URL is pinned to the provider's API host (SSRF guard).
* **secrets at execute-time** — builders take the resolved token; drafts carry only a
  ``{{secret:...}}`` handle (SecretBroker resolves it *behind* the approval, mirroring social/
  call brokers). Raw cookies/tokens never live in a draft.
* **validated catalog** — unknown target/action or missing required fields → refused at draft
  time with the reason, never guessed.

Offline-testable end to end; every builder is a deterministic function.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlparse

CONNECTOR_HOSTS = frozenset({
    "api.linear.app", "app.asana.com", "api.trello.com", "api.todoist.com",
    "api.clickup.com", "sheets.googleapis.com", "graph.microsoft.com",
})

_STR_CAP = 2_000
_LONG_CAP = 20_000


def _assert_allowed_host(url: str) -> str:
    host = urlparse(url).hostname or ""
    if host not in CONNECTOR_HOSTS:
        raise ValueError(f"host not allowlisted: {host}")
    return url


def _s(v, cap: int = _STR_CAP) -> str:
    return str(v if v is not None else "").strip()[:cap]


@dataclass(frozen=True)
class ConnectorAction:
    target: str
    action: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    label: str = ""


CATALOG: dict[tuple[str, str], ConnectorAction] = {}


def _reg(target: str, action: str, required, optional=(), label: str = "") -> None:
    CATALOG[(target, action)] = ConnectorAction(target, action, tuple(required),
                                                tuple(optional), label or f"{target}.{action}")


_reg("linear", "create_issue", ("team_id", "title"), ("description",), "Linear: create issue")
_reg("asana", "create_task", ("project_id", "name"), ("notes",), "Asana: create task")
_reg("trello", "create_card", ("list_id", "name"), ("desc",), "Trello: create card")
_reg("todoist", "create_task", ("content",), ("project_id", "due_string"), "Todoist: create task")
_reg("clickup", "create_task", ("list_id", "name"), ("description",), "ClickUp: create task")
_reg("gsheets", "append_row", ("spreadsheet_id", "range", "values"), (), "Sheets: append row")
_reg("m365", "create_draft", ("subject", "body", "to"), (), "Outlook: create mail draft")


def validate_draft(target: str, action: str, fields: dict) -> dict:
    """Validate a connector draft against the catalog. Returns ``{ok, reason?, spec?}``.

    Unknown target/action and missing required fields are refused with the exact reason —
    a draft is never silently 'fixed'.
    """
    spec = CATALOG.get((str(target), str(action)))
    if spec is None:
        return {"ok": False, "reason": f"unknown connector action: {target}.{action}"}
    f = fields if isinstance(fields, dict) else {}
    missing = [k for k in spec.required if not str(f.get(k) or "").strip()
               and f.get(k) not in (0, False) and not isinstance(f.get(k), (list, tuple))]
    # list-typed required fields (e.g. sheets values) count as present when non-empty lists
    missing = [k for k in missing if not (isinstance(f.get(k), (list, tuple)) and f.get(k))]
    if missing:
        return {"ok": False, "reason": f"missing required field(s): {', '.join(missing)}"}
    return {"ok": True, "spec": spec}


def draft_task_payload(target: str, action: str, fields: dict,
                       *, secret_handle: str | None = None) -> dict:
    """Build the ask-tier task payload for the approval queue (parallel to writeback.py).

    Carries a ``{{secret:<target>_token}}`` handle by default — never a raw credential; the
    executor resolves it behind the approval.
    """
    v = validate_draft(target, action, fields)
    if not v["ok"]:
        return {"ok": False, "reason": v["reason"]}
    return {
        "ok": True,
        "kind": f"connector.{target}.{action}",
        "target": target,
        "action": action,
        "fields": {k: fields[k] for k in (*v["spec"].required, *v["spec"].optional)
                   if k in (fields or {})},
        "credential_ref": secret_handle or f"{{{{secret:{target}_token}}}}",
        "label": v["spec"].label,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def build_connector_request(target: str, action: str, fields: dict, credentials: dict) -> dict:
    """Map a validated (target, action, fields) draft onto one concrete HTTP request.

    ``credentials`` carries the execute-time resolved secrets (``token``; Trello additionally
    ``api_key``). Every URL is allowlist-pinned. Raises ``ValueError`` on unknown actions,
    missing fields, or a non-allowlisted host — the executor treats that as a refused draft.
    """
    v = validate_draft(target, action, fields)
    if not v["ok"]:
        raise ValueError(v["reason"])
    f = fields or {}
    creds = credentials or {}
    token = str(creds.get("token") or "")

    if target == "linear":
        # GraphQL — one mutation, variables carry the sanitized fields.
        query = ("mutation IssueCreate($input: IssueCreateInput!) "
                 "{ issueCreate(input: $input) { success issue { id url } } }")
        variables = {"input": {"teamId": _s(f.get("team_id")), "title": _s(f.get("title")),
                               "description": _s(f.get("description"), _LONG_CAP)}}
        return {"method": "POST", "url": _assert_allowed_host("https://api.linear.app/graphql"),
                "headers": {"Authorization": token, "Content-Type": "application/json"},
                "json": {"query": query, "variables": variables}}

    if target == "asana":
        return {"method": "POST",
                "url": _assert_allowed_host("https://app.asana.com/api/1.0/tasks"),
                "headers": _bearer(token),
                "json": {"data": {"projects": [_s(f.get("project_id"))],
                                  "name": _s(f.get("name")),
                                  "notes": _s(f.get("notes"), _LONG_CAP)}}}

    if target == "trello":
        # Trello auths via query params (key+token) — still built here, never in the draft.
        key = quote(str(creds.get("api_key") or ""), safe="")
        tok = quote(token, safe="")
        lid = quote(_s(f.get("list_id")), safe="")
        return {"method": "POST",
                "url": _assert_allowed_host(
                    f"https://api.trello.com/1/cards?idList={lid}&key={key}&token={tok}"),
                "headers": {"Content-Type": "application/json"},
                "json": {"name": _s(f.get("name")), "desc": _s(f.get("desc"), _LONG_CAP)}}

    if target == "todoist":
        body = {"content": _s(f.get("content"))}
        if f.get("project_id"):
            body["project_id"] = _s(f.get("project_id"))
        if f.get("due_string"):
            body["due_string"] = _s(f.get("due_string"))
        return {"method": "POST",
                "url": _assert_allowed_host("https://api.todoist.com/rest/v2/tasks"),
                "headers": _bearer(token), "json": body}

    if target == "clickup":
        lid = quote(_s(f.get("list_id")), safe="")
        return {"method": "POST",
                "url": _assert_allowed_host(f"https://api.clickup.com/api/v2/list/{lid}/task"),
                "headers": {"Authorization": token, "Content-Type": "application/json"},
                "json": {"name": _s(f.get("name")),
                         "description": _s(f.get("description"), _LONG_CAP)}}

    if target == "gsheets":
        sid = quote(_s(f.get("spreadsheet_id")), safe="")
        rng = quote(_s(f.get("range")), safe="")
        values = f.get("values") if isinstance(f.get("values"), (list, tuple)) else []
        row = [_s(v) for v in list(values)[:100]]
        return {"method": "POST",
                "url": _assert_allowed_host(
                    f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{rng}"
                    ":append?valueInputOption=RAW"),
                "headers": _bearer(token), "json": {"values": [row]}}

    if target == "m365":
        to = f.get("to")
        addrs = [_s(a) for a in (to if isinstance(to, (list, tuple)) else [to]) if _s(a)]
        return {"method": "POST",
                "url": _assert_allowed_host("https://graph.microsoft.com/v1.0/me/messages"),
                "headers": _bearer(token),
                "json": {"subject": _s(f.get("subject")),
                         "body": {"contentType": "text", "content": _s(f.get("body"), _LONG_CAP)},
                         "toRecipients": [{"emailAddress": {"address": a}} for a in addrs]}}

    raise ValueError(f"unreachable target: {target}")   # catalog and builders kept in lockstep


def catalog() -> list[dict]:
    """The inspectable connector catalog (for `/api/integrations`-style surfaces)."""
    return [{"target": s.target, "action": s.action, "label": s.label,
             "required": list(s.required), "optional": list(s.optional)}
            for s in CATALOG.values()]
