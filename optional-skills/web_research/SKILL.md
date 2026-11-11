# Web Research

> Vision's web research skill — search, extract, summarize with citations

**Version:** 0.1.0
**Author:** claude
**Agents:** vision
**Tier:** business
**LLM Policy:** claude

## Usage
Execută cercetări web folosind Tavily / SearXNG / DuckDuckGo (fallback).
Extrage conținut, sumarizează și returnează un raport structurat cu citări
și URL-uri sursă. Protejat împotriva SSRF la fetch pagini.

## Commands
- `research <query>` — cercetare web cu surse citate

## Example Output
```
🔍 Rezultate cercetare: "piața MarTech CEE"
────────────────────────────────────────────
1. MarTech Trends in CEE 2025
   ...sursa explică creșterea pieței Martech în Europa Centrală...
   🔗 https://example.com/martech-cee-2025

2. Eastern Europe Marketing Technology Report
   ...analiză detaliată a ecosistemului de startup-uri...
   🔗 https://example.com/ee-martech-report

────────────────────────────────────────────
S-au găsit 2 rezultate.
```
