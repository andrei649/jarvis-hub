# Incoming attachment size

The existing admin settings surface exposes
`channels.max_inbound_media_bytes`: a whole number from 1 through 20,971,520
bytes, default 8,388,608 (8 MiB). Changes apply to subsequent reads without
restarting the adapters. Zero does not disable the bound; invalid writes are
rejected. An unreadable or malformed stored value uses the 8 MiB default.

Telegram image, voice, and supported document downloads stop when their actual received bytes cross
the limit, regardless of the sender's declared size. The local vision and speech
readers check again before inference or extraction. Telegram documents use the
Workspace's bounded parser for PDF, DOCX, XLSX, CSV, plain text, and Markdown;
the file extension selects a parser only after the file's bytes match that type.
Extracted text is capped at 8,000 characters and fenced as untrusted sender data.
Unsupported or unreadable documents receive a plain refusal, without pretending
the file was read. The adapter checks sender pairing before fetching any readable
photo, voice note, or document. Existing local-provider requirements remain in
force. Email attachment extraction applies the same per-file limit; oversized
attachments retain descriptive metadata but supply no bytes to the reader. The
independent limit on downloading an entire email still applies.

Static Telegram WebP stickers use the same local vision policy as photos, with
a sticker-specific prompt and untrusted-text fence. The adapter checks the
actual WebP format, one frame, and decoded dimensions before inference.
Animated and video stickers remain unsupported. Successful captions are kept
only in a bounded in-memory cache keyed by Telegram's stable file identity and
the current local reader configuration. Each reuse rechecks sender admission,
vision policy, and the current byte limit; failed captions are never cached.

This setting does not enable remote inference or outbound file delivery. No live Telegram or email provider acceptance was performed for this
local implementation.

# Discord owner-DM file replies

A reply to a paired owner's Discord DM may name up to four files with standalone
`MEDIA:` lines. The governed `channel.reply` task resolves each file under the
existing outbound media allowlist and shows its name, size, and SHA-256 on an
approval card. An approved task rechecks the current owner pairing, exact
inbound message and DM recipient, and each file's metadata and bytes before
using the Discord SDK. The transport records a receipt for the reply and for
each file. Duplicate approved deliveries are suppressed when the delivery
ledger is available. A failed file send leaves the reply marked partial.

Ordinary Discord text sends keep `MEDIA:` lines as text. They cannot upload a
file without a live broker approval permit. No live Discord provider send was
performed for this local implementation.
