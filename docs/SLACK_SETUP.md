# Slack inbox setup

Nerva can receive Slack direct messages and explicit mentions through Socket
Mode. Incoming messages enter the existing pairing and inbox flow. Replies
remain proposals in the approval queue; receiving a message does not authorize
a reply or enable live token streaming.

## Configure the Slack app

1. Install the optional `slack-sdk` Python package in the environment running
   Nerva. The built-in Socket Mode client needs no separate WebSocket package.
2. In your Slack app, enable **Socket Mode** and create an app-level token with
   `connections:write`. Keep it in the local `SLACK_APP_TOKEN` setting. Set
   `SLACK_BOT_TOKEN` to the installed app's bot token. Never commit either token.
3. Under **Event Subscriptions**, subscribe to `message.im` and `app_mention`.
   The bot needs `im:history` and `app_mentions:read` for those subscriptions,
   plus `chat:write` for approved replies. Reinstall the app in the workspace
   after changing its scopes. Enable the App Home messages tab if using DMs.
4. Restart the hub. Keep channel pairing enabled (the default). Pair the Slack member through Nerva's existing pairing
   controls before expecting their messages to enter the inbox. Socket Mode identities
   appear as `TEAM_ID:USER_ID`; previous bare-user pairings need fresh approval.

See [Slack's Socket Mode guide](https://docs.slack.dev/tools/python-slack-sdk/socket-mode/)
and the [app mention event](https://docs.slack.dev/reference/events/app_mention/).
No public inbound HTTP endpoint or signing-secret setting is needed for this
Socket Mode connection.

## What to expect

- DMs and explicit app mentions are eligible. Ordinary room chatter, bot
  messages, edits/deletions and unsupported event types are ignored.
- Events must belong to the bot token's authenticated workspace; installations
  in other workspaces cannot reuse a member's pairing. The bot's own messages
  are excluded by its authenticated user ID as well as bot event markers.
- Slack member, room and thread identity come from the event. Pairing remains
  responsible for admitting the member; the transport cannot make them owner.
- SDK callbacks acknowledge receipt promptly, then hand work to a bounded
  queue on the hub event loop. Receipt acknowledgment means accepted by the
  transport, not processed, approved or delivered.
- Repeated event IDs are suppressed while retained in the process's bounded
  replay cache. This is not durable exactly-once processing across restarts.
- Queue saturation or connection failure is reported in the hub log. Messages
  dropped at the capacity limit are not durably queued for later recovery.
- With only `SLACK_BOT_TOKEN`, the existing host `receive_event` integration and
  approved outbound replies remain available; automatic inbox receipt requires
  the app token and a functioning Socket Mode connection.

## Verify on the configured host

Use an owner-controlled workspace and member: check that an unpaired sender is
held, then pair them and verify a DM and mention appear in the correct inbox
thread. An answer should be queued before approval, delivered only after it,
and retain the original thread. Check that the bot's own reply and a replayed
event do not create a second turn. Restart and stop the hub to verify lifecycle.

Automated tests use a fake SDK and the real pairing/inbox components. An additional
optional test exercises the real SDK parser, callback and thread cleanup with
network operations mocked (verified with `slack-sdk` 3.44.1). They do not prove
Slack credentials, workspace scopes, connectivity or live delivery.
Removing `SLACK_APP_TOKEN` disables automatic ingress without a data migration.
