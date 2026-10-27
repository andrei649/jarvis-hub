# Sprint curent: echivalarea celor 697 de capabilități Hermes

**72 / 697 = 10.3% echivalente complet în evaluarea documentată.**

Din acestea, **72** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 72 | 10.3% |
| Parțial | 331 | 47.5% |
| Lipsă | 116 | 16.6% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 178 | 25.5% |

**Ținta acceptată în produs:** 697 rânduri; progres 72/697 = **10.3%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 464/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 10 | 32 | 8 | 0 | 6 |
| gateway | 33 | 1 | 19 | 6 | 0 | 7 |
| platforms | 39 | 2 | 23 | 7 | 0 | 7 |
| web | 40 | 7 | 13 | 6 | 0 | 14 |
| desktop | 54 | 1 | 36 | 10 | 0 | 7 |
| tui | 25 | 2 | 15 | 5 | 0 | 3 |
| config | 18 | 4 | 6 | 3 | 0 | 5 |
| env | 28 | 1 | 15 | 2 | 0 | 10 |
| tools — the agent-callable surface | 32 | 5 | 17 | 3 | 0 | 7 |
| skills | 33 | 7 | 11 | 5 | 0 | 10 |
| providers | 27 | 4 | 12 | 6 | 0 | 5 |
| agent-core | 36 | 3 | 10 | 7 | 0 | 16 |
| memory | 27 | 1 | 12 | 2 | 0 | 12 |
| automation | 32 | 3 | 12 | 2 | 0 | 15 |
| security | 34 | 2 | 15 | 3 | 0 | 14 |
| media | 27 | 5 | 15 | 3 | 0 | 4 |
| acp-mcp-dev | 33 | 1 | 10 | 16 | 0 | 6 |
| docs-features | 48 | 0 | 23 | 10 | 0 | 15 |
| rest-api | 33 | 3 | 22 | 5 | 0 | 3 |
| delta | 42 | 10 | 13 | 7 | 0 | 12 |

## Actualizare

Evaluare: `2026-10-27T18:12:33Z`. Cod inspectat: `815e176e34fe659b1a6abeae4a67ba4b85b22384`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
