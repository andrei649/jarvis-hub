"""Opt-in owner-machine MCP read probes for finish-line item 8."""

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

from agents.core.mcp.client import MCPManager, MCPServer

PROBES = ("adobe", "figma", "game_engine")
FIGMA_DESKTOP_URL = "http://127.0.0.1:3845/mcp"


def _config(kind):
    flag = f"NERVA_PRO_SMOKE_{kind.upper()}"
    marker_flag = f"{flag}_MARKER"
    location, marker = os.environ.get(flag), os.environ.get(marker_flag)
    if not location and not marker:
        pytest.skip(f"{flag} unset: no real {kind} MCP bridge selected")
    assert location and marker, f"{kind}: set both {flag} and {marker_flag}"
    assert len(marker) >= 16, f"{marker_flag}: use a unique marker of at least 16 characters"
    try:
        config = json.loads(Path(location).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        pytest.fail(f"{flag}: cannot read JSON config: {exc}")
    assert isinstance(config, dict), f"{flag}: expected a JSON object"
    transport = config.get("transport", "stdio")
    command, tool, arguments, root = (config.get(key) for key in
                                      ("command", "tool", "arguments", "project"))
    if transport == "streamable-http":
        assert kind == "figma" and config.get("url") == FIGMA_DESKTOP_URL and command is None, (
            f"{flag}: HTTP is allowed only for the fixed Figma desktop MCP URL, without command")
    else:
        assert transport == "stdio" and config.get("url") is None, f"{flag}: unsupported transport"
        assert isinstance(command, list) and command and all(isinstance(x, str) and x for x in command), (
            f"{flag}: command must be an installed local executable and argument list")
        executable = Path(command[0])
        assert executable.is_absolute() and executable.is_file() and executable.suffix.lower() not in {
            ".bat", ".cmd", ".ps1"}, f"{flag}: command[0] must be an existing absolute executable"
        assert executable.stem.lower() not in {"npx", "uvx", "pip", "npm", "pnpm", "yarn"}, (
            f"{flag}: package launchers are forbidden; install the bridge separately")
    assert isinstance(tool, str) and tool and "/" not in tool, f"{flag}: tool must be one MCP tool name"
    assert isinstance(arguments, dict), f"{flag}: arguments must be a JSON object"
    assert isinstance(root, str) and Path(root).is_absolute(), f"{flag}: project needs an absolute path"
    project = Path(root)
    assert project.is_dir() and not project.is_symlink(), f"{flag}: project must be an existing disposable directory"
    assert not _has_marker([command, config.get("url"), arguments, root], marker), (
        f"{marker_flag}: marker must not appear in bridge inputs or project path")
    return transport, command, tool, arguments, project, marker


def _replace_project(value, project):
    if value == "{project}":
        return str(project)
    if isinstance(value, dict):
        return {key: _replace_project(item, project) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_project(item, project) for item in value]
    return value


def _has_marker(value, marker):
    if isinstance(value, str):
        return marker in value
    if isinstance(value, dict):
        value = [*value, *value.values()]
    return isinstance(value, list) and any(_has_marker(part, marker) for part in value)


async def _probe(kind, transport, command, tool, arguments, project, marker, tmp_path, monkeypatch):
    args = _replace_project(arguments, project)
    if command is not None:
        command = [str(project) if value == "{project}" else value for value in command]
    assert not _has_marker([command, args], marker), "marker must stay out of bridge inputs"

    # The actual Nerva env baseline runs against only process plumbing, not owner state.
    state = tmp_path / "state"
    state.mkdir()
    system_root = os.environ.get("SYSTEMROOT", "")
    baseline = {"PATH": os.pathsep.join(filter(None, (str(Path(command[0]).parent) if command else "",
                                                   str(Path(system_root) / "System32") if system_root else ""))),
                "JARVIS_MCP_STDIO_ENV_BASELINE": "1", "HOME": str(state),
                "USERPROFILE": str(state), "APPDATA": str(state), "LOCALAPPDATA": str(state),
                "JARVIS_HOME": str(state), "TMP": str(state), "TEMP": str(state),
                "XDG_CONFIG_HOME": str(state), "XDG_DATA_HOME": str(state),
                "XDG_CACHE_HOME": str(state)}
    if system_root:
        baseline["SYSTEMROOT"] = system_root
    if transport == "streamable-http":
        baseline["JARVIS_MCP_HTTP_CLIENT"] = "1"
    monkeypatch.setattr(os, "environ", baseline)
    server = MCPServer(
        kind, transport=transport, command=shlex.join(command) if command else None,
        url=FIGMA_DESKTOP_URL if transport == "streamable-http" else None,
        cwd=str(project), trust="read-only",
        tools_allow=[tool], options={"connect_timeout": 10, "timeout": 10},
    )
    if transport == "stdio":
        assert all(marker not in value for value in server._merged_env().values()), (
            "expected marker must not reach the MCP subprocess environment")
    manager = MCPManager()
    manager.register(server)
    try:
        assert await manager.connect_server(kind), (
            f"{kind}: MCP handshake failed ({server.last_error}); check the installed bridge command")
        rows = [row for row in manager.model_tools() if row["server"] == kind and row["tool"] == tool]
        assert len(rows) == 1, f"{kind}: {tool} was not offered under Nerva's read-only policy"
        assert rows[0]["gated"] is False, f"{kind}: {tool} needs a readOnlyHint for this probe"
        result = await manager.call_tool(rows[0]["name"], args)
        if not isinstance(result, dict) or result.get("isError") or "error" in result:
            pytest.fail(f"{kind}: MCP tool call failed; check bridge logs and project focus", pytrace=False)
        texts = [block.get("text", "") for block in result.get("content", [])
                 if isinstance(block, dict) and block.get("type") == "text"]
        if not _has_marker([texts, result.get("structuredContent")], marker):
            pytest.fail(f"{kind}: {tool} did not return the selected live object marker", pytrace=False)
    finally:
        await manager.close_all()


@pytest.mark.parametrize("kind", PROBES)
async def test_professional_tool_reads_current_object(kind, tmp_path, monkeypatch):
    await _probe(kind, *_config(kind), tmp_path, monkeypatch)


async def test_loopback_harness_only(tmp_path, monkeypatch):
    project = tmp_path / "nerva-pro-smoke-loopback"
    project.mkdir()
    marker = 'Nerva fixture – "șir sintetic"'
    (project / "marker.txt").write_text(marker, encoding="utf-8")
    fixture = Path(__file__).resolve().parent / "fixtures" / "mcp_fake_server.py"
    await _probe("loopback", "stdio", [sys.executable, str(fixture), "project-marker"],
                 "read_project_marker", {}, project, marker, tmp_path, monkeypatch)


def test_figma_desktop_config_allows_only_fixed_loopback(tmp_path, monkeypatch):
    project = tmp_path / "disposable-figma-project"
    project.mkdir()
    config_path = tmp_path / "figma.json"
    config = {"transport": "streamable-http", "url": FIGMA_DESKTOP_URL,
              "project": str(project), "tool": "get_editor_tree", "arguments": {}}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("NERVA_PRO_SMOKE_FIGMA", str(config_path))
    monkeypatch.setenv("NERVA_PRO_SMOKE_FIGMA_MARKER", "synthetic-figma-object-1234")
    assert _config("figma")[:2] == ("streamable-http", None)
    config["url"] = "http://127.0.0.1:9999/mcp"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(AssertionError, match="fixed Figma desktop MCP URL"):
        _config("figma")
