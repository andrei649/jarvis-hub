# Dev Methodology — Superpowers-inspired (jarvis-hub)

> Sursă: github.com/obra/superpowers (plugin de metodologie pentru agenți).
> Pluginul în sine se instalează în Claude Code (vezi mai jos), NU în acest repo.
> Acest fișier adoptă PRINCIPIILE lui ca reguli de lucru pentru Claude + opencode,
> complementar lui PARALLEL_WORKFLOW.md (ownership: opencode — nu-l editez).

## Cum instalezi pluginul în Claude Code (Andrei rulează)

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```
După instalare, workflow-urile se activează automat înainte de task-uri relevante.

---

## Principiile adoptate (le respect chiar și fără plugin instalat)

### 1. Brainstorm înainte de cod
Pentru orice task ne-trivial: clarific cerința prin întrebări, propun alternative,
prezint designul pe secțiuni pentru validare — ÎNAINTE de a scrie cod.
(Deja fac asta prin `AskUserQuestion` la decizii de arhitectură.)

### 2. Plan scris, în pași mici
Sparg munca în task-uri de 2-5 minute. Fiecare task are: cale de fișier exactă,
ce se schimbă, pas de verificare. Plan-urile trăiesc în `.opencode/plans/`.

### 3. TDD: RED → GREEN → REFACTOR
- Scriu testul întâi, îl văd PICÂND (red)
- Scriu codul minim cât să treacă (green)
- Curăț, păstrând testele verzi (refactor)
- Commit după fiecare ciclu
(Notă: testele router-HTTP din sesiunile trecute treceau FALS pe dummy —
exact ce previne disciplina „watch it fail": un test care nu pică întâi nu dovedește nimic.)

### 4. Subagent-driven, cu review în 2 etape
Pentru task-uri paralele/independente: dispatch subagent per task, apoi review
în două straturi — (a) conformitate cu spec-ul, (b) calitatea codului.

### 5. Git worktrees pentru paralelism
Lucru izolat pe branch/worktree propriu → zero coliziuni. Se leagă direct de
PARALLEL_WORKFLOW.md (locks + ownership Claude/opencode).

### 6. Commit mic + push după fiecare unitate
Niciodată „big bang" la final. Fiecare skill/fix = commit+push imediat, ca munca
să nu se piardă dacă sesiunea se termină. (Regulă deja activă.)

### 7. Finalizare branch
Înainte de merge: rulez TOATE testele, raportez pe severitate, prezint opțiunile
(merge/PR) — nu fac merge cu teste roșii.

---

## Checklist de început de sesiune (Claude)
1. `git pull --rebase origin master` — sync cu opencode
2. `python lock.py status` — văd ce e blocat
3. `python lock.py check <cale>` înainte de a edita orice
4. Lucrez în pattern loader (`skills/<name>/`), nu router HTTP
5. Commit + push după fiecare unitate; eliberez lock-urile la final
