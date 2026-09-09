# Hermes absorption: live Slack event ingress

Generated: 2026-09-09. Goal: connect configured Slack Socket Mode events to the
existing paired, persistent, governed inbox path. Base/head before changes:
`c51f57df5f3fa60406a03155c88a2e618bbdb175`. Lease: none. Dependency: merged #1060.

The current adapter can receive a manually supplied event but does not subscribe
to Slack. Add an optional `SLACK_APP_TOKEN` connection using the Slack SDK's
built-in Socket Mode client. Acknowledge envelopes promptly, admit bounded new
human messages only, deduplicate replayed event IDs, and hand them to
`receive_event` on the hub event loop. Carry only validated sender, room and
thread identity. Pairing and `channel.reply` remain responsible for permission
and delivery; receiving an event must never send a response directly.

Non-goals: live token edits, public webhook routes, slash-command callbacks,
attachments, SDK installation, account provisioning or sending real messages.
Existing bot-token-only deployments retain their manually supplied event seam.
Connection, dispatch and shutdown must not block the hub; queues and replay
memory must be bounded. Failure must be visible without logging credentials or
message contents. Stop must close the connection and cancel pending work.

Paths: `agents/core/channels/slack.py`, `agents/web.py`, focused channel tests,
`.env.example`, absorption/architecture/owner setup and parity documentation.
Tests: regression-first fake-SDK envelope/lifecycle cases; existing workspace
reply, channel gateway, session, render and lifespan checks. A real Slack
connection remains unverified without the optional SDK and owner credentials.
Rollback: revert this PR or remove `SLACK_APP_TOKEN`; no data migration.
Next action: implement and exercise Socket Mode ingress through the existing
gateway, then independently review and publish a PR after focused checks pass.

Review refinements before publication: bind received events to the bot workspace
and bot identity returned by `auth.test`, rather than discarding workspace identity
at pairing. Add the both-token condition to `agents/core/boot_guards.py` so disabling
pairing cannot silently expose this newly live channel. Regression-first guard
test failed as expected before the table was extended; manual ingress stays
unchanged. Additional paths: `tests/test_default_deny_front_door.py`. Connection
readiness and repeated cancellation must be checked against actual SDK semantics.

Protocol reference: https://docs.slack.dev/tools/python-slack-sdk/socket-mode/

## Verification before publication

Independent review found and fixed workspace identity loss, false readiness on
failed handshakes, repeated-cancellation cleanup and the SDK's unlimited
rate-limit discovery retry. Socket pairing is now `TEAM_ID:USER_ID`; prior bare
pairings do not migrate implicitly. Startup verifies the bot workspace and the
guard covers the new inbound channel. SDK discovery uses one timed HTTP attempt;
normal reconnect behavior stays in the SDK. No security boundary was weakened.

The implementation agent ran 124 channel, pairing/inbox and route/OpenAPI tests;
the reviewer independently ran 94 Slack/front-door tests. The parent added an
optional real-SDK offline test and ran the complete Slack/front-door set with
`slack-sdk` 3.44.1: 95 passed. The real SDK parser, callback, ACK response and
thread cleanup ran; authentication, connection and network send were mocked.
The optional SDK was placed in a temporary test directory, not installed in the
hub's environment. Ruff and diff checks passed. Local Python is 3.11.15; hosted
CI uses the repository's Python 3.12 lane.

Real workspace authentication/subscriptions/delivery remain unverified. The
queue/cache bounds cover Nerva's bridge, not every internal SDK buffer. No user
message was sent to an external service during this work.

Integrated locally onto `a31b369ab83e167321448ee68e6fa3e99b65e03f` after #1061
merged. Final targeted run also exercised existing workspace replies, Slack/Discord
rendering, sessions, inbox, pairing, route/OpenAPI parity and real app startup/
shutdown, with optional channel credentials blank and dotenv loading disabled in
the test process. Exit 0; one existing Starlette deprecation warning. Generated
backend collection count: 9479; frontend/mobile counts reused because their code
is unchanged. No full local backend-suite pass is claimed.
