# Sprint curent: echivalarea celor 697 de capabilități Hermes

**148 / 697 = 21.2% echivalente complet în evaluarea documentată.**

Din acestea, **148** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 148 | 21.2% |
| Parțial | 460 | 66.0% |
| Lipsă | 57 | 8.2% |
| Exclus intenționat | 32 | 4.6% |
| De reverificat | 0 | 0.0% |

**Ținta acceptată în produs:** 665 rânduri; progres 148/665 = **22.3%**. Excluderi active: 32. Readmise explicit din vechiul audit: 75; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 665/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 14 | 35 | 5 | 2 | 0 |
| gateway | 33 | 3 | 27 | 1 | 2 | 0 |
| platforms | 39 | 3 | 27 | 5 | 4 | 0 |
| web | 40 | 13 | 22 | 3 | 2 | 0 |
| desktop | 54 | 4 | 42 | 6 | 2 | 0 |
| tui | 25 | 2 | 19 | 2 | 2 | 0 |
| config | 18 | 8 | 9 | 1 | 0 | 0 |
| env | 28 | 5 | 21 | 1 | 1 | 0 |
| tools — the agent-callable surface | 32 | 9 | 22 | 0 | 1 | 0 |
| skills | 33 | 14 | 17 | 1 | 1 | 0 |
| providers | 27 | 6 | 17 | 1 | 3 | 0 |
| agent-core | 36 | 10 | 24 | 2 | 0 | 0 |
| memory | 27 | 9 | 18 | 0 | 0 | 0 |
| automation | 32 | 6 | 25 | 1 | 0 | 0 |
| security | 34 | 7 | 25 | 1 | 1 | 0 |
| media | 27 | 7 | 19 | 1 | 0 | 0 |
| acp-mcp-dev | 33 | 3 | 13 | 13 | 4 | 0 |
| docs-features | 48 | 4 | 35 | 6 | 3 | 0 |
| rest-api | 33 | 3 | 25 | 2 | 3 | 0 |
| delta | 42 | 18 | 18 | 5 | 1 | 0 |

## Actualizare

Evaluare: `2026-11-10T17:33:57Z`. Cod inspectat: `7e263d5933731255ea297f324e7905368a400aa6`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
