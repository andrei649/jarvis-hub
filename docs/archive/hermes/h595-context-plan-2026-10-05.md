# H595 project and environment integration

Goal: all697 Hermes parity, local only. Base/head: a7ffad6676cfb28e7ac374d495b4a5889e5f4646. Generated: 2026-10-05.

1. Reuse donor mode/interpreter resolver and exact-name environment policy in new helpers (two authorized implementers, separate files).
2. Connect successful owner-vouched skill views to exact actor/principal/session declarations with a live trust/catalog validator.
3. Freeze an approved context after the cell grant; send values only through startup stdin. Include an opaque keyed context revision in interpreter identity, revalidate after waiting, and discard previous context interpreters on change.
4. Project mode stages bounded, redacted project files into a separate read-only Docker mount. Strict selects backend staging/default Python. Interpreter probes occur inside the backend; never execute host model code.
5. Verify real resident worker behavior with synthetic project/env data and scope/revocation/reset cases; review Docker transport configuration separately. One-shot context integration remains explicit follow-up until supported; refuse configured context rather than silently ignore it.
6. Run affected checks, save evidence and refresh only reviewed pins from this exact external preimage. No publish or parity credit for helper presence alone.

Ruling: project writes use existing approved file tools; the project projection is read-only. This preserves Nerva isolation while enabling local module/data reads. Active virtual environments must exist inside the execution backend. Project snapshots refresh on interpreter restart/reset.

Owned paths: agents/core/{code_context,code_env,code_tools,session_kernels,detached_kernel,autonomy_coordinator}.py; agents/core/skills/tools.py; focused tests and docs/hermes evidence.
