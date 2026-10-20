# Sprint curent: echivalarea celor 697 de capabilități Hermes

**101 / 697 = 14.5% echivalente complet în evaluarea documentată.**

Din acestea, **101** au fost reevaluate pe cod în această livrare; **0** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 101 | 14.5% |
| Parțial | 455 | 65.3% |
| Lipsă | 116 | 16.6% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 25 | 3.6% |

**Ținta acceptată în produs:** 697 rânduri; progres 101/697 = **14.5%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 617/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 6 | 39 | 8 | 0 | 3 |
| gateway | 33 | 2 | 23 | 6 | 0 | 2 |
| platforms | 39 | 3 | 26 | 10 | 0 | 0 |
| web | 40 | 10 | 24 | 5 | 0 | 1 |
| desktop | 54 | 2 | 42 | 10 | 0 | 0 |
| tui | 25 | 2 | 18 | 5 | 0 | 0 |
| config | 18 | 7 | 8 | 3 | 0 | 0 |
| env | 28 | 4 | 19 | 2 | 0 | 3 |
| tools — the agent-callable surface | 32 | 8 | 21 | 3 | 0 | 0 |
| skills | 33 | 8 | 18 | 5 | 0 | 2 |
| providers | 27 | 4 | 16 | 6 | 0 | 1 |
| agent-core | 36 | 5 | 23 | 7 | 0 | 1 |
| memory | 27 | 3 | 16 | 2 | 0 | 6 |
| automation | 32 | 5 | 25 | 2 | 0 | 0 |
| security | 34 | 6 | 24 | 3 | 0 | 1 |
| media | 27 | 7 | 17 | 3 | 0 | 0 |
| acp-mcp-dev | 33 | 1 | 15 | 17 | 0 | 0 |
| docs-features | 48 | 3 | 35 | 8 | 0 | 2 |
| rest-api | 33 | 1 | 25 | 4 | 0 | 3 |
| delta | 42 | 14 | 21 | 7 | 0 | 0 |

## Actualizare

Evaluare: `2026-10-20T12:44:00Z`. Cod inspectat: `35731e4952828f80089bafd0814d8dedb155df7c`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
