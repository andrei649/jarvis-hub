# Sprint curent: echivalarea celor 697 de capabilități Hermes

**92 / 697 = 13.2% echivalente complet în evaluarea documentată.**

Din acestea, **92** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 92 | 13.2% |
| Parțial | 373 | 53.5% |
| Lipsă | 111 | 15.9% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 121 | 17.4% |

**Ținta acceptată în produs:** 697 rânduri; progres 92/697 = **13.2%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 521/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 10 | 36 | 7 | 0 | 3 |
| gateway | 33 | 1 | 21 | 4 | 0 | 7 |
| platforms | 39 | 3 | 26 | 10 | 0 | 0 |
| web | 40 | 11 | 18 | 6 | 0 | 5 |
| desktop | 54 | 3 | 37 | 10 | 0 | 4 |
| tui | 25 | 1 | 16 | 5 | 0 | 3 |
| config | 18 | 2 | 3 | 2 | 0 | 11 |
| env | 28 | 2 | 13 | 2 | 0 | 11 |
| tools — the agent-callable surface | 32 | 6 | 18 | 2 | 0 | 6 |
| skills | 33 | 8 | 16 | 5 | 0 | 4 |
| providers | 27 | 1 | 4 | 4 | 0 | 18 |
| agent-core | 36 | 6 | 14 | 7 | 0 | 9 |
| memory | 27 | 3 | 17 | 3 | 0 | 4 |
| automation | 32 | 3 | 23 | 2 | 0 | 4 |
| security | 34 | 4 | 19 | 3 | 0 | 8 |
| media | 27 | 5 | 14 | 2 | 0 | 6 |
| acp-mcp-dev | 33 | 3 | 13 | 17 | 0 | 0 |
| docs-features | 48 | 4 | 28 | 9 | 0 | 7 |
| rest-api | 33 | 3 | 23 | 5 | 0 | 2 |
| delta | 42 | 13 | 14 | 6 | 0 | 9 |

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
