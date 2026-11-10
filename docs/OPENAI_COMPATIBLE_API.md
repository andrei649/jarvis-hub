# Use Nerva from other chat apps (OpenAI-compatible API)

Nerva can answer apps that speak OpenAI's API: Open WebUI, LibreChat, LobeChat, ChatBox,
NextChat, editor plugins, and scripts that use the official `openai` libraries. The app sends
its messages to Nerva instead of to OpenAI. Each message becomes a normal Nerva turn, so Nerva
uses its memory and tools, and its actions follow the same approval rules as in the HUD. With
a guest key, every action that changes something waits for your approval.

This is not a way to lend your cloud model keys to other apps. The app talks to Nerva, and
Nerva decides which model answers, using your own routing settings.

## 1. Turn it on

The API is off until you turn it on.

- **HUD:** Settings → `openai_api` → *OpenAI-compatible API for other chat apps* → on.
- **Terminal:** `nerva config set openai_api.enabled on`

If an administrator pinned this setting in the managed configuration (`/etc/nerva/config.yaml`,
see "Settings an administrator pins" in [INSTALL.md](INSTALL.md)), the switch shows as managed
and you cannot change it. In safe mode (`serve.py --safe-mode`) the API stays off.

## 2. Issue a key

Every request needs a key. Issue keys on the Nerva box:

```bash
python -m agents.core.openai_api keys issue "open-webui on the laptop"           # a guest key
python -m agents.core.openai_api keys issue "my own scripts" --owner              # your own key
python -m agents.core.openai_api keys list
python -m agents.core.openai_api keys revoke key_1a2b3c4d5e6f
```

The key (`nrv-…`) is printed once. Copy it then; Nerva keeps only a hash of it. Your HUD user
and admin tokens do not work as API keys, and an API key opens nothing else in Nerva.

**Owner key or guest key?**

| | Owner key (`--owner`) | Guest key (default) |
|---|---|---|
| Who Nerva thinks is speaking | you, as at the HUD | someone else, through an outside door |
| Actions that change something (write memory, send, buy, run) | follow your normal autonomy settings | always wait in your approval queue |
| Tools offered | your normal tools | the guest tool list |

Give a guest key to anything you do not fully control (a shared machine, a friend's app, a
browser extension). A system prompt sent by the app cannot change any of this: it reaches the
model as text, labelled as instructions from the client app, and never changes tools,
autonomy or approvals.

## 3. Point the app at Nerva

Use these values in the app's "OpenAI-compatible" or "custom OpenAI" provider settings:

- **Base URL:** `http://<your-nerva-host>:8765/v1` (the address you open the HUD on, plus `/v1`)
- **API key:** the `nrv-…` key
- **Model:** `nerva`, or `nerva/<agent>` to ask one of your Nerva agents directly
  (`GET /v1/models` lists them)

Python:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="nrv-...")
reply = client.chat.completions.create(
    model="nerva",
    messages=[{"role": "user", "content": "What's on my calendar tomorrow?"}],
)
print(reply.choices[0].message.content)
```

curl, streamed:

```bash
curl http://127.0.0.1:8765/v1/chat/completions \
  -H "Authorization: Bearer nrv-..." -H "Content-Type: application/json" \
  -d '{"model": "nerva", "stream": true, "messages": [{"role": "user", "content": "hi"}]}'
```

If Nerva is reachable from other machines, put it behind HTTPS (a reverse proxy listed in
`JARVIS_TRUSTED_PROXIES`), because the key travels in a header.

## What works

| Endpoint | What it does |
|---|---|
| `POST /v1/chat/completions` | One answer, whole or streamed (`"stream": true`, with `stream_options.include_usage`). |
| `POST /v1/responses` | The Responses API: answers are stored, `previous_response_id` continues the same conversation, `conversation` names one, `"stream": true` sends the typed events (`response.created` … `response.completed`). `"store": false` keeps nothing. |
| `GET /v1/responses/{id}`, `DELETE /v1/responses/{id}` | Read or delete a stored response. Only the key that made it can see it. |
| `GET /v1/models` | `nerva` and `nerva/<agent>` for each Nerva agent. |

**Conversations.** Chat apps resend the whole conversation on every message. Nerva already
remembers it, so it reads only the newest message. It uses the earlier messages only when a
conversation is new to Nerva. To keep one conversation across devices or restarts, send an
`X-Nerva-Conversation-Id` header, or `metadata.conversation_id` in the body. Without one, Nerva
recognises the conversation by its first messages. Each key has its own conversations. A key
never reaches your HUD conversations or another key's.

**Approvals.** When a turn queues an action, the answer lists the approval ids in its `nerva`
field (`nerva.pending_approvals`). You approve or reject them in the HUD as usual.

**Retries.** A non-streamed chat completion sent with an `Idempotency-Key` header returns the
first answer to a retry instead of running the turn twice.

## Limits (Settings → `openai_api`)

| Setting | Default | What happens past it |
|---|---|---|
| `rate_limit_per_min` | 20 requests per key per minute | `429 rate_limit_exceeded` |
| `max_concurrent` | 2 turns per key at once | `429 too_many_concurrent_requests` |
| `max_request_kb` | 256 KB per request | `413 request_too_large` |
| `max_input_chars` | 16 000 characters per turn | `413 context_length_exceeded` |

## Errors

Errors use OpenAI's format, `{"error": {"message", "type", "param", "code"}}`:

| Status | Code | Meaning |
|---|---|---|
| 404 | `api_disabled` | The API is off (step 1). |
| 401 | `invalid_api_key` | No key, a wrong key or a revoked key. |
| 404 | `model_not_found` | Use `nerva` or a name from `/v1/models`. |
| 409 | `conversation_busy` | Nerva is still answering the previous message in this conversation. |
| 502 | `agent_incomplete` | The turn failed. Nerva reports it as an error, not as the answer. |
| 503 | `model_unavailable` | No language model is loaded in Nerva. |

## Not supported yet

- Images, audio and files in messages (refused with `unsupported_content`). Text only.
- Tools defined by the app (`tools` / function calling). Nerva uses its own tools, and the
  app's are not called.
- A live "tool running" event in the stream, the Runs, Jobs and Sessions APIs, and
  `/api/model/options`.
- Managing keys from the HUD. Keys are issued on the box with the command above.
- Rate and concurrency counters are kept per hub process and reset when it restarts.
