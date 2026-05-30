# SPECIFICATION: H2.7 Hephaestus PM Skill

## 1. Context & Objective
A local project manager that tracks development epics and tasks inside a standalone SQLite file database. It utilizes `aiosqlite` for asynchronous connection pooling.

## 2. API Endpoints
Prefix: `/api/skills/pm`

### A. GET `/api/skills/pm/tasks`
Lists all tracked tasks.
- **Success Response (200 OK)**: `[{"id": 1, "title": "Implement RAG", "status": "todo"}]`

### B. POST `/api/skills/pm/tasks`
Creates a task.
- **Payload**: `{"title": "string", "status": "string"}`
- **Success Response (201 Created)**: `{"status": "success", "id": 1}`

## 3. SQLite Thread Safety & Transient Storage
- Database schema initialization (`CREATE TABLE IF NOT EXISTS tasks...`) must occur automatically on module startup.
- In test environments, the database path must be configurable to use temporary paths (`tmp_path`) to enforce clean, isolated mock states.
