# SPECIFICATION: H2.4 Hercules Health Skill

## 1. Context & Objective
Hercules processes health telemetry structures exported from XML/JSON bundles (Apple Health style). Since it runs inside a server framework, it does not connect to a physical Apple Watch device; it parses flat exported logs.

## 2. API Endpoints
Prefix: `/api/skills/health`

### A. POST `/api/skills/health/metrics`
Accepts a structured health metrics payload for statistical trend analysis.
- **Payload**:
```json
{
    "metric_type": "heart_rate",
    "values": [72, 75, 80, 110, 68],
    "unit": "count/min"
}
```
- **Success Response (200 OK)**:
```json
{
    "status": "processed",
    "analysis": {"mean": 81.0, "max": 110.0, "min": 68.0}
}
```
