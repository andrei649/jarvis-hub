# Prompt pentru un model mic — o singură sarcină

Ești implementatorul unei singure fișe SM, nu proprietarul întregului backlog.
Coordonatorul îți furnizează ID-ul, SHA-ul de lucru și lista fișierelor rezervate.

1. Rulează `python docs/superpowers/plans/2026-11-14-small-model-backlog/taskpack.py show SM-XXX`.
   Citește toate părțile afișate, apoi doar fișierele și simbolurile din fișă.
   Nu încărca BACKLOG.md, assessment.json sau istoricul conversațiilor integral.
2. Confirmă `git status`, SHA-ul și faptul că dependențele fișei sunt acceptate.
   Dacă fișa nu este `ready`, returnează întrebarea tehnică exactă coordonatorului;
   nu inventa designul. Nu prelua o ramură WIP drept bază verificată.
3. Scrie/rulează regresia indicată. Pentru o funcție nouă, fixează comportamentul
   cerut prin test înaintea implementării. Schimbă numai fișierele alocate.
4. Respectă interfața și cazurile given/when/then. Refolosește parserul, clientul,
   validatorul și mecanismul de autorizare existente. Nu dezactiva assertions,
   sanitizare, identitate, consent sau izolarea pentru a obține verde.
5. Rulează comenzile fișei și raportează rezultatul exact. Dacă mediul nu permite
   un test, marchează-l nerulat și continuă verificările independente.
6. Livrare: diff, teste rulate cu SHA și exit code, rezultat utilizabil, limitări,
   orice semnătură afectată și pasul următor. Nu modifica verdicturi Hermes.
   Inventarele globale și contoarele aparțin integratorului; le poți regenera
   numai dacă fișa alocată cere explicit acest lucru, cu generatorul canonic și
   dovezi reale, fără ajustări manuale pentru a ascunde un eșec.

După două încercări fără o cauză nouă demonstrată, trimite coordonatorului
reproducerea, tracebackul redus și ipotezele eliminate. Nu repeta bucle de încercări.
Nu șterge lucrul altuia și nu reseta checkout-uri dirty. Lucrează pe o ramură izolată.
Commit/push/draft PR sunt autorizate în mandatul curent; merge/deploy nu sunt.

Formatul rezultatului:

```json
{
  "task_id": "SM-XXX",
  "base_sha": "actual",
  "head_sha": "actual-or-uncommitted",
  "changed_files": [],
  "acceptance": [{"case": "exact test name", "status": "passed|failed|not_run", "evidence": "command + exit + artifact"}],
  "remaining": [],
  "ready_for_review": false
}
```

Completează valorile reale; exemplul nu este o dovadă de execuție.
