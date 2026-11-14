# Sprint curent: echivalarea celor 697 de capabilități Hermes

**187 / 697 = 26.8% echivalente complet în evaluarea documentată.**

Din acestea, **187** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 187 | 26.8% |
| Parțial | 474 | 68.0% |
| Lipsă | 0 | 0.0% |
| Exclus intenționat | 36 | 5.2% |
| De reverificat | 0 | 0.0% |

**Ținta acceptată în produs:** 661 rânduri; progres 187/661 = **28.3%**. Excluderi active: 36. Readmise explicit din vechiul audit: 71; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 661/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii de funcționalitate

Fiecare rând aparține unui singur domeniu din [areas.json](docs/hermes/areas.json) (23 domenii). Lane: own = cod Nerva nativ, adopt = cod Hermes preluat, run = sidecar-ul Hermes guvernat. Suita de acceptanță a domeniului ține rândurile echivalente oneste: dacă pică, rândurile echivalente ale domeniului trec la «De reverificat». CI o evaluează la fiecare rulare din rezultatul JUnit al suitei pytest normale (`hermes_status.py verify --junit`), fără a rula testele a doua oară. «Subțire» = sub 5 fișiere sau sub 60% din rândurile reevaluate ale domeniului citează un test din suită; suitele de azi sunt semănate din testele deja citate în dovezi și urmează să fie înlocuite cu suite scrise din perspectiva owner-ului.

| Domeniu | Lane | Rânduri | Echiv. | Parțial | Lipsă | Exclus | Reverificare | Suită | Stare suită |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| [cli](docs/HERMES_CAPABILITIES.md#area-cli) — Command line: jobs done through the nerva CLI | own | 56 | 21 | 33 | 0 | 2 | 0 | 123 | seed din dovezi |
| [gateway](docs/HERMES_CAPABILITIES.md#area-gateway) — Always-on gateway and slash commands | own/run | 33 | 6 | 25 | 0 | 2 | 0 | 252 | seed din dovezi |
| [platforms](docs/HERMES_CAPABILITIES.md#area-platforms) — Messaging platforms and channels | own | 39 | 6 | 27 | 0 | 6 | 0 | 46 | seed din dovezi |
| [web](docs/HERMES_CAPABILITIES.md#area-web) — Web dashboard and HUD | own/run | 40 | 15 | 23 | 0 | 2 | 0 | 71 | seed din dovezi |
| [desktop](docs/HERMES_CAPABILITIES.md#area-desktop) — Desktop app: jobs done in the HUD and Tauri shell | own | 54 | 6 | 46 | 0 | 2 | 0 | 54 | seed din dovezi |
| [tui](docs/HERMES_CAPABILITIES.md#area-tui) — Terminal UI: jobs done in the HUD and nerva CLI | own | 25 | 4 | 19 | 0 | 2 | 0 | 30 | seed din dovezi |
| [config](docs/HERMES_CAPABILITIES.md#area-config) — Configuration and settings | own | 18 | 9 | 9 | 0 | 0 | 0 | 30 | seed din dovezi |
| [env](docs/HERMES_CAPABILITIES.md#area-env) — Environment, install and execution targets | own | 28 | 6 | 21 | 0 | 1 | 0 | 157 | seed din dovezi |
| [tools](docs/HERMES_CAPABILITIES.md#area-tools) — Agent-callable tools and toolsets | adopt/own | 32 | 11 | 20 | 0 | 1 | 0 | 82 | seed din dovezi |
| [skills](docs/HERMES_CAPABILITIES.md#area-skills) — Skills: authoring, catalogue and curation | adopt/own | 33 | 14 | 18 | 0 | 1 | 0 | 80 | seed din dovezi |
| [providers](docs/HERMES_CAPABILITIES.md#area-providers) — Model providers, routing and fallback | adopt/own | 27 | 6 | 17 | 0 | 4 | 0 | 82 | seed din dovezi |
| [agent-core](docs/HERMES_CAPABILITIES.md#area-agent-core) — Agent loop, context and sessions | own | 36 | 11 | 25 | 0 | 0 | 0 | 113 | seed din dovezi |
| [memory](docs/HERMES_CAPABILITIES.md#area-memory) — Memory and recall | own | 27 | 10 | 17 | 0 | 0 | 0 | 70 | seed din dovezi |
| [automation](docs/HERMES_CAPABILITIES.md#area-automation) — Automation: schedules, goals, delegation, kanban | own | 32 | 6 | 26 | 0 | 0 | 0 | 98 | seed din dovezi |
| [security](docs/HERMES_CAPABILITIES.md#area-security) — Security: approvals, sandbox, secrets, egress | own | 34 | 9 | 24 | 0 | 1 | 0 | 217 | seed din dovezi |
| [media](docs/HERMES_CAPABILITIES.md#area-media) — Media: images, video, voice, vision | adopt/own | 27 | 7 | 20 | 0 | 0 | 0 | 101 | seed din dovezi |
| [editor-acp](docs/HERMES_CAPABILITIES.md#area-editor-acp) — Editor agent over ACP | own/adopt | 6 | 0 | 5 | 0 | 1 | 0 | 4 | **subțire**, seed din dovezi |
| [mcp](docs/HERMES_CAPABILITIES.md#area-mcp) — MCP client and server | own/run | 13 | 3 | 10 | 0 | 0 | 0 | 14 | seed din dovezi |
| [agent-interop](docs/HERMES_CAPABILITIES.md#area-agent-interop) — OpenAI-compatible API and agent-to-agent (A2A) | own/adopt | 5 | 0 | 4 | 0 | 1 | 0 | 4 | **subțire**, seed din dovezi |
| [extensions](docs/HERMES_CAPABILITIES.md#area-extensions) — Extensions, hooks and deployment packaging | own/adopt | 9 | 1 | 6 | 0 | 2 | 0 | 30 | seed din dovezi |
| [feature-pages](docs/HERMES_CAPABILITIES.md#area-feature-pages) — Upstream feature pages (cross-cutting) | own/adopt/run | 48 | 7 | 37 | 0 | 4 | 0 | 175 | seed din dovezi |
| [user-journeys](docs/HERMES_CAPABILITIES.md#area-user-journeys) — User journeys from the rest of the docs (cross-cutting) | own | 33 | 6 | 24 | 0 | 3 | 0 | 68 | seed din dovezi |
| [upstream-delta](docs/HERMES_CAPABILITIES.md#area-upstream-delta) — Upstream delta v2026.8.27 to v2026.8.31 (cross-cutting) | own/adopt/run | 42 | 23 | 18 | 0 | 1 | 0 | 153 | seed din dovezi |

Suite subțiri: editor-acp, agent-interop.

## Actualizare

Evaluare: `2026-11-10T17:33:57Z`. Cod inspectat: `7e263d5933731255ea297f324e7905368a400aa6`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json): verdict, motiv, lipsuri și căile dovezilor (fără hash-uri). Un merge care doar mută sau editează cod nu schimbă niciun rând; un rând se schimbă când cineva îl reevaluează sau când suita domeniului său pică. Citările `cale:linie` din texte sunt indicatoare în proză, nu sunt fixate. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
python scripts/hermes_status.py verify --area mcp
python scripts/hermes_status.py verify --junit pytest-junit.xml
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri, harta domeniilor și lipsa derivării unor procente din PR-uri sau din bifele HA.
