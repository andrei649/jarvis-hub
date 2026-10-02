# Sprint curent: echivalarea celor 697 de capabilități Hermes

**172 / 697 = 24.7% echivalente complet în evaluarea documentată.**

Din acestea, **64** au fost reevaluate pe cod în această livrare; **108** păstrează verdictul auditului din 7 septembrie.

**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.

[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · [Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · [Planul tehnic](docs/HERMES_ABSORPTION.md)

| Stare cod | Rânduri | Din 697 |
|---|---:|---:|
| Echivalent | 172 | 24.7% |
| Parțial | 254 | 36.4% |
| Lipsă | 64 | 9.2% |
| Exclus intenționat | 0 | 0.0% |
| De reverificat | 207 | 29.7% |

**Ținta acceptată în produs:** 697 rânduri; progres 172/697 = **24.7%**. Excluderi active: 0. Readmise explicit din vechiul audit: 107; readmiterea nu acordă credit de implementare.

**Acoperirea reevaluării curente:** 125/697 rânduri. Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. Existența unui fișier sau a unui PR nu închide automat un rând.

**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.

## Pe domenii

| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |
|---|---:|---:|---:|---:|---:|---:|
| cli | 56 | 16 | 14 | 3 | 0 | 23 |
| gateway | 33 | 5 | 9 | 5 | 0 | 14 |
| platforms | 39 | 6 | 19 | 3 | 0 | 11 |
| web | 40 | 16 | 11 | 3 | 0 | 10 |
| desktop | 54 | 9 | 27 | 6 | 0 | 12 |
| tui | 25 | 4 | 9 | 2 | 0 | 10 |
| config | 18 | 5 | 7 | 3 | 0 | 3 |
| env | 28 | 5 | 11 | 1 | 0 | 11 |
| tools — the agent-callable surface | 32 | 7 | 12 | 1 | 0 | 12 |
| skills | 33 | 13 | 9 | 2 | 0 | 9 |
| providers | 27 | 8 | 8 | 1 | 0 | 10 |
| agent-core | 36 | 10 | 8 | 8 | 0 | 10 |
| memory | 27 | 11 | 8 | 0 | 0 | 8 |
| automation | 32 | 3 | 15 | 2 | 0 | 12 |
| security | 34 | 10 | 11 | 2 | 0 | 11 |
| media | 27 | 7 | 15 | 3 | 0 | 2 |
| acp-mcp-dev | 33 | 3 | 12 | 11 | 0 | 7 |
| docs-features | 48 | 11 | 22 | 3 | 0 | 12 |
| rest-api | 33 | 12 | 15 | 2 | 0 | 4 |
| delta | 42 | 11 | 12 | 3 | 0 | 16 |

## Actualizare

Evaluare: `2026-10-02T00:14:39Z`. Cod inspectat: `0382ef0b1329f156086c561b522fdfd404c2b3af`. Inventar înghețat: SHA-256 `7ce9e291cfb6053afb21a08d50b61b0375c17e71be02e1012791780930508686`.

Sursa editabilă este [assessment.json](docs/hermes/assessment.json). Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. Data reauditării moștenite nu este rescrisă.

```text
python scripts/hermes_status.py summary
python scripts/hermes_status.py list --state partial --limit 20
python scripts/hermes_status.py show H515
python scripts/hermes_status.py write
python scripts/hermes_status.py check
```

Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.
