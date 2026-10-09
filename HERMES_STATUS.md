# Sprint curent: echivalarea celor 697 de capabilități Hermes

**128 / 697 = 18.4% echivalente complet în evaluarea documentată.**

Din acestea, **20** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 128 | 18.4% |
| Parțial | 246 | 35.3% |
| Lipsă | 63 | 9.0% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 260 | 37.3% |

**Ținta acceptată în produs:** 697 rânduri; progres 128/697 = **18.4%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 73/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 16 | 14 | 3 | 0 | 23 |
| gateway | 33 | 6 | 9 | 4 | 0 | 14 |
| platforms | 39 | 5 | 19 | 3 | 0 | 12 |
| web | 40 | 9 | 11 | 3 | 0 | 17 |
| desktop | 54 | 6 | 26 | 6 | 0 | 16 |
| tui | 25 | 2 | 9 | 2 | 0 | 12 |
| config | 18 | 4 | 7 | 3 | 0 | 4 |
| env | 28 | 2 | 11 | 1 | 0 | 14 |
| tools — the agent-callable surface | 32 | 7 | 12 | 1 | 0 | 12 |
| skills | 33 | 8 | 8 | 2 | 0 | 15 |
| providers | 27 | 6 | 8 | 1 | 0 | 12 |
| agent-core | 36 | 8 | 8 | 8 | 0 | 12 |
| memory | 27 | 8 | 8 | 0 | 0 | 11 |
| automation | 32 | 1 | 15 | 2 | 0 | 14 |
| security | 34 | 8 | 8 | 2 | 0 | 16 |
| media | 27 | 7 | 13 | 3 | 0 | 4 |
| acp-mcp-dev | 33 | 3 | 12 | 11 | 0 | 7 |
| docs-features | 48 | 8 | 21 | 3 | 0 | 16 |
| rest-api | 33 | 12 | 15 | 2 | 0 | 4 |
| delta | 42 | 2 | 12 | 3 | 0 | 25 |

## Actualizare

Evaluare: `2026-10-08T13:38:58.177807Z`. Cod inspectat: `36b54419225132b3eb73fec18ad1f2fe3ccdbdc8`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
