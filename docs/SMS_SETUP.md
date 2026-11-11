# SMS channel setup (Twilio)

Text Nerva from any phone, with no app and no data plan. SMS is **off by default**, and
every reply Nerva sends by SMS waits for your approval, because each message costs money.

Code: `agents/core/channels/sms.py` (the channel), `agents/core/routers/channels_sms.py`
(the webhook). Hermes row H098 (G16).

## What you need

- A Twilio account with an SMS-capable phone number.
- Nerva reachable from the internet over HTTPS at a fixed address (for example behind Caddy
  or a tunnel), so Twilio can call the webhook. Nothing else of the hub needs to be public.

## Settings

| Setting | What it is |
|---|---|
| `JARVIS_SMS_ENABLED=1` | Turns the channel on. Without it the webhook answers 404 and nothing is sent. |
| `JARVIS_SMS_ACCOUNT_SID` | Your Twilio Account SID (`AC…`). |
| `JARVIS_SMS_AUTH_TOKEN` | Your Twilio auth token. Set it in the HUD: **Integrations → channels → SMS (Twilio)**. It is kept in the hub's encrypted secret store. A `.env` value also works and wins. |
| `JARVIS_SMS_FROM_NUMBER` | Your Twilio number in E.164 form, for example `+15550001111`. |
| `JARVIS_SMS_ALLOWED_NUMBERS` | Your own numbers, comma-separated, E.164 (`+15551234567,+447700900123`). Only these numbers, and numbers you pair from the HUD, are heard. |
| `JARVIS_SMS_WEBHOOK_URL` | The exact public URL you give Twilio, for example `https://nerva.example.com/api/channels/sms/webhook`. Set it when Nerva runs behind a proxy, so the signature is checked against the URL Twilio signed. |
| `JARVIS_SMS_REPLY_MAX_PER_HOUR` | At most this many SMS replies per number per hour (default 10). |

Every `JARVIS_` name also works as `NERVA_…`. `JARVIS_SMS_ENABLED` is read when the hub
starts; the others are read on every message, so the auth token set in the HUD takes effect
at once.

## In Twilio

1. Phone Numbers → your number → Messaging → "A message comes in": **Webhook**, `HTTP POST`,
   the URL above.
2. Text the number from one of your allowed phones. Nerva answers with nothing at first; the
   reply appears as an approval card in the HUD (and on Telegram if you use it). Approve it and
   the SMS is sent.

The HUD's Integrations **Test** button checks the settings without sending anything.

## What is checked

- **Signature.** Every request must carry `X-Twilio-Signature`, the HMAC-SHA1 of the URL and
  the sorted form parameters with your auth token. A missing or wrong signature, or a request
  for another Twilio account, is refused with 403. The URL is tried with and without its
  default port, as Twilio may sign either.
- **Size.** Bodies over 65,536 bytes are refused (413).
- **Replays.** Twilio signs no timestamp, so Nerva remembers every message id for 24 hours; a
  replayed request is answered and dropped.
- **Who.** A text from a number that is neither allowed nor paired is ignored and **never
  answered** (an answer would cost money and confirm the number). It shows up as a pairing
  request in the HUD, where you can approve it. Turning pairing off does not open SMS.
- **Echoes.** A message from your own Twilio number is dropped.
- **Privacy.** Numbers are logged only as `+1…4567`; delivery receipts keep a digest of the
  number, never the number itself.

## Replies

- Each reply is an approval card at the money tier: it waits for you in every autonomy mode,
  even when the Action Kernel is on. The emergency stop and plan mode still apply first.
- An approved reply goes only to the number that wrote the message it answers. It is plain
  text, in parts of 1,600 characters, at most three parts; a longer reply is cut and says so.
- A retried approval never sends the same reply twice (delivery receipt keyed by the task).
- Picture messages (MMS) are not read; Nerva is told how many pictures came with the text.

## Not yet

- Unattended replies (without an approval per message).
- Sending an SMS that is not a reply (`nerva send`, scheduled notices).
- File attachments by SMS.
