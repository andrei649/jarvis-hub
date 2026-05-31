# Security Monitor

> Ultron's local security monitoring — open ports, network devices, Pi-hole, firewall, and threat heuristics

**Version:** 0.1.0
**Author:** claude
**Agents:** ultron

## Usage
Gathers local security data from available sources. All sources are optional —
the skill degrades gracefully when Pi-hole / firewall / /proc are not present.
Works on any dev machine with only psutil installed. No external network calls.

## Commands
- `security_status` — full security snapshot: ports, devices, firewall, pihole, threats
- `ports` — list all listening sockets and their owning processes
- `devices` — network devices from ARP table
- `pihole` — recent Pi-hole blocked query summary
- `firewall` — firewall status (ufw / iptables)
- `threats` — threat heuristics derived from local data

## Example Output
```
Security status: OK
Listening ports (5): 22/sshd, 80/nginx, 443/nginx, 8080/python, 11434/ollama
Devices on LAN (3): 192.168.1.1, 192.168.1.100, 192.168.1.101
Firewall: active (ufw)
Pi-hole: unavailable
Threats: none detected
```
