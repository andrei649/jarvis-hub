# Sprint curent: echivalarea celor 697 de capabilități Hermes

**115 / 697 = 16.5% echivalente complet în evaluarea documentată.**

Din acestea, **7** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 115 | 16.5% |
| Parțial | 369 | 52.9% |
| Lipsă | 106 | 15.2% |
| Exclus intenționat | 107 | 15.4% |
| De reverificat | 0 | 0.0% |

**Ținta acceptată în produs:** 590 rânduri; progres 115/590 = **19.5%**. Cele 107 excluderi rămân vizibile, nu sunt numărate ca implementări.

**Acoperirea reevaluării curente:** 98/697 rânduri. Restul păstrează auditul inițial. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 15 | 27 | 4 | 10 | 0 |
| gateway | 33 | 5 | 17 | 6 | 5 | 0 |
| platforms | 39 | 5 | 20 | 6 | 8 | 0 |
| web | 40 | 7 | 17 | 9 | 7 | 0 |
| desktop | 54 | 6 | 33 | 9 | 6 | 0 |
| tui | 25 | 1 | 13 | 2 | 9 | 0 |
| config | 18 | 4 | 10 | 3 | 1 | 0 |
| env | 28 | 2 | 19 | 2 | 5 | 0 |
| tools — the agent-callable surface | 32 | 8 | 19 | 3 | 2 | 0 |
| skills | 33 | 6 | 13 | 6 | 8 | 0 |
| providers | 27 | 4 | 13 | 3 | 7 | 0 |
| agent-core | 36 | 8 | 15 | 9 | 4 | 0 |
| memory | 27 | 8 | 14 | 3 | 2 | 0 |
| automation | 32 | 1 | 24 | 4 | 3 | 0 |
| security | 34 | 7 | 18 | 4 | 5 | 0 |
| media | 27 | 4 | 17 | 5 | 1 | 0 |
| acp-mcp-dev | 33 | 3 | 12 | 12 | 6 | 0 |
| docs-features | 48 | 8 | 26 | 5 | 9 | 0 |
| rest-api | 33 | 12 | 15 | 2 | 4 | 0 |
| delta | 42 | 1 | 27 | 9 | 5 | 0 |

## Actualizare

Evaluare: `2026-09-10T16:30:00Z`. Cod inspectat: `75b73cb79b18d44b6f197c8bbfcdd8b30fbbfbc0`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
