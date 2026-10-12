# Sprint curent: echivalarea celor 697 de capabilități Hermes

**184 / 697 = 26.4% echivalente complet în evaluarea documentată.**

Din acestea, **76** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 184 | 26.4% |
| Parțial | 313 | 44.9% |
| Lipsă | 56 | 8.0% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 144 | 20.7% |

**Ținta acceptată în produs:** 697 rânduri; progres 184/697 = **26.4%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 197/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 20 | 23 | 1 | 0 | 12 |
| gateway | 33 | 7 | 17 | 3 | 0 | 6 |
| platforms | 39 | 6 | 21 | 3 | 0 | 9 |
| web | 40 | 16 | 12 | 3 | 0 | 9 |
| desktop | 54 | 8 | 33 | 6 | 0 | 7 |
| tui | 25 | 3 | 11 | 2 | 0 | 9 |
| config | 18 | 7 | 8 | 2 | 0 | 1 |
| env | 28 | 4 | 15 | 1 | 0 | 8 |
| tools — the agent-callable surface | 32 | 10 | 15 | 1 | 0 | 6 |
| skills | 33 | 12 | 10 | 2 | 0 | 9 |
| providers | 27 | 8 | 10 | 1 | 0 | 8 |
| agent-core | 36 | 10 | 13 | 7 | 0 | 6 |
| memory | 27 | 10 | 12 | 0 | 0 | 5 |
| automation | 32 | 6 | 18 | 2 | 0 | 6 |
| security | 34 | 10 | 14 | 1 | 0 | 9 |
| media | 27 | 8 | 14 | 2 | 0 | 3 |
| acp-mcp-dev | 33 | 3 | 13 | 11 | 0 | 6 |
| docs-features | 48 | 10 | 22 | 3 | 0 | 13 |
| rest-api | 33 | 12 | 15 | 2 | 0 | 4 |
| delta | 42 | 14 | 17 | 3 | 0 | 8 |

## Actualizare

Evaluare: `2026-10-12T16:46:21Z`. Cod inspectat: `ccb336756824475413f64bfd95d45118f012cbd9`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
