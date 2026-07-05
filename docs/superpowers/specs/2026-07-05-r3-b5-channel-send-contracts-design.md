# R3-B5 Channel-Send Contracts Design

## Goal

Add a reusable automation-contract gate to the generic `ChannelManager.send()` boundary before any registered channel adapter sends a message.

## Non-Goals

- Do not change inbound pairing, inbox storage, or reply drafting.
- Do not add new channels or widen the existing send surface.
- Do not replace the existing channel-reply approval queue.
- Do not route escalation sends through `ChannelManager`; R3-B3 already gates escalation fan-out directly.

## Current Seam

`ChannelManager.send(channel, response, **kwargs)` is the shared outbound transport used by orchestrator replies and approved channel replies. It currently verifies that the channel is registered and then calls the adapter for `telegram`, `web`, or `voice`.

The remaining gap is that this generic transport boundary does not evaluate the reusable automation-contract fabric before adapter I/O. Caller-level gates exist for channel replies and escalation, but the manager itself should still have a last-mile shape gate.

## Approach

Add `CHANNEL_SEND_CONTRACT` in `agents/core/channels/manager.py`. Evaluate it after a registered adapter is found and before dispatching to the adapter.

The contract payload is shape-only:

- kind: `channel.send`
- channel id
- message length
- sorted keyword argument keys
- keyword argument count

Do not include raw message text, chat IDs, client IDs, tokens, email addresses, phone numbers, or other keyword values.

Denied or failed contract evaluation returns `False` and never calls the adapter, matching the existing manager convention for failed sends.

## Risk

The main risk is blocking legitimate local replies by making the default contract too strict. The default template therefore validates only supported channel shape, message length as a non-negative integer, and safe keyword key names. It does not inspect values or require approval.

## Verification

- Red/green tests proving a patched contract denial prevents adapter calls.
- Red/green tests proving admissible evaluation receives a shape-only payload.
- Adjacent Safe Comms, send-rate-limit, cross-channel, and escalation suites.
