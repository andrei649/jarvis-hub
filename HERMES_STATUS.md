# Sprint curent: echivalarea celor 697 de capabilități Hermes

**134 / 697 = 19.2% echivalente complet în evaluarea documentată.**

Din acestea, **26** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 134 | 19.2% |
| Parțial | 251 | 36.0% |
| Lipsă | 61 | 8.8% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 251 | 36.0% |

**Ținta acceptată în produs:** 697 rânduri; progres 134/697 = **19.2%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 84/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 15 | 15 | 2 | 0 | 24 |
| gateway | 33 | 5 | 9 | 5 | 0 | 14 |
| platforms | 39 | 6 | 19 | 3 | 0 | 11 |
| web | 40 | 10 | 12 | 3 | 0 | 15 |
| desktop | 54 | 8 | 26 | 6 | 0 | 14 |
| tui | 25 | 2 | 9 | 2 | 0 | 12 |
| config | 18 | 5 | 7 | 3 | 0 | 3 |
| env | 28 | 2 | 10 | 1 | 0 | 15 |
| tools — the agent-callable surface | 32 | 7 | 12 | 1 | 0 | 12 |
| skills | 33 | 10 | 8 | 2 | 0 | 13 |
| providers | 27 | 6 | 9 | 1 | 0 | 11 |
| agent-core | 36 | 8 | 10 | 8 | 0 | 10 |
| memory | 27 | 8 | 8 | 0 | 0 | 11 |
| automation | 32 | 1 | 14 | 2 | 0 | 15 |
| security | 34 | 9 | 8 | 1 | 0 | 16 |
| media | 27 | 7 | 14 | 2 | 0 | 4 |
| acp-mcp-dev | 33 | 3 | 12 | 11 | 0 | 7 |
| docs-features | 48 | 9 | 21 | 3 | 0 | 15 |
| rest-api | 33 | 12 | 15 | 2 | 0 | 4 |
| delta | 42 | 1 | 13 | 3 | 0 | 25 |

## Actualizare

Evaluare: `2026-10-04T09:36:03.709834Z`. Cod inspectat: `b9d4d22dab2f9a663b162003db9f66a27a054d39`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
