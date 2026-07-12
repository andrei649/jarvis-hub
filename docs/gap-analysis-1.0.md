# Jarvis Hub — 1.0 Gap Analysis

> Ce lipsește între v0.5-beta și un produs bun de promovat online.
>
> **Scope note (2026-07-11):** acest document analizează jumătatea **proof track** a gate-ului 1.0;
> gap-urile programului de capabilități AI-OS (cei 6 piloni, ORIZONT 27–33) sunt în
> [NERVA_VISION.md](../NERVA_VISION.md) §4.
>
> **Actualizat 2026-06-21:** toate orizonturile de features sunt livrate = **v0.10.0**. **1.0 NU mai e "tot
> backlogul terminat"** — e *productionizare* (**H23**) + validare cu useri reali (design partners). Sursa de
> adevăr pentru plan e linia de versiuni din [BACKLOG.md](../BACKLOG.md#version-roadmap) + [MOONSHOT.md](../MOONSHOT.md) §4.
> Engineering must-have-urile de mai jos sunt în mare **livrate** (H7 hardening + onboarding ✅); ce rămâne aici e
> mai ales **launch/promo** (landing page, video, Product Hunt).

## Pentru 1.0 (după H5)

### Must-have
- [x] **Onboarding docs** — README cu quickstart + badges (tests/license/version); *GIF/demo video încă lipsesc*
- [ ] **Landing page** — `index.html` care explică ce e Jarvis, nu doar chat UI
- [x] **Single-command setup** — `INSTALL.bat` / `install.ps1` (Python, dependencies, LM Studio check)
- [x] **Docker Compose** — `docker-compose.yml` + `.env.example` (server, Qdrant, Neo4j)
- [x] **CI/CD pe PR** — Ubuntu+Windows, ruff/mypy/pytest-cov (H7.2 ✅); *release-artifact workflow rămâne*
- [ ] **Security review** — H12.1 (secret store, skill signing, guardrails, PII) ✅; *auth pe `/api/` + CORS + dual-LLM quarantine rămân (H17)*
- [x] **Error handling** — H7 hardening (input validation Pydantic, logging structurat în loc de `except: pass`)

### Nice-to-have (before 1.0)
- [ ] **Multi-user** — Login cu parolă + sesiuni per user (vs single-user acum) — *Phase 2/business, post-1.0*
- [x] **Mobile app** — PWA installable (H5.2) ✅; *push notifications parțiale*
- [x] **Plugin marketplace** — agent/skill marketplace (H5.8) ✅; *registry semnat & moderat = H12.12*
- [x] **Performance benchmark** — pagină `/bench` cu stats ✅
- [x] **Internationalization** — EN/RO (H5.3) ✅

### Pentru promovare online
- [ ] **GitHub repo bine întreținut**:
  - [ ] Description + topics (ex: "AI-agent", "multi-agent", "local-first", "fastapi")
  - [ ] README cu badges (tests, license, version) + screenshots
  - [ ] GitHub Pages site cu demo
- [ ] **Video demo** (30-60s) — walkthrough pe YouTube / Twitter
- [ ] **Blog post** — "Cum am construit un sistem multi-agent local-first"
- [ ] **Product Hunt** sau **Hacker News** launch

## GitHub Actions

```yaml
# Run `gh repo edit` pentru a seta:
gh repo edit andrei649/jarvis-hub \
  --description "Jarvis Hub — Local-first multi-agent AI orchestration system. 16 specialist agents (+ 17 bench), Python 3.12 + FastAPI + LM Studio. HUD, voice, Telegram, OAuth, RAG, security sandbox, and more." \
  --homepage "https://github.com/andrei649/jarvis-hub" \
  --add-topic "ai-agent" \
  --add-topic "multi-agent" \
  --add-topic "local-first" \
  --add-topic "fastapi" \
  --add-topic "python" \
  --add-topic "lm-studio" \
  --add-topic "rag"
```
