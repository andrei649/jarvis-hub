# Sprint curent: echivalarea celor 697 de capabilități Hermes

**91 / 697 = 13.1% echivalente complet în evaluarea documentată.**

Din acestea, **91** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 91 | 13.1% |
| Parțial | 371 | 53.2% |
| Lipsă | 118 | 16.9% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 117 | 16.8% |

**Ținta acceptată în produs:** 697 rânduri; progres 91/697 = **13.1%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 525/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 1 | 17 | 7 | 0 | 31 |
| gateway | 33 | 2 | 16 | 6 | 0 | 9 |
| platforms | 39 | 3 | 26 | 10 | 0 | 0 |
| web | 40 | 11 | 19 | 6 | 0 | 4 |
| desktop | 54 | 2 | 36 | 10 | 0 | 6 |
| tui | 25 | 1 | 14 | 5 | 0 | 5 |
| config | 18 | 3 | 6 | 3 | 0 | 6 |
| env | 28 | 4 | 17 | 2 | 0 | 5 |
| tools — the agent-callable surface | 32 | 8 | 19 | 3 | 0 | 2 |
| skills | 33 | 8 | 16 | 5 | 0 | 4 |
| providers | 27 | 4 | 14 | 6 | 0 | 3 |
| agent-core | 36 | 5 | 20 | 7 | 0 | 4 |
| memory | 27 | 4 | 15 | 3 | 0 | 5 |
| automation | 32 | 2 | 20 | 2 | 0 | 8 |
| security | 34 | 7 | 20 | 2 | 0 | 5 |
| media | 27 | 7 | 17 | 3 | 0 | 0 |
| acp-mcp-dev | 33 | 2 | 13 | 17 | 0 | 1 |
| docs-features | 48 | 3 | 30 | 9 | 0 | 6 |
| rest-api | 33 | 1 | 19 | 5 | 0 | 8 |
| delta | 42 | 13 | 17 | 7 | 0 | 5 |

## Actualizare

Evaluare: `2026-10-21T20:53:46Z`. Cod inspectat: `64df07c4ddc33a419ee76e403cc67ba7902a2ad7`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
