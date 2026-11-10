# Sprint curent: echivalarea celor 697 de capabilități Hermes

**47 / 697 = 6.7% echivalente complet în evaluarea documentată.**

Din acestea, **47** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 47 | 6.7% |
| Parțial | 239 | 34.3% |
| Lipsă | 102 | 14.6% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 309 | 44.3% |

## Axe separate de contabilizare

**Verdict pe cod înregistrat** (review sau audit moștenit): partial 432, equivalent 152, missing 113. Acesta nu este creditul conservator de mai sus.
**Prospețimea dovezii:** changed 328, current 314, unrecorded 55.
**Impactul schimbării:** pending 309, none 369, accepted 19. Un hash schimbat cere analiză; nu dovedește singur regresia funcțională.
**Acceptare runtime/platform/provider:** runtime: unrecorded 694, verified 3; platform: unrecorded 694, required_pending 3; provider: unrecorded 694, required_pending 3. «unrecorded» nu înseamnă că toate rândurile cer servicii externe.
**Prospețimea acceptării:** runtime: unrecorded 694, stale 3; platform: unrecorded 694, current 1, stale 2; provider: unrecorded 694, current 1, stale 2.
**Scope-uri declarate încă în așteptare:** runtime 0, platform 5, provider 3.

**Ținta acceptată în produs:** 697 rânduri; progres 47/697 = **6.7%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 333/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 1 | 14 | 7 | 0 | 34 |
| gateway | 33 | 1 | 11 | 5 | 0 | 16 |
| platforms | 39 | 2 | 22 | 8 | 0 | 7 |
| web | 40 | 8 | 12 | 6 | 0 | 14 |
| desktop | 54 | 3 | 26 | 9 | 0 | 16 |
| tui | 25 | 0 | 11 | 4 | 0 | 10 |
| config | 18 | 1 | 2 | 2 | 0 | 13 |
| env | 28 | 1 | 11 | 2 | 0 | 14 |
| tools — the agent-callable surface | 32 | 4 | 8 | 2 | 0 | 18 |
| skills | 33 | 6 | 8 | 3 | 0 | 16 |
| providers | 27 | 3 | 8 | 5 | 0 | 11 |
| agent-core | 36 | 2 | 8 | 7 | 0 | 19 |
| memory | 27 | 1 | 4 | 0 | 0 | 22 |
| automation | 32 | 0 | 15 | 2 | 0 | 15 |
| security | 34 | 3 | 9 | 2 | 0 | 20 |
| media | 27 | 4 | 11 | 2 | 0 | 10 |
| acp-mcp-dev | 33 | 1 | 12 | 17 | 0 | 3 |
| docs-features | 48 | 0 | 21 | 7 | 0 | 20 |
| rest-api | 33 | 1 | 17 | 5 | 0 | 10 |
| delta | 42 | 5 | 9 | 7 | 0 | 21 |

## Actualizare

Evaluare: `2026-11-09T23:25:24Z`. Cod inspectat: `85a4179709c8e3551ac1ab98751b06859257c408`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece la «De reverificat» până la analiza de impact. O acceptare explicită a impactului, legată de revizie și verificări, poate păstra verdictul; simpla schimbare de hash nu dovedește regresia. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
