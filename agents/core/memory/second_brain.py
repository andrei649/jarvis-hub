"""Read-only, local-only bridge to the owner's configured Second Brain sources.

No source path is bundled with Nerva. Callers must check the turn's actual route
before invoking this module: a raw result is never eligible for cloud routing.
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import sqlite3
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import closing, contextmanager
from contextvars import ContextVar
from pathlib import Path

from agents.core.env_config import env_flag, env_str
from agents.core.mcp.client import stdio_env_baseline
from agents.core.security.rag_guard import MemorySnippet, wrap_memory
from agents.core.tool_rpc import ToolRPCValidationError

_MCP_TOOLS = {
    "search_memory_and_connections": ("question",),
}
_COPILOT_PROCESS: subprocess.Popen | None = None
_MAX_QUERY = 512
_MAX_RESULT = 6000
SECOND_BRAIN_TOOLS = frozenset({"search_second_brain", "search_private_memory", "search_ai_knowledge"})
_TOOL_LOCAL_BACKEND: ContextVar[bool] = ContextVar("second_brain_tool_local_backend", default=False)
_LOCAL_PROJECT_VIEW: ContextVar[bool] = ContextVar("second_brain_local_project_view", default=False)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _local(allowed: Callable[[], bool]) -> bool:
    try:
        return allowed() is True
    except Exception:
        return False


@contextmanager
def local_project_view(allowed: bool):
    """Request-owned direct-loopback allowance for compact project metadata only."""
    token = _LOCAL_PROJECT_VIEW.set(allowed is True)
    try:
        yield
    finally:
        _LOCAL_PROJECT_VIEW.reset(token)


def local_project_view_allowed() -> bool:
    return _LOCAL_PROJECT_VIEW.get()


def strict_loopback_backend(agent_id: str, backend: object, route: str = "") -> bool:
    """A real LM Studio/Ollama loopback route for an in-code local-only agent."""
    from agents.core.llm.base import LMStudioBackend, OllamaBackend
    from agents.core.llm.hybrid_router import LOCAL_ONLY_AGENTS

    if agent_id not in LOCAL_ONLY_AGENTS or type(backend) not in (LMStudioBackend, OllamaBackend):
        return False
    if route and not route.startswith("local"):
        return False
    try:
        parsed = urllib.parse.urlsplit(str(getattr(backend, "base_url", "")))
        return (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and parsed.port is not None and not parsed.username and not parsed.password)
    except ValueError:
        return False


def tool_backend_local() -> bool:
    from agents.core.llm.physical_local import physical_local_required

    return _TOOL_LOCAL_BACKEND.get() and physical_local_required()


def private_context_active() -> bool:
    from agents.core.memory import turn_tools

    return turn_tools.private()


def _private_read_begin(tool: str, local_only: Callable[[], bool]) -> bool:
    from agents.core import trajectory
    from agents.core.memory import turn_tools

    if not _local(local_only) or not turn_tools.mark_private():
        return False
    trajectory.suppress_current()
    turn_tools.note({"event": "tool_result", "tool": tool})
    return True


def bind_tool_backend(agent_id: str, backend: object, route: str = ""):
    return _TOOL_LOCAL_BACKEND.set(strict_loopback_backend(agent_id, backend, route))


def reset_tool_backend(token) -> None:
    _TOOL_LOCAL_BACKEND.reset(token)


def _child_env() -> dict[str, str]:
    # The fixed local scripts need process plumbing, never hub provider credentials.
    result = stdio_env_baseline(include_extra=False)
    result["PYTHONIOENCODING"] = "utf-8"
    token = env_str("NERVA_MEMORY_COPILOT_TOKEN").strip()
    if token:
        result["COPILOT_AUTH_TOKEN"] = token
    return result


def _mcp_script() -> Path | None:
    raw = env_str("NERVA_SECOND_BRAIN_MCP_SCRIPT").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    return path if path.name == "memory_mcp_server.py" and path.is_file() else None


def _python() -> Path | None:
    raw = env_str("NERVA_SECOND_BRAIN_PYTHON").strip()
    path = Path(raw).expanduser().resolve() if raw else Path(sys.executable)
    return path if path.is_file() else None


def _copilot_script() -> Path | None:
    raw = env_str("NERVA_MEMORY_COPILOT_SCRIPT").strip()
    mcp = _mcp_script()
    path = Path(raw).expanduser().resolve() if raw else mcp.with_name("memory_copilot_server.py") if mcp else None
    return path if path and path.name == "memory_copilot_server.py" and path.is_file() else None


def _copilot_url() -> str | None:
    raw = env_str("NERVA_MEMORY_COPILOT_URL").strip()
    if not raw:
        return None
    parsed = urllib.parse.urlsplit(raw)
    try:
        valid_port = parsed.port is not None
    except ValueError:
        return None
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or not valid_port or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        return None
    return f"http://{parsed.hostname}:{parsed.port}"


def _request(path: str, payload: dict | None = None) -> dict | None:
    base = _copilot_url()
    if base is None:
        return None
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    token = env_str("NERVA_MEMORY_COPILOT_TOKEN").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=body, headers=headers, method="POST" if body else "GET")
    try:
        # Refuse redirects: the loopback origin is an authority boundary.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(req, timeout=0.5) as response:
            data = response.read(_MAX_RESULT + 1)
        if len(data) > _MAX_RESULT:
            return None
        value = json.loads(data)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def health() -> dict[str, bool]:
    """Configuration and live loopback status, without paths or record contents."""
    answer = _request("/api/health")
    expected = env_str("NERVA_MEMORY_COPILOT_SERVICE").strip()
    token = env_str("NERVA_MEMORY_COPILOT_TOKEN").strip()
    connected = bool(answer and answer.get("ok") is True and answer.get("hardened") is True
                     and type(answer.get("service")) is str and answer["service"]
                     and (not expected or answer["service"] == expected)
                     and (not token or answer.get("auth_enforced") is True))
    return {
        "mcp_configured": _mcp_script() is not None,
        "connected": connected,
        "vault_fts_configured": bool(env_str("NERVA_VAULT_FTS_DB").strip()),
        "ai_kb_fts_configured": bool(env_str("NERVA_AI_KB_FTS_DB").strip()),
    }


def start_memory_copilot() -> bool:
    """Autostart only the named sibling script, using this Python and fixed argv."""
    global _COPILOT_PROCESS
    if not env_flag("NERVA_AUTOSTART_MEMORY_COPILOT"):
        return False
    if _copilot_url() not in {"http://127.0.0.1:8765", "http://localhost:8765"}:
        return False
    if health()["connected"]:
        return True
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.3):
            return False
    except OSError:
        pass
    sibling = _copilot_script()
    python = _python()
    if sibling is None or python is None:
        return False
    if _COPILOT_PROCESS is not None and _COPILOT_PROCESS.poll() is None:
        return True
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        # Fixed owner-configured local script and interpreter argv; never a shell.
        _COPILOT_PROCESS = subprocess.Popen(  # nosec B603
            [str(python), str(sibling)], cwd=str(sibling.parent), env=_child_env(),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        for _ in range(20):
            if _COPILOT_PROCESS.poll() is not None:
                return False
            if health()["connected"]:
                return True
            time.sleep(0.1)
        _COPILOT_PROCESS.terminate()
        return False
    except OSError:
        return False


def call_mcp(name: str, arguments: dict, *, local_only: Callable[[], bool]) -> dict:
    """One bounded JSON-RPC call to the fixed stdio script; no result logging."""
    if not _local(local_only):
        return {"ok": False, "reason": "strict_local_required"}
    script = _mcp_script()
    python = _python()
    if script is None or python is None or name not in _MCP_TOOLS or not isinstance(arguments, dict):
        return {"ok": False, "reason": "source_unavailable"}
    keys = _MCP_TOOLS[name]
    if any(type(arguments.get(key)) is not str or not arguments[key].strip()
           or len(arguments[key]) > _MAX_QUERY for key in keys):
        return {"ok": False, "reason": "bad_args"}
    allowed = set(keys)
    if set(arguments) - allowed:
        return {"ok": False, "reason": "bad_args"}
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        # Fixed owner-configured local MCP script and interpreter argv; never a shell.
        result = subprocess.run(  # nosec B603
            [str(python), str(script)], cwd=str(script.parent), env=_child_env(),
            input=json.dumps(init) + "\n" + json.dumps(call, ensure_ascii=False) + "\n",
            text=True, encoding="utf-8", capture_output=True, timeout=12, creationflags=flags,
        )
        if result.returncode or len(result.stdout) > 1_000_000:
            return {"ok": False, "reason": "source_failed"}
        for line in result.stdout.splitlines():
            answer = json.loads(line)
            if answer.get("id") == 2:
                value = answer.get("result") or {}
                if value.get("isError"):
                    return {"ok": False, "reason": "source_failed"}
                content = value.get("content") or []
                text = content[0].get("text") if content and isinstance(content[0], dict) else None
                if type(text) is str:
                    return {"ok": True, "source": "local_memory_mcp", "text": text[:_MAX_RESULT]}
        return {"ok": False, "reason": "source_failed"}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"ok": False, "reason": "source_failed"}


def search_fts(query: str, *, source: str, local_only: Callable[[], bool], limit: int = 5) -> dict:
    """Read known FTS5 schemas through SQLite's read-only URI."""
    if not _local(local_only):
        return {"ok": False, "reason": "strict_local_required"}
    if source == "vault":
        return {"ok": False, "reason": "unverified_source"}
    if type(query) is not str or not query.strip() or len(query) > _MAX_QUERY or source != "ai_kb":
        return {"ok": False, "reason": "bad_args"}
    raw = env_str("NERVA_AI_KB_FTS_DB").strip()
    path = Path(raw).expanduser().resolve() if raw else None
    if path is None or not path.is_file():
        return {"ok": False, "reason": "source_unavailable"}
    terms = re.findall(r"\w{3,}", query.casefold(), re.UNICODE)[:6]
    if not terms:
        return {"ok": True, "source": source, "hits": []}
    expression = " OR ".join('"' + term.replace('"', '""') + '"*' for term in terms)
    sql = ("SELECT d.source, d.title, d.content FROM kb_docs_fts "
           "JOIN kb_docs d ON d.doc_id = kb_docs_fts.rowid "
           "WHERE kb_docs_fts MATCH ? ORDER BY bm25(kb_docs_fts) LIMIT ?")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
            rows = conn.execute(sql, (expression, max(1, min(limit, 5)))).fetchall()
        return {"ok": True, "source": source,
                "hits": [{"path": str(row[0])[:200], "section": str(row[1])[:100],
                          "text": str(row[2])[:600]} for row in rows]}
    except (sqlite3.Error, OSError, ValueError):
        return {"ok": False, "reason": "source_failed"}


def search_vault(query: str, *, local_only: Callable[[], bool], limit: int = 4) -> dict:
    """Use the hub OS indexer and its validated vault configuration."""
    if not _local(local_only):
        return {"ok": False, "reason": "strict_local_required"}
    if type(query) is not str or not query.strip() or len(query) > _MAX_QUERY:
        return {"ok": False, "reason": "bad_args"}
    try:
        from agents.core.routers import jarvis_os

        engine = jarvis_os._engine()
        if engine is None:
            return {"ok": False, "reason": "source_unavailable"}
        cfg = jarvis_os._config(engine)
        if not jarvis_os._vault_available(cfg):
            return {"ok": False, "reason": "source_unavailable"}
        _, nodes = engine.retrieve_vault_context(query, cfg, max(1, min(limit, 4)))
        return {"ok": True, "source": "vault", "hits": [
            {"path": str(node.get("relPath") or "")[:200],
             "title": str(node.get("title") or "")[:120],
             "text": str(node.get("excerpt") or "")[:600]}
            for node in nodes if isinstance(node, dict)]}
    except (OSError, ValueError, KeyError):
        return {"ok": False, "reason": "source_failed"}


def recall_context(query: str, *, local_only: Callable[[], bool]) -> str:
    """Bounded fenced memory block for both /chat paths; never persist the block."""
    if not _local(local_only):
        return ""
    results = search_vault(query, local_only=local_only)
    snippets = [MemorySnippet(text=hit["text"], source=str(hit.get("path") or "vault"))
                for hit in results.get("hits", []) if hit.get("text")]
    return wrap_memory(snippets, label="Second Brain").block if snippets else ""


def project_reply(query: str) -> str | None:
    """Answer narrow register/map questions from validated public metadata only."""
    if type(query) is not str or len(query) > _MAX_QUERY:
        return None
    low = query.casefold()
    deadline_queue = re.search(r"\b(?:termene(?:le)?|scadențe(?:le)?|scadente(?:le)?|deadlines)\b", low)
    deadline_request = re.search(
        r"\b(?:am|avem|urmeaz\w*|apropiat\w*|viitoare|14 zile|vault|registru|my|our|upcoming|next)\b",
        low,
    )
    decision_queue = re.search(r"\b(?:decizii(?:le)?|decisions)\b", low)
    decision_request = re.search(
        r"\b(?:am|avem|luate|recente|vault|registru|hart[ăa]|map|my|our|recent)\b", low,
    )
    if deadline_queue and (deadline_request or low.strip(" ?!.") in {"termene", "termenele", "deadlines"}):
        kind = "deadlines"
    elif (re.search(r"\b(?:proiecte(?:le)?|projects)\b", low)
          and re.search(r"\b(?:termin\w*|finaliz\w*|priorit\w*|acum|finish\w*|complet\w*|now|next)\b", low)
          and re.search(r"\b(?:ce|care|am|avem|my|our|what|which|acum|now|vault|registru)\b", low)):
        kind = "projects"
    elif low.strip(" ?!.") in {"azi", "today"} or (re.search(r"\b(?:azi|today)\b", low)
          and re.search(r"\b(?:plan\w*|agend\w*|ce am|what|task\w*|hart\w*|map)\b", low)):
        kind = "azi"
    elif decision_queue and (decision_request or low.strip(" ?!.") in {"decizii", "deciziile", "decisions"}):
        kind = "decisions"
    elif (re.search(r"\b(?:vault\w*|secon\w* brain|harta|map)\b", low)
          and re.search(r"\b(?:organi\w*|structur\w*|arhitectur\w*|navig\w*|zone\w*|hub\w*)\b", low)):
        kind = "architecture"
    else:
        return None
    try:
        from agents.core.routers import jarvis_os

        engine = jarvis_os._engine()
        if engine is None:
            return None
        cfg = jarvis_os._config(engine)
        if not jarvis_os._vault_available(cfg):
            return None
        if kind in {"projects", "deadlines"} and not cfg.get("projectIndex"):
            return None
        if kind in {"azi", "decisions", "architecture"} and not cfg.get("vaultMapPath"):
            return None
        local_metadata = local_project_view_allowed() and kind in {"projects", "deadlines"}
        if local_metadata:
            cfg = {**cfg, "localProjectMetadata": True}
        rows = (engine.project_priorities(cfg, query, limit=4) if kind == "projects"
                else engine.structured_brief(cfg, kind, limit=5))
        if not isinstance(rows, list):
            raise ValueError("invalid result")
        lines = []
        for row in rows[:5]:
            if not isinstance(row, dict) or type(row.get("title")) is not str:
                continue
            title = row["title"].strip()[:120]
            if not title:
                continue
            next_step = str(row.get("nextStep") or "").strip()[:180]
            due = str(row.get("dueDate") or "").strip()[:10]
            due_text = str(row.get("dueText") or "").strip()[:160]
            identifier = str(row.get("id") or "").strip()[:40] if local_metadata else ""
            stage = str(row.get("stage") or "").strip()[:80] if local_metadata else ""
            lines.append("- " + (identifier + " · " if identifier else "")
                         + (due + " · " if due else "") + title
                         + (" (" + stage + ")" if stage else "")
                         + (": " + (next_step or due_text) if next_step or due_text else ""))
        if not lines:
            return ("Nu am găsit intrări publice verificate în registrul local."
                    if re.search(r"[ăâîșț]|\b(?:ce|azi|proiect|termene|decizii)\b", low)
                    else "I found no verified public entries in the local register.")
        intro = ({"projects": "Proiectele de terminat acum, conform registrului local:",
                  "deadlines": "Termenele apropiate din registrul local:",
                  "azi": "Pagina Azi din harta locală:",
                  "decisions": "Deciziile din harta locală:",
                  "architecture": "Zonele publice din harta vaultului:"}[kind]
                 if re.search(r"[ăâîșț]|\b(?:ce|azi|proiect|termene|decizii)\b", low)
                 else {"projects": "Projects to finish now, from the local register:",
                       "deadlines": "Upcoming deadlines in the local register:",
                       "azi": "Today's page in the local map:",
                       "decisions": "Decisions in the local map:",
                       "architecture": "Public zones in the vault map:"}[kind])
        return intro + "\n" + "\n".join(lines)
    except (OSError, ValueError, AttributeError):
        return ("Nu pot verifica acum prioritățile proiectelor din registrul local."
                if "proiect" in low else "I can't verify project priorities from the local register now.")


def register_second_brain_tools(server, *, local_only: Callable[[], bool],
                                visible: Callable[[], bool] | None = None) -> tuple[str, ...]:
    """Fixed read-only tools, invisible and refused outside strict-local turns."""
    def _preflight(args: dict) -> dict:
        query = args.get("query")
        if type(query) is not str or not query.strip() or len(query) > _MAX_QUERY:
            raise ToolRPCValidationError("bad_args")
        return {"query": query.strip()}

    async def _vault(args: dict) -> dict:
        if not _private_read_begin("search_second_brain", local_only):
            return {"ok": False, "reason": "strict_local_required"}
        return await asyncio.to_thread(search_vault, args["query"], local_only=local_only)

    async def _mcp(args: dict) -> dict:
        if not _private_read_begin("search_private_memory", local_only):
            return {"ok": False, "reason": "strict_local_required"}
        return await asyncio.to_thread(call_mcp, "search_memory_and_connections",
                                       {"question": args["query"]}, local_only=local_only)

    async def _fts(args: dict) -> dict:
        if not _private_read_begin("search_ai_knowledge", local_only):
            return {"ok": False, "reason": "strict_local_required"}
        return await asyncio.to_thread(search_fts, args["query"], source="ai_kb", local_only=local_only)

    names = ("search_second_brain", "search_private_memory", "search_ai_knowledge")
    schema = {"type": "object", "properties": {"query": {"type": "string"}},
              "required": ["query"], "additionalProperties": False}
    for name, handler in zip(names, (_vault, _mcp, _fts), strict=True):
        server.register_tool(name, handler, gated=False, description="Search configured local read-only memory.",
                             input_schema=schema, capability_id=f"tool:{name}", preflight=_preflight,
                             visible=visible or (lambda: _local(local_only)),
                             risk="read_only", untrusted_output=True,
                             max_result_bytes=8192)
    return names
