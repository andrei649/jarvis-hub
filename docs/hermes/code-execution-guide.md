# Programmatic tool calling in Nerva

Use `execute_code` for three or more tool calls with filtering, branching or loops
between them. Only printed output returns to the model; intermediate responses
stay in the isolated worker. The owner enables `llm.execute_code`; a composed,
pinned isolated backend uses persistent session kernels by default. An explicit
`llm.execute_code_sessions=false` chooses a fresh interpreter per call.

Import functions using the actual offered tool names:

```python
from jarvis_tools import file_read
response = file_read("notes.txt")
if response["ok"]:
    print(response["result"]["content"])
else:
    print(response["reason"])
```

Signatures come from the live tool schema: required arguments first, then optional
arguments. Positional and keyword arguments work; omitted optional arguments stay
omitted. The functions return the same `{ok, result}` or refusal envelope as
`jarvis_tool_call(name, arguments)`. Imports include only public Python identifiers
offered to this invocation. Dotted/other names remain available through the raw
call. `execute_code` itself is excluded. A missing import means the tool is not
offered, not permission to try a different actor. An old saved function cannot
keep access after its tool is withdrawn.

The file RPC reaches the existing host broker and dispatcher. Writes, terminal
commands and other gated effects return `approval_required` with the task id;
they do not run inline. Approval and later worker execution are separate. Imported
functions do not widen the offered set, bypass the kernel or alter call/output
limits. Each resident cell earns one GRANT and revalidates it after the interpreter
lock; a denied reset preserves existing variables. Timeout/cancellation uses the
backend's teardown, and one-shot cancellation awaits that teardown before deleting
its mailbox. Python exceptions return stderr; cancellation propagates to the caller.

## Examples

Read matching project files through the governed file roots:

```python
from jarvis_tools import file_search, file_read
matches = file_search("database", glob="*.yaml")["result"]["matches"]
configs = []
for match in matches:
    response = file_read(match["path"])
    if response["ok"]:
        configs.append({"path": match["path"], "content": response["result"]["content"]})
print(configs)
```

Combine research without returning every page to the model:

```python
from jarvis_tools import web_search, web_extract
response = web_search("Python features", max_results=3)
pages = []
if response["ok"]:
    for hit in response["result"].get("results", []):
        page = web_extract(hit["url"], max_chars=2000)
        if page["ok"]:
            pages.append({"url": hit["url"], "page": page["result"]})
print(pages)
```

Propose file replacements, preserving the approval boundary:

```python
from jarvis_tools import file_search, file_read, file_write
proposals = []
for match in file_search("old_api_call(", glob="*.py")["result"]["matches"]:
    read = file_read(match["path"])
    if read["ok"] and "next_offset" not in read["result"]:
        content = read["result"]["content"].replace("old_api_call(", "new_api_call(")
        proposals.append(file_write(match["path"], content))
print(proposals)  # Pending proposals, not a claim that files were changed.
```

Build/test commands belong on the terminal tool; a script can propose a command
and inspect its returned approval id. Choose an owner-configured target from the
tool's advertised schema, then use `terminal_run(target=..., command=...)`.
Run and inspect its output through the existing approved task workflow.

## Choosing tools and understanding limits

| Work | Tool |
|---|---|
| Multi-step tool calls, large-output filtering, loops over results | execute_code |
| Shell commands, builds/test suites, interactive/background processes | terminal |
| Credentials for arbitrary SDK code | Exact owner-vouched skill/config passthrough; managed provider credentials stay in governed provider tools |

Code is capped at32,768 characters; generated imports do not reduce that allowance.
The host enforces the configured sandbox/cell timeout and tool-call cap (default50).
Each returned stream has byte and line bounds with explicit truncation. A composed
result store may retain redirected overflow for `file_read` paging; runaway/native
descriptor output has separate limits. These are not unlimited capture promises.
Children receive a minimal scrubbed environment; resident production containers
do not inherit the host environment. Provider secrets remain with host-side tools.

Docker/file RPC avoids dependence on AF_UNIX: the same client works on host systems
with a usable isolated backend and Python inside it. Linux/macOS/Windows environment
handling has separate tests; this checkpoint is locally tested on macOS, not a new
live Windows/Docker/remote acceptance run. Remote backend breadth belongs to H660.

## H595 contract map — all12 frozen entries

Reference: `docs/research/hermes-inventory-v2026.8.31/35-docs-features.md`,
code-execution page. This map preserves the full contract and its actual gaps.

| Entry | Nerva evidence or remaining work |
|---|---|
|1 execute_code programmatic tools | Existing broker/file RPC plus imported live-schema functions; tested at registered model entry and real worker |
|2 When to use it | Selection guidance above; no added acceptance gate |
|3 Four practical examples | File pipeline, research, governed refactoring and terminal build/test guidance above; live providers not claimed |
|4 project versus strict cwd/interpreter | Resident and one-shot workers resolve backend-local Python and cwd; owner-configured projects use a bounded read-only projection. Strict uses backend staging/default Python. Registered-model tests cover resident, one-shot and safe startup fallback |
|5 Resource limits | Existing host/worker caps; original code-length boundary retained with imports |
|6 RPC mechanics | Existing dispatcher/broker and file transport; imported helpers retain approvals and caps |
|7 Error handling/interruption | Tracebacks/refusals preserved. Admitted same-session HTTP/channel messages interrupt active code before waiting for the turn lease; the tool awaits teardown and reports the donor interruption marker. Registered-model tests cover one-shot and resident namespace loss. Responsive HUD typed follow-ups reach the existing SSE route; each reply and Stop cancellation retain their stream ownership |
|8 Environment scrubbing | Existing minimal child env and host-side credentials; isolated mode never uses host fallback |
|9 Skill environment passthrough | Successful owner-vouched main skill views declare names for the exact actor/principal/session. Resident and one-shot startup freeze approved values; trust/catalog/config changes revoke the namespace or refuse pending startup |
|10 Operational-prefix hardening/workaround | Exact operational names plus explicit owner skill/config allowances; managed credentials and loader/control variables remain blocked. Values travel over startup stdin, never argv |
|11 execute_code versus terminal | Decision table above |
|12 Platform support | File-RPC adaptation; local and backend-specific evidence remain distinguished |

H595 is equivalent for these twelve frozen entries after registered-tool, real
local-worker, interruption and responsive-HUD verification. This verdict does not
claim fresh live Docker/Windows/Linux acceptance. SSH/Modal provisioning, native-fd
capture and automatic approved RPC resume remain separate H660 work.

## Project and environment configuration

The owner may set `llm.execute_code_project_root` to an explicit project directory
and `llm.execute_code_mode` to `project` (default) or `strict`. A project
worker imports local modules and reads relative data from a snapshot mounted
read-only separately from its writable RPC mailbox. Secret paths, links, generated
dependencies and text changed by the secret broker are excluded. The snapshot is
limited to2000 files/50MB; exceeding a limit refuses startup. Restart/reset refreshes
it. Actual project writes continue through approved file tools.

`llm.execute_code_env_passthrough` is a list of exact third-party variable names.
The same allowance may come from `required_environment_variables` after a successful
owner-vouched `skill_view`. Allowances never cross actors, principals or sessions;
reload, trust revocation, expiry and config/value changes prevent reuse of the old
interpreter. `VIRTUAL_ENV`/`CONDA_PREFIX` are trusted interpreter hints, separate
from skill allowances: the candidate must exist and pass a Python3.8+ probe inside
the backend. An unavailable host virtual environment cannot select a Docker Python.

One-shot Docker execution and safe resident-startup fallback preserve this context.
Each run has a private project snapshot outside the shared staging mount, mounted
read-only at `/project`; environment and code travel only through startup stdin.
Authority is checked before preparing the snapshot and again before sending values.
Contextual execution on unsupported WASM or a production host fallback returns
`context_backend_unsupported`. Timeout includes startup transmission; cancellation
stops the backend before removing its snapshot and mailbox. Local-worker tests
simulate the isolation boundary; Docker transport checks are distinct from live
containment.

## New-message interruption and results

An admitted new message in the same conversation interrupts its active code
children. The previous model turn receives `status=interrupted` and
`[execution interrupted — user sent a new message]`, captured stdout/stderr,
completed tool-call count and elapsed duration; it can finish before the queued
turn starts. Resident interruption discards the old namespace. Background jobs,
other conversations, rejected or observation-only traffic and intercepted pending
replies do not send this signal. Request disconnect cancellation still propagates.

HTTP `/chat` and `/chat/stream` signal before their turn lease. Telegram signals
before batching/chat lanes after group/pending gates and a current pairing/rate
probe; that probe does not reserve a rate slot, so later dispatch can differ if
admission state changes. Other channel gateway messages signal only after live
admission and pending interception.

Executed results also expose `status` (`success`, `error`, `timeout`, `interrupted`),
`output`, `tool_calls_made` and `duration_seconds`, alongside existing Nerva fields.
Timeout classification uses backend state, not text printed by a script.
Captured interrupted content respects stream limits and remains untrusted. The
fixed interruption notice is protocol overhead when an unusually small configured
limit is shorter than the notice itself. Incomplete spill files are discarded.

Verification is recorded in `docs/hermes/evidence/2026-10-05-code-interruption/`.
The local workers and ingress are tested; fresh Docker/platform acceptance remains
separate. H660 remote provisioning and automatic approved resume remain open.
