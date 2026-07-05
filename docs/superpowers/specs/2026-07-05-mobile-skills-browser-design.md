# H18.15 Mobile Skills Browser Design

## Goal

Bring the browser HUD skills catalog surface to the native mobile app by adding
a read-only Skills tab backed by `GET /skills`.

## Non-goals

- No backend route changes.
- No skill import, install, approve, rollback, or sandbox execution controls.
- No admin-token use.
- No invented/demo rows when the hub returns an empty catalog.

## Approach

The backend `GET /skills` route returns a map-shaped payload:

```json
{
  "skills": {
    "brief": {
      "name": "brief",
      "version": "1.0.0",
      "description": "...",
      "agents": ["jarvis"],
      "commands": []
    }
  }
}
```

The mobile client normalizes that map into a stable array sorted by skill name.
It also tolerates an array-shaped `skills` value so older/local experiments do
not crash the app. The screen renders each skill as a compact read-only card
with name, version, description, agents, and command count.

## Data Contracts

Mobile client additions live in `mobile/src/api/client.ts`:

- `HubSkill`
- `SkillsResponse`
- `fetchSkills(config): Promise<SkillsResponse>`

Normalization guarantees:

- `skills: []` when the field is absent, malformed, or empty.
- `key` is preserved from the map key when present.
- `name` falls back to the map key, then the item id.
- `agents` and `commands` are always arrays.

## Risks

Skill manifests are plugin-shaped and may have sparse metadata. The UI treats
missing descriptions, agents, versions, and commands as blank/empty data rather
than as errors.

## Verification

- Mobile API Jest tests prove request path, user-token auth, map normalization,
  array tolerance, and sparse-payload normalization.
- Mobile TypeScript verifies the new screen and tab wiring.
- `scripts/status_sync.py --check` verifies docs/status counters stay aligned.
