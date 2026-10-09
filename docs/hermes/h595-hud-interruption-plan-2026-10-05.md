# H595 HUD follow-up messages

Goal: all697, local-only. Base/head:
`a7ffad6676cfb28e7ac374d495b4a5889e5f4646`. Generated: 2026-10-05.

The backend interrupts active conversational code on an admitted new message.
The current HUD `runTurn`/`submit` busy guard drops that message before it reaches
the backend. Make the accepted backend behavior usable through the actual composer.

1. Permit an intentional typed follow-up during a text stream; send it through
   the existing authenticated `/chat/stream` so the backend can interrupt code.
2. Keep each stream's bubble, AbortController and completion separate. Old tokens
   or delayed cognition responses cannot overwrite another message or clear its
   busy state. Preserve normal pending-question, voice, vision and demo behavior.
3. Stop/unmount must cancel and settle every owned stream, including one waiting
   for the server lease. Preserve meaningful double-submit protection.
4. Demonstrate the current dropped-message defect in the rendered App/composer;
   then verify two real stream seams, ordered replies, late callbacks and Stop.
   Run affected frontend tests and build once after the implementation.

Implementer owns `frontend/src/app.tsx`, a narrowly scoped stream helper if needed,
and focused tests. Coordinator owns docs/parity, built assets and integration.
Save preimages before editing; rollback only this batch's diffs and keep inherited
work. No backend redesign, API shape change, dependency updates or publication.
Next action: RED rendered composer follow-up test, then localized implementation.
