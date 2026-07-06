# TASK-3 Channel Ingress Taint Design

## Goal

Mark untrusted inbound channel messages at the gateway boundary so the channel inbox and handler seam carry explicit taint metadata.

## Non-Goals

- Do not wrap the handler's `text` argument in an object; it remains a plain string.
- Do not change the Action Kernel origin behavior; inbound channel actions already queue by declared origin.
- Do not persist raw extra metadata values in the channel inbox.
- Do not mark trusted operator channels (`web`, `voice`) as tainted.

## Current Seam

`Gateway.route()` classifies turn origin and records telegram/web messages in `ChannelInboxStore`. The downstream kernel and memory paths now have origin/taint defenses, but the gateway itself does not attach an explicit taint record to the inbound channel message.

## Approach

At `Gateway.route()`:

- compute the existing origin with `origin_for_channel(channel)`;
- for untrusted inbound origins, build a private `_inbound_meta` dictionary with `tainted`, `taint_source`, and `injection_flags`;
- pass `_inbound_meta` to the handler as metadata, not as the text value;
- record the same taint fields into `ChannelInboxStore`.

At `Orchestrator.channel_handler()`:

- consume `_inbound_meta` before replying so private gateway metadata cannot leak into outbound adapter kwargs.

At `ChannelInboxStore`:

- preserve only public taint fields: `tainted`, `taint_source`, and `injection_flags`.

## Risk

The main compatibility risk is changing the handler text type or leaking metadata to outbound adapters. This design avoids both: text remains `str`, and the orchestrator pops `_inbound_meta` before calling `ChannelManager.send()`.

## Verification

- Red/green gateway test for untrusted telegram metadata.
- Red/green inbox test for persisted taint fields.
- Regression that trusted `web` input remains untainted.
- Adjacent Safe Comms, pairing, cross-channel, and taint/kernel tests.
