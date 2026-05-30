# Brief

> Friday's morning brief — weather + news consolidated, degrades gracefully

**Version:** 0.1.0
**Author:** claude
**Agents:** friday

## Usage
Consolidates weather (wttr.in) and news (RSS) into one briefing. Each source
degrades independently; if any fails the brief still returns with
`degraded_mode=True`.

## Commands
- `brief <input>` — generate the morning briefing for an optional `[location]`

## Example Output
```
☀️ Brief de dimineață:
Vreme: București: +18°C, Clear
Știri (3):
- Headline one
- Headline two
```
