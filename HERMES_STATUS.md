# Sprint curent: echivalarea celor 697 de capabilități Hermes

**196 / 697 = 28.1% echivalente complet în evaluarea documentată.**

Din acestea, **89** au fost reevaluate pe cod în această livrare; **107** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 196 | 28.1% |
| Parțial | 382 | 54.8% |
| Lipsă | 119 | 17.1% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 0 | 0.0% |

**Ținta acceptată în produs:** 697 rânduri; progres 196/697 = **28.1%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 535/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 20 | 28 | 8 | 0 | 0 |
| gateway | 33 | 7 | 21 | 5 | 0 | 0 |
| platforms | 39 | 7 | 22 | 10 | 0 | 0 |
| web | 40 | 16 | 18 | 6 | 0 | 0 |
| desktop | 54 | 8 | 36 | 10 | 0 | 0 |
| tui | 25 | 3 | 17 | 5 | 0 | 0 |
| config | 18 | 8 | 7 | 3 | 0 | 0 |
| env | 28 | 5 | 21 | 2 | 0 | 0 |
| tools — the agent-callable surface | 32 | 12 | 17 | 3 | 0 | 0 |
| skills | 33 | 13 | 15 | 5 | 0 | 0 |
| providers | 27 | 8 | 13 | 6 | 0 | 0 |
| agent-core | 36 | 10 | 19 | 7 | 0 | 0 |
| memory | 27 | 11 | 14 | 2 | 0 | 0 |
| automation | 32 | 6 | 24 | 2 | 0 | 0 |
| security | 34 | 12 | 19 | 3 | 0 | 0 |
| media | 27 | 9 | 15 | 3 | 0 | 0 |
| acp-mcp-dev | 33 | 3 | 13 | 17 | 0 | 0 |
| docs-features | 48 | 11 | 27 | 10 | 0 | 0 |
| rest-api | 33 | 12 | 16 | 5 | 0 | 0 |
| delta | 42 | 15 | 20 | 7 | 0 | 0 |

## Actualizare

Evaluare: `2026-10-14T08:15:32Z`. Cod inspectat: `5ce7d63ce00428b7d9a73acf9ff6e6287ed09a4f`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
