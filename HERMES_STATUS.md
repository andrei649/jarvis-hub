# Sprint curent: echivalarea celor 697 de capabilități Hermes

**119 / 697 = 17.1% echivalente complet în evaluarea documentată.**

Din acestea, **11** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 119 | 17.1% |
| Parțial | 366 | 52.5% |
| Lipsă | 91 | 13.1% |
| Exclus intenționat | 107 | 15.4% |
| De reverificat | 14 | 2.0% |

**Ținta acceptată în produs:** 590 rânduri; progres 119/590 = **20.2%**. Cele 107 excluderi rămân vizibile, nu sunt numărate ca implementări.

**Acoperirea reevaluării curente:** 117/697 rânduri. Restul păstrează auditul inițial. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 16 | 27 | 3 | 10 | 0 |
| gateway | 33 | 5 | 13 | 6 | 5 | 4 |
| platforms | 39 | 5 | 19 | 5 | 8 | 2 |
| web | 40 | 7 | 17 | 6 | 7 | 3 |
| desktop | 54 | 6 | 35 | 7 | 6 | 0 |
| tui | 25 | 1 | 13 | 2 | 9 | 0 |
| config | 18 | 4 | 10 | 3 | 1 | 0 |
| env | 28 | 2 | 19 | 2 | 5 | 0 |
| tools — the agent-callable surface | 32 | 8 | 19 | 3 | 2 | 0 |
| skills | 33 | 6 | 13 | 6 | 8 | 0 |
| providers | 27 | 4 | 13 | 3 | 7 | 0 |
| agent-core | 36 | 7 | 15 | 9 | 4 | 1 |
| memory | 27 | 8 | 14 | 3 | 2 | 0 |
| automation | 32 | 1 | 24 | 3 | 3 | 1 |
| security | 34 | 7 | 17 | 4 | 5 | 1 |
| media | 27 | 6 | 15 | 4 | 1 | 1 |
| acp-mcp-dev | 33 | 3 | 13 | 11 | 6 | 0 |
| docs-features | 48 | 8 | 26 | 5 | 9 | 0 |
| rest-api | 33 | 12 | 15 | 2 | 4 | 0 |
| delta | 42 | 3 | 29 | 4 | 5 | 1 |

## Actualizare

Evaluare: `2026-09-22T17:10:53Z`. Cod inspectat: `b1fd9c4204d4de310cd70e951ff5e478eeb91442`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
