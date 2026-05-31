# System Monitor

> Steve's infrastructure monitoring — CPU, GPU, RAM, disk, services, auto-recovery

**Version:** 0.1.0
**Author:** opencode
**Agents:** steve

## Usage
Monitors Bonobo WS and Pi 5 hardware: CPU/GPU/RAM/disk usage, temperatures,
service health. Auto-recovers failed services when safe. Alerts on thresholds.
Degrades gracefully when psutil or nvidia-smi unavailable.

## Commands
- `status` — full system snapshot (CPU, RAM, GPU, disk, temps)
- `cpu` — CPU usage and load
- `ram` — RAM usage breakdown
- `gpu` — GPU VRAM, utilization, temperature (nvidia-smi)
- `disk <path>` — disk usage for path (default: all mounted partitions)
- `temps` — all available temperature sensors
- `services` — check health of configured services
- `check <service>` — check single service and attempt auto-recovery

## Thresholds
- CPU >80% sustained: warn
- RAM >85%: warn, >95%: critical
- GPU temp >85°C: critical (throttle inference)
- Disk >80%: warn, >90%: critical, >95%: emergency

## Example Output
```
System OK — CPU 23% (8/24 cores active), RAM 14.2/64 GB (22%), GPU 41°C, VRAM 8/24 GB
Disk C: 234/953 GB (24%) — OK
Services: ollama ✓, qdrant ✓, neo4j ✓
```
