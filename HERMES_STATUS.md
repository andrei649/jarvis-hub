# Sprint curent: echivalarea celor 697 de capabilități Hermes

**193 / 697 = 27.7% echivalente complet în evaluarea documentată.**

Din acestea, **85** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 193 | 27.7% |
| Parțial | 228 | 32.7% |
| Lipsă | 56 | 8.0% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 220 | 31.6% |

**Ținta acceptată în produs:** 697 rânduri; progres 193/697 = **27.7%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 121/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 20 | 12 | 1 | 0 | 23 |
| gateway | 33 | 7 | 8 | 3 | 0 | 15 |
| platforms | 39 | 7 | 11 | 3 | 0 | 18 |
| web | 40 | 16 | 11 | 3 | 0 | 10 |
| desktop | 54 | 8 | 27 | 6 | 0 | 13 |
| tui | 25 | 3 | 9 | 2 | 0 | 11 |
| config | 18 | 7 | 7 | 2 | 0 | 2 |
| env | 28 | 5 | 11 | 1 | 0 | 11 |
| tools — the agent-callable surface | 32 | 12 | 12 | 1 | 0 | 7 |
| skills | 33 | 13 | 8 | 2 | 0 | 10 |
| providers | 27 | 8 | 8 | 1 | 0 | 10 |
| agent-core | 36 | 10 | 7 | 7 | 0 | 12 |
| memory | 27 | 11 | 7 | 0 | 0 | 9 |
| automation | 32 | 6 | 13 | 2 | 0 | 11 |
| security | 34 | 13 | 9 | 1 | 0 | 11 |
| media | 27 | 7 | 12 | 2 | 0 | 6 |
| acp-mcp-dev | 33 | 3 | 12 | 11 | 0 | 7 |
| docs-features | 48 | 10 | 18 | 3 | 0 | 17 |
| rest-api | 33 | 12 | 15 | 2 | 0 | 4 |
| delta | 42 | 15 | 11 | 3 | 0 | 13 |

## Actualizare

Evaluare: `2026-10-12T15:32:01Z`. Cod inspectat: `b339672cbc955dcc2119b1a194683be22785b82e`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
