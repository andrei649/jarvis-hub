# Pure-placeholder i18n templates (12 strings with no literal words)

The mechanical string checker maps every UI string to the inventory entry that documents it. Twelve
catalog entries normalise to the empty string because they contain **only** interpolation slots,
punctuation or emoji — they carry no word of their own. They are still real translation keys with a
real render shape, so they are documented here rather than silently counted as covered. Each entry
names the key, the literal template, the exact call site, and what the rendered line looks like.

### Gateway list-item template for `/personality`  `id: zz.gateway-personality-item`
- **Surface:** Gateway/Telegram
- **Where:** the body of `/personality` when it lists available personalities.
- **What it does:** renders one personality per line as a bullet with its name in backticks and a preview.
- **How it works:** `locales/en.yaml` → `gateway.personality.item` = `"• \`{name}\` — {preview}"`, rendered at `gateway/slash_commands.py:2615` inside `_handle_personality_command`.
- **Inputs / options:** `name` (personality id), `preview` (first line of its prompt).
- **Outputs / side effects:** one line per personality in the reply.
- **Config / env:** `display.personality` selects the active one.
- **Edge cases / guards:** a personality with no prompt renders an empty preview after the em dash.
- **Rebuild notes:** `f"• `{name}` — {preview}"`. Better: truncate preview to a fixed width so long prompts do not wrap on mobile clients.

### Gateway list-item templates for `/reload-skills`  `id: zz.gateway-reload-skills-items`
- **Surface:** Gateway/Telegram
- **Where:** the reply of `/reload-skills`, one line per reloaded skill.
- **What it does:** lists each reloaded skill, with its description when it has one.
- **How it works:** `gateway.reload_skills.item_with_desc` = `"    - {name}: {desc}"` and `gateway.reload_skills.item_no_desc` = `"    - {name}"`; the branch is at `gateway/slash_commands.py:6009-6010`.
- **Inputs / options:** `name`, `desc` (may be absent).
- **Outputs / side effects:** indented list inside the reload summary.
- **Config / env:** n/a
- **Edge cases / guards:** four-space indent is literal, so clients that trim leading whitespace flatten the nesting.
- **Rebuild notes:** two templates rather than one with a conditional suffix, so translators can reorder name and description independently.

### Gateway list-item templates for `/resume`  `id: zz.gateway-resume-items`
- **Surface:** Gateway/Telegram
- **Where:** the session list `/resume` prints when called without an argument.
- **What it does:** renders one past session per line, bold title plus an optional italic preview; numbered when the list is selectable.
- **How it works:** `gateway.resume.list_item` = `"• **{title}**{preview_part}"`, `gateway.resume.list_item_numbered` = `"{index}. **{title}**{preview_part}"`, `gateway.resume.list_preview_suffix` = `" — _{preview}_"`. Built at `gateway/slash_commands.py:5214-5215`: the suffix is rendered first and passed in as `preview_part`, or left empty when there is no preview.
- **Inputs / options:** `index` (1-based), `title`, `preview`.
- **Outputs / side effects:** the numbered form makes each line selectable by replying with its number.
- **Config / env:** n/a
- **Edge cases / guards:** no preview → `preview_part` is `""` and the line ends after the title.
- **Rebuild notes:** compose the suffix separately so a translation can drop the preview entirely; better: cap the title so the number stays aligned.

### Gateway error passthrough templates  `id: zz.gateway-error-passthrough`
- **Surface:** Gateway/Telegram
- **Where:** `/rollback` when a restore fails; `/title` when title generation warns; any shared handler that surfaces a caught exception.
- **What it does:** prints a bare error string behind a status glyph, with no wording of its own.
- **How it works:** `gateway.rollback.restore_failed` = `"❌ {error}"` (`gateway/slash_commands.py:3507`), `gateway.title.warn_prefix` = `"⚠️ {error}"` (`locales/en.yaml:370`), `gateway.shared.warn_passthrough` = `"⚠️ {error}"` (`gateway/slash_commands.py:5120`).
- **Inputs / options:** `error` — a message produced upstream, already localised or raw.
- **Outputs / side effects:** the reply is whatever the failure said; the template only adds the glyph.
- **Config / env:** n/a
- **Edge cases / guards:** because the text is passed through verbatim, an untranslated internal exception reaches the user in English regardless of locale — the known cost of a passthrough template.
- **Rebuild notes:** glyph + message. Better: classify the error and pick a translated sentence, keeping the raw text behind a `/debug`-style expansion.

### Gateway context meter bar  `id: zz.gateway-context-bar`
- **Surface:** Gateway/Telegram
- **Where:** the `/context` reply, the line that draws the usage meter.
- **What it does:** emits the pre-rendered bar glyph string on its own line.
- **How it works:** `gateway.context.bar` = `"{bar}"` — a pass-through so translators can wrap or pad the meter; rendered at `gateway/slash_commands.py:892` with the bar built by the context-breakdown helper.
- **Inputs / options:** `bar` — the composed block-character meter.
- **Outputs / side effects:** one monospace-ish line inside the context report.
- **Config / env:** the meter's width and thresholds come from the context-breakdown code, not from this key.
- **Edge cases / guards:** a client with proportional fonts renders the bar ragged; the template cannot fix that.
- **Rebuild notes:** keep the key even though it is an identity template — it is the seam a locale needs to add padding or wrap the bar in code fences.

### Gateway voice roster line  `id: zz.gateway-voice-status-member`
- **Surface:** Gateway/Telegram
- **Where:** `/voice status`, one line per participant in the voice room.
- **What it does:** lists a member's display name with a status marker.
- **How it works:** `gateway.voice.status_member` = `"  - {name}{status}"`, rendered at `gateway/slash_commands.py:3396` from each member's `display_name` and a status string composed by the caller.
- **Inputs / options:** `name`, `status` (already includes its own separator when non-empty).
- **Outputs / side effects:** indented roster inside the voice status reply.
- **Config / env:** `voice.*` keys govern the room itself.
- **Edge cases / guards:** `status` is concatenated with no separator, so the caller owns the spacing.
- **Rebuild notes:** two-slot template; better: pass status as a separate translated token instead of a pre-composed string.

### Desktop turn-finished notification body  `id: zz.desktop-turn-done-body`
- **Surface:** Desktop app
- **Where:** the native OS notification posted when a turn finishes while the window is unfocused.
- **What it does:** supplies the notification body — deliberately empty, so the notification shows the reply text instead.
- **How it works:** `apps/desktop/src/i18n/en.ts:193` sets `notifications.native.turnDoneBody: ''`. At `apps/desktop/src/app/session/hooks/use-message-stream/index.ts:794` the body is `text.slice(0, 140) || translateNow('notifications.native.turnDoneBody')` — the empty string is the fallback used only when the assistant's reply has no text at all (a tool-only turn). Paired with `turnDoneTitle` = `'Hermes finished'`.
- **Inputs / options:** none; the first 140 characters of the reply win whenever there are any.
- **Outputs / side effects:** a native notification with a title and, for text turns, a truncated preview.
- **Config / env:** governed by the desktop notification settings panel.
- **Edge cases / guards:** the empty fallback is intentional and identical in every shipped locale (`zh.ts:188`, `zh-hant.ts:188` also `''`) — a body-less notification is preferred to a generic sentence.
- **Rebuild notes:** truncate the reply for the body and leave it blank when there is nothing to show; better: describe the tool-only turn ("3 tools run, no reply") instead of showing nothing.
