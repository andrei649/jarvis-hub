"""Nerva Workspace — the B2B pilot web application of the hub.

The workspace is a separate product surface: company employees log in with their own
accounts, work inside departments, ask a governed assistant questions answered from
company documents, run reports and request approvals, while admins manage users,
departments, model policy and a tamper-evident audit trail. It never touches the
owner's personal pipeline, memory or agents.

The contract every module here follows is ``docs/business/WORKSPACE_PILOT_SPEC.md``.
This package is deliberately import-light: importing it pulls in nothing, so the CLI
(``nerva-run -m agents.core.workspace``, PILOT_GUIDE §2) and the routers load only what
they use.
"""
