# Jarvis Hub — 1.0 Gap Analysis

> Ce lipsește între v0.5-beta și un produs bun de promovat online.

## Pentru 1.0 (după H5)

### Must-have
- [ ] **Onboarding docs** — README cu GIF/screenshot, quickstart în 3 pași, demo video link
- [ ] **Landing page** — `index.html` care explică ce e Jarvis, nu doar chat UI
- [ ] **Single-command setup** — `install.ps1` care instalează tot (Python, dependencies, LM Studio check)
- [ ] **Docker Compose** — `docker-compose.yml` cu toate serviciile (server, Qdrant, Neo4j) + `.env.example`
- [ ] **CI/CD complet** — Release workflow cu GitHub Actions care face artifact
- [ ] **Security review** — Pen-test pe endpointuri, auth pe toate `/api/` routes, CORS config
- [ ] **Error handling** — Toate erorile au mesaje user-friendly, nu stack traces

### Nice-to-have (before 1.0)
- [ ] **Multi-user** — Login cu parolă + sesiuni per user (vs single-user acum)
- [ ] **Mobile app** — PWA installable cu push notifications (H5.2)
- [ ] **Plugin marketplace** — Skills public registry (H5.8)
- [ ] **Performance benchmark** — Pagină `/bench` publică cu stats
- [ ] **Internationalization** — EN default, RO optional (H5.3)

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
  --description "Jarvis Hub — Local-first multi-agent AI orchestration system. 16 agents, Python 3.12 + FastAPI + LM Studio. HUD, voice, Telegram, OAuth, RAG, security sandbox, and more." \
  --homepage "https://github.com/andrei649/jarvis-hub" \
  --add-topic "ai-agent" \
  --add-topic "multi-agent" \
  --add-topic "local-first" \
  --add-topic "fastapi" \
  --add-topic "python" \
  --add-topic "lm-studio" \
  --add-topic "rag"
```
