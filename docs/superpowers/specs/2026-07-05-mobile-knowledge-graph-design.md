# H18.17 Mobile Knowledge Graph Design

## Goal
Catch the native mobile app up to the browser HUD's read-only knowledge graph surface without adding write controls to the phone.

## Non-goals
- No entity/relation/fact creation, deletion, or rewrite from mobile.
- No new backend routes.
- No ninth bottom-tab item. The graph is a memory surface, so it lives inside the existing Memory tab.

## Surface
- `GET /api/kg/entities?q=&limit=` lists/searches graph entities.
- `GET /api/kg/entities/{name}` returns one entity plus relations.
- `GET /api/kg/facts/as-of?subject=&predicate=` returns current/as-of facts.
- `GET /api/kg/facts/history?subject=&predicate=` returns fact history for a selected subject.

## UX
The existing Memory screen gains an internal segmented control:
- `Turns`: current H18.16 recent turns and session notes.
- `Graph`: entity search/list, selected entity relations, current facts, and selected-subject history.

The Graph view must keep honest empty states for unavailable or empty graph data and label the surface as read-only through affordances rather than adding disabled write buttons.

## Risk
The main risk is mobile nav density. Reusing the Memory tab avoids shrinking the bottom tab bar further.

## Tests
- Red mobile API contract tests prove the client has no KG helpers before implementation.
- Focused Jest for KG client normalization and auth.
- Full mobile Jest and TypeScript check before PR.
