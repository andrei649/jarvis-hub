# Sprint curent: echivalarea celor 697 de capabilități Hermes

**145 / 697 = 20.8% echivalente complet în evaluarea documentată.**

Din acestea, **145** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 145 | 20.8% |
| Parțial | 422 | 60.5% |
| Lipsă | 113 | 16.2% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 17 | 2.4% |

**Ținta acceptată în produs:** 697 rânduri; progres 145/697 = **20.8%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 625/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 13 | 32 | 8 | 0 | 3 |
| gateway | 33 | 3 | 21 | 6 | 0 | 3 |
| platforms | 39 | 3 | 25 | 10 | 0 | 1 |
| web | 40 | 13 | 21 | 6 | 0 | 0 |
| desktop | 54 | 4 | 40 | 10 | 0 | 0 |
| tui | 25 | 2 | 18 | 5 | 0 | 0 |
| config | 18 | 7 | 6 | 2 | 0 | 3 |
| env | 28 | 4 | 18 | 2 | 0 | 4 |
| tools — the agent-callable surface | 32 | 9 | 21 | 2 | 0 | 0 |
| skills | 33 | 14 | 15 | 4 | 0 | 0 |
| providers | 27 | 6 | 16 | 5 | 0 | 0 |
| agent-core | 36 | 10 | 19 | 7 | 0 | 0 |
| memory | 27 | 9 | 17 | 1 | 0 | 0 |
| automation | 32 | 6 | 24 | 2 | 0 | 0 |
| security | 34 | 7 | 23 | 3 | 0 | 1 |
| media | 27 | 7 | 18 | 2 | 0 | 0 |
| acp-mcp-dev | 33 | 3 | 12 | 17 | 0 | 1 |
| docs-features | 48 | 4 | 35 | 9 | 0 | 0 |
| rest-api | 33 | 3 | 24 | 5 | 0 | 1 |
| delta | 42 | 18 | 17 | 7 | 0 | 0 |

## Actualizare

Evaluare: `2026-11-10T08:19:49Z`. Cod inspectat: `dc6f9317aedf014f194ccb2981b2e3235c31fdbe`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
