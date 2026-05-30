# Health

> Hercules' health telemetry — analyze metric series + Apple Health summary

**Version:** 0.1.0
**Author:** claude
**Agents:** hercules

## Usage
Analyzes numeric health series (heart rate, HRV, sleep) and can pull a summary
from the Apple Health bridge (`APPLE_HEALTH_BRIDGE_URL`). Degrades gracefully
when the bridge is unreachable.

## Commands
- `analyze <input>` — stats over a series: comma-separated values
- `summary <input>` — Apple Health summary for the last `[days]` (default 1)

## Example Output
```
5 valori — medie 81.0, min 68, max 110, trend ↑
Sumar sănătate — sleep_hours: 7.5, hrv: 62, resting_hr: 54
```
