# Sprint curent: echivalarea celor 697 de capabilități Hermes

**124 / 697 = 17.8% echivalente complet în evaluarea documentată.**

Din acestea, **16** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 124 | 17.8% |
| Parțial | 226 | 32.4% |
| Lipsă | 56 | 8.0% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 291 | 41.8% |

**Ținta acceptată în produs:** 697 rânduri; progres 124/697 = **17.8%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 50/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 15 | 12 | 1 | 0 | 28 |
| gateway | 33 | 6 | 8 | 3 | 0 | 16 |
| platforms | 39 | 5 | 11 | 3 | 0 | 20 |
| web | 40 | 8 | 11 | 3 | 0 | 18 |
| desktop | 54 | 8 | 26 | 6 | 0 | 14 |
| tui | 25 | 1 | 9 | 2 | 0 | 13 |
| config | 18 | 4 | 7 | 2 | 0 | 5 |
| env | 28 | 2 | 10 | 1 | 0 | 15 |
| tools — the agent-callable surface | 32 | 5 | 10 | 1 | 0 | 16 |
| skills | 33 | 9 | 8 | 2 | 0 | 14 |
| providers | 27 | 5 | 8 | 1 | 0 | 13 |
| agent-core | 36 | 7 | 7 | 7 | 0 | 15 |
| memory | 27 | 8 | 7 | 0 | 0 | 12 |
| automation | 32 | 1 | 14 | 2 | 0 | 15 |
| security | 34 | 8 | 8 | 1 | 0 | 17 |
| media | 27 | 7 | 13 | 2 | 0 | 5 |
| acp-mcp-dev | 33 | 3 | 12 | 11 | 0 | 7 |
| docs-features | 48 | 9 | 18 | 3 | 0 | 18 |
| rest-api | 33 | 12 | 15 | 2 | 0 | 4 |
| delta | 42 | 1 | 12 | 3 | 0 | 26 |

## Actualizare

Evaluare: `2026-10-06T14:08:22Z`. Cod inspectat: `c6a855183b26a8b45200d47834565d69aa6dcb0f`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
