# Sprint curent: echivalarea celor 697 de capabilități Hermes

**122 / 697 = 17.5% echivalente complet în evaluarea documentată.**

Din acestea, **14** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 122 | 17.5% |
| Parțial | 343 | 49.2% |
| Lipsă | 79 | 11.3% |
| Exclus intenționat | 107 | 15.4% |
| De reverificat | 46 | 6.6% |

**Ținta acceptată în produs:** 590 rânduri; progres 122/590 = **20.7%**. Cele 107 excluderi rămân vizibile, nu sunt numărate ca implementări.

**Acoperirea reevaluării curente:** 178/697 rânduri. Restul păstrează auditul inițial. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 16 | 27 | 3 | 10 | 0 |
| gateway | 33 | 5 | 14 | 5 | 5 | 4 |
| platforms | 39 | 5 | 20 | 3 | 8 | 3 |
| web | 40 | 9 | 17 | 5 | 7 | 2 |
| desktop | 54 | 6 | 31 | 9 | 6 | 2 |
| tui | 25 | 1 | 12 | 2 | 9 | 1 |
| config | 18 | 4 | 10 | 3 | 1 | 0 |
| env | 28 | 2 | 17 | 1 | 5 | 3 |
| tools — the agent-callable surface | 32 | 8 | 16 | 2 | 2 | 4 |
| skills | 33 | 6 | 12 | 2 | 8 | 5 |
| providers | 27 | 4 | 12 | 4 | 7 | 0 |
| agent-core | 36 | 7 | 13 | 9 | 4 | 3 |
| memory | 27 | 8 | 13 | 0 | 2 | 4 |
| automation | 32 | 1 | 23 | 3 | 3 | 2 |
| security | 34 | 7 | 17 | 2 | 5 | 3 |
| media | 27 | 7 | 16 | 3 | 1 | 0 |
| acp-mcp-dev | 33 | 3 | 13 | 11 | 6 | 0 |
| docs-features | 48 | 8 | 25 | 5 | 9 | 1 |
| rest-api | 33 | 12 | 15 | 2 | 4 | 0 |
| delta | 42 | 3 | 20 | 5 | 5 | 9 |

## Actualizare

Evaluare: `2026-09-22T20:39:30Z`. Cod inspectat: `6578cd3cc497b601350ab339d1b330cb63d6502c`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
