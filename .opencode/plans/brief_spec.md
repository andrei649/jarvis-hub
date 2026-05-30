# SPECIFICATION: H2.3 Friday Brief Skill

## 1. Context & Objective
Generates a consolidated dashboard metric containing current weather, top news headlines, and market trends. It aggregates OpenWeather, NewsAPI, and financial market tickers.

## 2. API Endpoints
Prefix: `/api/skills/brief`

### A. GET `/api/skills/brief/generate`
Compiles data sources into a standardized strategic overview.
- **Success Response (200 OK)**:
```json
{
    "weather": {"temp": 22.5, "condition": "Sunny"},
    "news": [{"title": "Market Highs", "source": "Reuters"}],
    "market": {"BTC_USD": "68000", "EUR_RON": "4.97"}
}
```

## 3. Robust Aggregation & Fallbacks
- **Partial Failure**: If OpenWeather down but NewsAPI works, populate the weather key with `{"status": "unavailable"}` and return status `200 OK` with the available news and market data.
- **Total Failure**: If all upstream services fail or timeout, fallback immediately to raw cache logs or a static safe payload, returning a degraded `200 OK` summary with a warning flag: `"degraded_mode": true`.
