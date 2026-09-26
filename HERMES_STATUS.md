# Sprint curent: echivalarea celor 697 de capabilități Hermes

**175 / 697 = 25.1% echivalente complet în evaluarea documentată.**

Din acestea, **67** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 175 | 25.1% |
| Parțial | 345 | 49.5% |
| Lipsă | 65 | 9.3% |
| Exclus intenționat | 107 | 15.4% |
| De reverificat | 5 | 0.7% |

**Ținta acceptată în produs:** 590 rânduri; progres 175/590 = **29.7%**. Cele 107 excluderi rămân vizibile, nu sunt numărate ca implementări.

**Acoperirea reevaluării curente:** 219/697 rânduri. Restul păstrează auditul inițial. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 16 | 27 | 3 | 10 | 0 |
| gateway | 33 | 5 | 18 | 5 | 5 | 0 |
| platforms | 39 | 6 | 22 | 3 | 8 | 0 |
| web | 40 | 13 | 17 | 3 | 7 | 0 |
| desktop | 54 | 11 | 31 | 6 | 6 | 0 |
| tui | 25 | 2 | 12 | 2 | 9 | 0 |
| config | 18 | 4 | 10 | 3 | 1 | 0 |
| env | 28 | 5 | 15 | 1 | 5 | 2 |
| tools — the agent-callable surface | 32 | 13 | 15 | 1 | 2 | 1 |
| skills | 33 | 12 | 10 | 2 | 8 | 1 |
| providers | 27 | 7 | 12 | 1 | 7 | 0 |
| agent-core | 36 | 9 | 15 | 8 | 4 | 0 |
| memory | 27 | 12 | 13 | 0 | 2 | 0 |
| automation | 32 | 3 | 23 | 3 | 3 | 0 |
| security | 34 | 12 | 15 | 2 | 5 | 0 |
| media | 27 | 8 | 15 | 3 | 1 | 0 |
| acp-mcp-dev | 33 | 3 | 13 | 11 | 6 | 0 |
| docs-features | 48 | 12 | 24 | 3 | 9 | 0 |
| rest-api | 33 | 12 | 15 | 2 | 4 | 0 |
| delta | 42 | 10 | 23 | 3 | 5 | 1 |

## Actualizare

Evaluare: `2026-09-26T11:55:27Z`. Cod inspectat: `0a30677ab1ceeb32bc54b2611275d52d580efba1`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
