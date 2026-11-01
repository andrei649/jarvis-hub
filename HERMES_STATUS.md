# Sprint curent: echivalarea celor 697 de capabilități Hermes

**76 / 697 = 10.9% echivalente complet în evaluarea documentată.**

Din acestea, **76** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 76 | 10.9% |
| Parțial | 336 | 48.2% |
| Lipsă | 110 | 15.8% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 175 | 25.1% |

**Ținta acceptată în produs:** 697 rânduri; progres 76/697 = **10.9%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 467/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 9 | 34 | 7 | 0 | 6 |
| gateway | 33 | 1 | 18 | 4 | 0 | 10 |
| platforms | 39 | 3 | 24 | 10 | 0 | 2 |
| web | 40 | 11 | 18 | 6 | 0 | 5 |
| desktop | 54 | 3 | 36 | 10 | 0 | 5 |
| tui | 25 | 0 | 16 | 5 | 0 | 4 |
| config | 18 | 2 | 2 | 2 | 0 | 12 |
| env | 28 | 2 | 12 | 2 | 0 | 12 |
| tools — the agent-callable surface | 32 | 5 | 17 | 2 | 0 | 8 |
| skills | 33 | 7 | 13 | 5 | 0 | 8 |
| providers | 27 | 1 | 3 | 4 | 0 | 19 |
| agent-core | 36 | 3 | 9 | 7 | 0 | 17 |
| memory | 27 | 1 | 10 | 2 | 0 | 14 |
| automation | 32 | 3 | 22 | 2 | 0 | 5 |
| security | 34 | 4 | 18 | 3 | 0 | 9 |
| media | 27 | 5 | 13 | 2 | 0 | 7 |
| acp-mcp-dev | 33 | 3 | 13 | 17 | 0 | 0 |
| docs-features | 48 | 0 | 25 | 9 | 0 | 14 |
| rest-api | 33 | 3 | 21 | 5 | 0 | 4 |
| delta | 42 | 10 | 12 | 6 | 0 | 14 |

## Actualizare

Evaluare: `2026-11-01T14:04:40Z`. Cod inspectat: `52af00854d0711b15e4d35bf582a80504efbcd11`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
