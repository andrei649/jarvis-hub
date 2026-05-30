# SPECIFICATION: H2.10 Veronica Content Skill

## 1. Context & Objective
Veronica handles the drafts generation for social platforms (LinkedIn, blog posts). Draft states are serialized locally into separate user JSON objects stored inside `memory_logs/content_drafts/`.

## 2. API Endpoints
Prefix: `/api/skills/content`

### A. POST `/api/skills/content/draft`
Saves a generated raw text snippet or template as a platform draft.
- **Payload**: `{"platform": "linkedin", "title": "AI Trends", "body": "text Content"}`
- **Success Response (200 OK)**: `{"status": "success", "draft_id": "string"}`

### B. GET `/api/skills/content/draft/{platform}`
Fetches active historical logs for a targeted social platform vector.
- **Success Response (200 OK)**: `[{"draft_id": "abc", "title": "AI Trends", "body": "text Content"}]`
