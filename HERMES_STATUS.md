# Sprint curent: echivalarea celor 697 de capabilități Hermes

**118 / 697 = 16.9% echivalente complet în evaluarea documentată.**

Din acestea, **118** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 118 | 16.9% |
| Parțial | 416 | 59.7% |
| Lipsă | 120 | 17.2% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 43 | 6.2% |

**Ținta acceptată în produs:** 697 rânduri; progres 118/697 = **16.9%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 599/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 10 | 34 | 8 | 0 | 4 |
| gateway | 33 | 2 | 19 | 6 | 0 | 6 |
| platforms | 39 | 3 | 26 | 10 | 0 | 0 |
| web | 40 | 11 | 19 | 5 | 0 | 5 |
| desktop | 54 | 3 | 39 | 10 | 0 | 2 |
| tui | 25 | 2 | 17 | 5 | 0 | 1 |
| config | 18 | 5 | 6 | 3 | 0 | 4 |
| env | 28 | 5 | 21 | 2 | 0 | 0 |
| tools — the agent-callable surface | 32 | 9 | 20 | 3 | 0 | 0 |
| skills | 33 | 10 | 16 | 5 | 0 | 2 |
| providers | 27 | 4 | 15 | 6 | 0 | 2 |
| agent-core | 36 | 6 | 19 | 7 | 0 | 4 |
| memory | 27 | 5 | 17 | 3 | 0 | 2 |
| automation | 32 | 6 | 22 | 2 | 0 | 2 |
| security | 34 | 7 | 24 | 3 | 0 | 0 |
| media | 27 | 7 | 17 | 3 | 0 | 0 |
| acp-mcp-dev | 33 | 3 | 13 | 17 | 0 | 0 |
| docs-features | 48 | 2 | 30 | 10 | 0 | 6 |
| rest-api | 33 | 3 | 25 | 5 | 0 | 0 |
| delta | 42 | 15 | 17 | 7 | 0 | 3 |

## Actualizare

Evaluare: `2026-10-25T06:05:33Z`. Cod inspectat: `bfe4c3a566abfe3e1c8d2d940352d009df1a9e47`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
