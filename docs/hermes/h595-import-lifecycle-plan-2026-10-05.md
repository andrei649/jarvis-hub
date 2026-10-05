# H595 — imported tool functions and interruption

All697 goal active. Previous turn made progress: resident defaults, exact cell
GRANT and non-consuming live revalidation verified;129/697 accepted. Preserve
dirty state. No stage, commit, push, merge, deploy or paid provider.

Reference: frozen inventory35-docs-features.md, code-execution page's12 entries;
Hermes59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e/tools/code_execution_tool.py
generate_hermes_tools_module and templates, MIT2025 Nous Research.

Before source changes:
1. Reproduce interruption leaving the one-shot execute task running, including
   cancellation while the host services a tool. Propagate cancellation and await
   existing backend teardown before removing its RPC mailbox. Do not rebuild
   Docker/process teardown or change the host subprocess security contract.
2. Adapt donor per-tool import stubs to Nerva's live offered tool schemas and
   existing jarvis_tool_call. Expose `from jarvis_tools import ...` only for tools
   offered to this invocation. Preserve raw response/refusal behavior, approvals,
   taint and call caps; no new authority/transport. Rebuild imports each resident
   cell; old captured functions still use the current broker/mailbox.
3. Verify one-shot and resident real-worker imports, positional/keyword arguments,
   revoked/offered tool reach, required arguments and canonical length boundary.
   Verify cancellation teardown ordering. Run affected regression once after
   integration, then scoped checks/source hashes and Graft refresh.

Owned source: agents/core/tool_rpc_runtime.py, agents/core/code_tools.py,
agents/core/session_kernels.py, new agents/core/tool_rpc_stubs.py; matching tests,
guide and docs/hermes evidence/status. Reuse existing test-only real Python worker;
label simulated isolation separately from live Docker. No backend provisioning.

H595 cannot yet be equivalent: `project` chooses cwd/interpreter, whereas Nerva
tool profiles choose authority. Those are different functions. Skill-declared
environment passthrough is also not bound to code execution. Retain partial;
explicitly map all12 frozen entries in the acceptance guide, without treating
unrelated H660 remote transport, unlimited/native-fd output or automatic approved
RPC resume as new H595 requirements.

Rollback baseline: /tmp/nerva-h595-import-lifecycle-baseline-20261005. Apply only
this localized diff; preserve all preceding resident/default/pending work.
