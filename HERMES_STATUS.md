# Sprint curent: echivalarea celor 697 de capabilități Hermes

**155 / 697 = 22.2% echivalente complet în evaluarea documentată.**

Din acestea, **155** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 155 | 22.2% |
| Parțial | 469 | 67.3% |
| Lipsă | 41 | 5.9% |
| Exclus intenționat | 32 | 4.6% |
| De reverificat | 0 | 0.0% |

**Ținta acceptată în produs:** 665 rânduri; progres 155/665 = **23.3%**. Excluderi active: 32. Readmise explicit din vechiul audit: 75; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 665/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii de funcționalitate

Fiecare rând aparține unui singur domeniu din [areas.json](docs/hermes/areas.json) (23 domenii). Lane: own = cod Nerva nativ, adopt = cod Hermes preluat, run = sidecar-ul Hermes guvernat. Suita de acceptanță a domeniului ține rândurile echivalente oneste: dacă pică, rândurile echivalente ale domeniului trec la «De reverificat». CI o evaluează la fiecare rulare din rezultatul JUnit al suitei pytest normale (`hermes_status.py verify --junit`), fără a rula testele a doua oară. «Subțire» = sub 5 fișiere sau sub 60% din rândurile reevaluate ale domeniului citează un test din suită; suitele de azi sunt semănate din testele deja citate în dovezi și urmează să fie înlocuite cu suite scrise din perspectiva owner-ului.

| Domeniu | Lane | Rânduri | Echiv. | Parțial | Lipsă | Exclus | Reverificare | Suită | Stare suită |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| [cli](docs/HERMES_CAPABILITIES.md#area-cli) — Command line: jobs done through the nerva CLI | own | 56 | 14 | 36 | 4 | 2 | 0 | 108 | seed din dovezi |
| [gateway](docs/HERMES_CAPABILITIES.md#area-gateway) — Always-on gateway and slash commands | own/run | 33 | 3 | 27 | 1 | 2 | 0 | 101 | seed din dovezi |
| [platforms](docs/HERMES_CAPABILITIES.md#area-platforms) — Messaging platforms and channels | own | 39 | 3 | 27 | 5 | 4 | 0 | 38 | seed din dovezi |
| [web](docs/HERMES_CAPABILITIES.md#area-web) — Web dashboard and HUD | own/run | 40 | 13 | 22 | 3 | 2 | 0 | 66 | seed din dovezi |
| [desktop](docs/HERMES_CAPABILITIES.md#area-desktop) — Desktop app: jobs done in the HUD and Tauri shell | own | 54 | 4 | 42 | 6 | 2 | 0 | 50 | **subțire**, seed din dovezi |
| [tui](docs/HERMES_CAPABILITIES.md#area-tui) — Terminal UI: jobs done in the HUD and nerva CLI | own | 25 | 2 | 19 | 2 | 2 | 0 | 25 | **subțire**, seed din dovezi |
| [config](docs/HERMES_CAPABILITIES.md#area-config) — Configuration and settings | own | 18 | 9 | 9 | 0 | 0 | 0 | 30 | seed din dovezi |
| [env](docs/HERMES_CAPABILITIES.md#area-env) — Environment, install and execution targets | own | 28 | 6 | 21 | 0 | 1 | 0 | 157 | seed din dovezi |
| [tools](docs/HERMES_CAPABILITIES.md#area-tools) — Agent-callable tools and toolsets | adopt/own | 32 | 9 | 22 | 0 | 1 | 0 | 81 | seed din dovezi |
| [skills](docs/HERMES_CAPABILITIES.md#area-skills) — Skills: authoring, catalogue and curation | adopt/own | 33 | 14 | 17 | 1 | 1 | 0 | 78 | seed din dovezi |
| [providers](docs/HERMES_CAPABILITIES.md#area-providers) — Model providers, routing and fallback | adopt/own | 27 | 6 | 17 | 1 | 3 | 0 | 82 | seed din dovezi |
| [agent-core](docs/HERMES_CAPABILITIES.md#area-agent-core) — Agent loop, context and sessions | own | 36 | 10 | 25 | 1 | 0 | 0 | 111 | seed din dovezi |
| [memory](docs/HERMES_CAPABILITIES.md#area-memory) — Memory and recall | own | 27 | 9 | 18 | 0 | 0 | 0 | 69 | seed din dovezi |
| [automation](docs/HERMES_CAPABILITIES.md#area-automation) — Automation: schedules, goals, delegation, kanban | own | 32 | 6 | 26 | 0 | 0 | 0 | 97 | seed din dovezi |
| [security](docs/HERMES_CAPABILITIES.md#area-security) — Security: approvals, sandbox, secrets, egress | own | 34 | 7 | 25 | 1 | 1 | 0 | 211 | seed din dovezi |
| [media](docs/HERMES_CAPABILITIES.md#area-media) — Media: images, video, voice, vision | adopt/own | 27 | 7 | 20 | 0 | 0 | 0 | 100 | seed din dovezi |
| [editor-acp](docs/HERMES_CAPABILITIES.md#area-editor-acp) — Editor agent over ACP | own/adopt | 6 | 0 | 0 | 5 | 1 | 0 | 2 | **subțire**, seed din dovezi |
| [mcp](docs/HERMES_CAPABILITIES.md#area-mcp) — MCP client and server | own/run | 13 | 3 | 9 | 1 | 0 | 0 | 11 | seed din dovezi |
| [agent-interop](docs/HERMES_CAPABILITIES.md#area-agent-interop) — OpenAI-compatible API and agent-to-agent (A2A) | own/adopt | 5 | 0 | 3 | 1 | 1 | 0 | 2 | **subțire**, seed din dovezi |
| [extensions](docs/HERMES_CAPABILITIES.md#area-extensions) — Extensions, hooks and deployment packaging | own/adopt | 9 | 1 | 6 | 0 | 2 | 0 | 13 | seed din dovezi |
| [feature-pages](docs/HERMES_CAPABILITIES.md#area-feature-pages) — Upstream feature pages (cross-cutting) | own/adopt/run | 48 | 5 | 35 | 5 | 3 | 0 | 169 | seed din dovezi |
| [user-journeys](docs/HERMES_CAPABILITIES.md#area-user-journeys) — User journeys from the rest of the docs (cross-cutting) | own | 33 | 4 | 25 | 1 | 3 | 0 | 65 | seed din dovezi |
| [upstream-delta](docs/HERMES_CAPABILITIES.md#area-upstream-delta) — Upstream delta v2026.8.27 to v2026.8.31 (cross-cutting) | own/adopt/run | 42 | 20 | 18 | 3 | 1 | 0 | 150 | seed din dovezi |

Suite subțiri: desktop, tui, editor-acp, agent-interop.

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
