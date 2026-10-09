"""Narrow, source-backed HTTP protocol descriptor for external chat clients.

This describes mounted routes, not live model/provider capability. Keep the
handler-derived facts explicit where FastAPI's OpenAPI cannot express them.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_CLIENT_ROUTES = (
    ("POST", "/chat", "user"),
    ("POST", "/chat/stream", "user"),
    ("GET", "/sessions", "user"),
    ("POST", "/sessions/resume", "user"),
    ("DELETE", "/sessions/{session_id}", "admin"),
)

_SESSION_LIST = {
    "type": "object", "required": ["sessions"],
    "properties": {"sessions": {"type": "array", "items": {"type": "object"}}},
}
_SESSION_RESUME_REQUEST = {
    "type": "object", "required": ["session_id"],
    "properties": {"session_id": {"type": "string"}},
    "additionalProperties": True,
}
_SESSION_RESUME_RESPONSE = {
    "type": "object", "required": ["ok", "session", "turns", "recap"],
    "properties": {
        "ok": {"type": "boolean"}, "session": {"type": "string"},
        "turns": {"type": "array", "items": {"type": "object"}},
        "recap": {
            "type": "object", "required": ["exchanges", "shown", "total", "text"],
            "properties": {
                "exchanges": {"type": "array"}, "shown": {"type": "integer"},
                "total": {"type": "integer"}, "text": {"type": "string"},
            },
        },
    },
}
_SESSION_DELETE_RESPONSE = {
    "type": "object", "required": ["ok", "session", "backup", "removed", "pruned"],
    "properties": {
        "ok": {"type": "boolean"}, "session": {"type": "string"},
        "backup": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "removed": {"type": "object"},
        "pruned": {"type": "array"},
    },
}
_STREAM_EVENTS = {
    "start": ["type", "agent"],
    "token": ["type", "text"],
    "end": ["type", "agent", "text", "session_id", "pending_approvals", "warming", "notices"],
}


def _openapi_media(operation: dict[str, Any], field: str) -> dict[str, Any] | None:
    """Copy the one declared JSON body/200 response without unrelated errors."""
    container = operation.get("requestBody", {}) if field == "request" else operation.get("responses", {}).get("200", {})
    content = container.get("content", {})
    if not content:
        return None
    media = "application/json" if "application/json" in content else next(iter(content))
    result = {"media_type": media, "schema": deepcopy(content[media].get("schema", {})), "source": "openapi"}
    if field == "request":
        result["required"] = bool(container.get("required", False))
    else:
        result["status"] = 200
    return result


def _schema_refs(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set()
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for item in value.values():
            found.update(_schema_refs(item))
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            found.update(_schema_refs(item))
        return found
    return set()


def _required_schemas(routes: list[dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
    definitions = source.get("components", {}).get("schemas", {})
    names = _schema_refs(routes)
    included: dict[str, Any] = {}
    while names:
        name = names.pop()
        if name in included:
            continue
        if name not in definitions:
            raise ValueError("OpenAPI references an unavailable component schema")
        included[name] = deepcopy(definitions[name])
        names.update(_schema_refs(included[name]) - included.keys())
    return dict(sorted(included.items()))


def describe_client_protocol(app: Any) -> dict[str, Any]:
    """Project five known contracts only when the app actually mounts them."""
    source = app.openapi()
    paths = source.get("paths", {})
    routes = []
    for method, path, auth in _CLIENT_ROUTES:
        operation = paths.get(path, {}).get(method.lower())
        if not isinstance(operation, dict):
            continue
        row: dict[str, Any] = {
            "method": method, "path": path, "auth": auth,
            "parameters": deepcopy(operation.get("parameters", [])),
            "request": _openapi_media(operation, "request"),
            "response": _openapi_media(operation, "response"),
        }
        if path == "/chat/stream":
            # StreamingResponse declares no useful OpenAPI body type here.
            row["response"] = {"media_type": "text/event-stream", "schema": None, "source": "handler", "status": 200}
            row["stream_events"] = deepcopy(_STREAM_EVENTS)
        elif path == "/sessions":
            row["response"] = {"media_type": "application/json", "schema": deepcopy(_SESSION_LIST), "source": "handler", "status": 200}
            row["semantics"] = {"limit": 20, "archived_default": False}
        elif path == "/sessions/resume":
            row["request"] = {"media_type": "application/json", "schema": deepcopy(_SESSION_RESUME_REQUEST), "source": "handler", "required": True}
            row["response"] = {"media_type": "application/json", "schema": deepcopy(_SESSION_RESUME_RESPONSE), "source": "handler", "status": 200}
            row["semantics"] = {
                "requires_existing_session": True, "sets_active_session": True,
                "may_unarchive": True, "turns_limit": 20,
            }
        elif path == "/sessions/{session_id}":
            row["response"] = {"media_type": "application/json", "schema": deepcopy(_SESSION_DELETE_RESPONSE), "source": "handler", "status": 200}
            row["semantics"] = {
                "confirm_query_value": "DELETE",
                "orphan_outcomes_cleanup_without_session": True,
            }
        routes.append(row)

    readiness = (
        {"href": "/api/capabilities", "auth": "user"}
        if "get" in paths.get("/api/capabilities", {}) else None
    )
    return {
        "descriptor_schema": 1,
        "protocol_version": None,
        "server_version": app.version,
        "routes": routes,
        "components": {"schemas": _required_schemas(routes, source)},
        "auth": {
            "user": {
                "headers": ["X-User-Token", "X-Admin-Token"],
                "when_configured": (
                    "The user credential branch applies when a user env token exists, or the "
                    "store has a persisted revocation marker or an extant issued/expired user "
                    "token row, or this process retains a positive in-process memo for that "
                    "store. This branch accepts a valid X-User-Token or X-Admin-Token."
                ),
                "local_fallback": (
                    "When that predicate is false, only a loopback origin is allowed; forwarded "
                    "origins count only through a configured trusted proxy. Revoking the sole "
                    "issued token without a revocation marker can restore localhost fallback "
                    "after process restart."
                ),
                "admin_only_configuration": (
                    "A valid admin credential alone does not enable remote user routes when the "
                    "user credential predicate is false; the localhost-only branch still applies."
                ),
            },
            "admin": {
                "headers": ["X-Admin-Token"],
                "when_configured": (
                    "The admin credential branch applies when an admin env token exists, or the "
                    "store has a persisted revocation marker or an extant issued/expired admin "
                    "token row, or this process retains a positive in-process memo for that "
                    "store. This branch requires a valid X-Admin-Token."
                ),
                "local_fallback": (
                    "When that predicate is false, only a loopback origin is allowed; forwarded "
                    "origins count only through a configured trusted proxy. Revoking the sole "
                    "issued token without a revocation marker can restore localhost fallback "
                    "after process restart."
                ),
            },
        },
        "compatibility": {
            "chat_session_id": "optional JSON body field",
            "chat_session_id_returned_in": "/chat response body or /chat/stream end event",
            "session_header": None,
            "explicit_session_requires_saved_history": True,
            "explicit_session_hydrated_before_turn": True,
            "chat_message_must_be_nonblank": True,
            "chat_model_override": False,
            "chat_provider_override": False,
            "idempotency_key_supported": False,
            "idempotency_key_note": "POST chat and resume do not consume Idempotency-Key; no keyed replay or deduplication guarantee is offered.",
        },
        "readiness": readiness,
    }
