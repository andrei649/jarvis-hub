# Mobile Channel Inbox Design

**Goal:** Close H18.12 by giving the native iOS/Android app the same Safe Comms channel inbox loop the browser HUD has: list live telegram/web threads, read one thread, and queue a governed reply.

**Non-goals:** No new backend endpoints, no direct channel send from mobile, no admin-token requirement for drafting replies, and no email/WhatsApp inbox transport expansion.

## Context

Safe Comms v0 already persists bounded telegram/web inbound threads through `ChannelInboxStore` and queues outbound replies through `ChannelReplyBroker`. The browser HUD can read `/api/channels/inbox*` and draft replies, but `mobile/PARITY.md` still marked the native app as not started for that surface.

The mobile app already has a stateless API client, persisted hub/user/admin token settings, and an Approvals tab over the same approval funnel. The safest native product loop is therefore: mobile drafts the reply with the user token, the server enqueues `channel.reply`, and the owner approves from the existing queue.

## Approach

- Add typed client calls in `mobile/src/api/client.ts`:
  - `fetchChannelInbox()` for `GET /api/channels/inbox`.
  - `fetchChannelThread()` for `GET /api/channels/inbox/{thread_id}` with encoded thread ids.
  - `sendChannelReply()` for `POST /api/channels/inbox/{thread_id}/reply` with `source:"mobile"`.
- Add a `CommsScreen` and bottom-tab entry:
  - Thread list with unread/live metadata.
  - Selected-thread messages with inbound/outbound alignment.
  - Reply composer that queues, never sends directly.
- Update `mobile/PARITY.md`, `mobile/README.md`, `BACKLOG.md`, `STATUS.md`, and `docs/SPRINT.md`.

## Risks

Thread ids contain `:` and must be encoded in mobile URLs. The API test pins this. The screen intentionally does not require `X-Admin-Token`; approval remains a separate existing step.

## Tests

- Red/green mobile API contract test for inbox list, sparse normalization, encoded thread read, and governed reply payload.
- Full mobile Jest suite.
- Mobile TypeScript check.

## Rollback

Remove the Comms tab/screen, remove the three channel inbox client functions and API tests, and flip `mobile/PARITY.md` for the channel inbox row back to not started.
