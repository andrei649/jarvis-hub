# Check a professional tool through Nerva

Open a disposable project in the real application. Give a layer, node or object a unique synthetic name of at least 16 characters. Confirm the name in the app. Select a read-only MCP tool that reads the current object or its hierarchy. Keep the expected name out of the tool arguments, paths and bridge configuration.

Save the connection details in a private JSON file. For an already installed Godot Universal MCP bridge, this example starts the bridge in the project's directory and asks Godot for its open scene tree. Replace both executable paths and the project path. Enable the matching editor add-on in that disposable project. The separate bridge is optional and needs owner approval before installation. [Godot bridge and license](https://github.com/Noa3/GodotMCP/tree/d2e541c0c23dd350c37297ef962a43aaf256c33a)

```json
{
  "command": ["C:/Program Files/nodejs/node.exe", "C:/tools/GodotMCP/dist/cli/index.js"],
  "project": "C:/scratch/godot-smoke",
  "tool": "godot_editor_tree",
  "arguments": {"max_depth": 3}
}
```

For an Adobe bridge, use its installed executable and its layer-inspection tool in the same configuration. The stdio bridge receives a minimal environment. A JSON string value of `{project}` in a command argument or tool argument expands to the project path. Nerva offers only the selected tool and requires the bridge to advertise `readOnlyHint: true`.

For Figma Desktop, use its built-in server if an eligible Dev or Full seat is already available. Open a synthetic design and enable the desktop MCP server in Dev Mode. Select the frame containing the named child. Choose a read-only tool the server advertises that returns the node hierarchy. The test accepts Figma's fixed local endpoint. [Figma Desktop setup](https://developers.figma.com/docs/figma-mcp-server/local-server-installation/)

```json
{
  "transport": "streamable-http",
  "url": "http://127.0.0.1:3845/mcp",
  "project": "C:/scratch/figma-smoke",
  "tool": "get_metadata",
  "arguments": {}
}
```

Run one case from the repository root in a temporary PowerShell session. This example assumes the Godot node has already been named in the editor.

```powershell
$env:NERVA_PRO_SMOKE_GAME_ENGINE = 'C:\scratch\godot-connection.json'
$env:NERVA_PRO_SMOKE_GAME_ENGINE_MARKER = 'NervaSyntheticNode94172'
python -m pytest "tests/test_finish_line_professional_tools.py::test_professional_tool_reads_current_object[game_engine]" -q
```

Use `ADOBE` and `[adobe]`, or `FIGMA` and `[figma]`, for the other integrations. The probe passes when Nerva's own MCP manager connects, exposes the named read-only tool and receives the expected object name from it. An incomplete opt-in fails before connecting. Without a selected bridge, the three app cases skip. The ordinary suite checks the stdio path with a fixture and validates the Figma URL locally.
