# Review Antigravity — 14 noiembrie 2026

Verificare read-only a PR-urilor #1365–#1368 și a checkpointului Lot5. Snapshotul exact și linkurile CI sunt în github-snapshot.json. Main rămâne 1338833d; toate cele patru PR-uri sunt draft, neintegrate. Nu au fost modificate branchuri, surse sau setări remote.

## Progres confirmat

- #1365 e39d9b6: reconciliază cumulativul V70 cu corecțiile V81; diferența față de d930e77 păstrează sursa cumulativă și adaugă corecții CLI, transcript, Chrome/Windows și fixtures. CI nu raportează cazuri FAILED; eșuează verificarea contorului: executate36700, înregistrate36699.
- #1366 155c915: preseturi multi-model concurente/quorum, integrare CLI/API/HUD; ancorare Python macOS TCC; interfețe OAuth, subagenți, A2A, MCP, jobs și receipts.
- #1367 d454227: sincronizare criptată config/skills, broker browser pe identitate, replicare/promovare camere și pets/companion procedural.
- #1368 ffbfce8: gestiune provider packages și Kanban prin panouri reale, skin-uri CLI, delegare, scrubber de context, scanner comenzi, migrare Codex și harness benchmark.

Panourile inspectate au formulare și apelanți reali. Reducerea rutelor fără interfață54→9 nu dovedește că toți adaptorii sau providerii funcționează live.

## Stare și constatări

Registrul autorului declară187 equivalent/474partial/0missing/36excluded din697, față de171/482/8/36 la handoverul cumulativ. Aceasta nu este certificare independentă: reviewul constată defecte în capabilități promovate equivalent. Zero missing nu înseamnă obiectiv complet.

Toate patru CI principale sunt roșii. Ultimul #1368 are23 intrări FAILED pentru cazuri pytest; exemple: compatibilitate callback streaming, CLI --help fără site-packages (import yaml), arhive pets în afara archive_safe, inventare bindings/env/capabilities. Security eșuează la Bandit și Gitleaks; cele3 șiruri Gitleaks sunt explicit sintetice în benchmark, deci nu este confirmată o scurgere de credențiale reale. Unele joburi sunt skipped conform condițiilor workflowului, nu trebuie numărate drept passed.

### Prioritate: H040 sincronizare

1. Constructorul normal nu reîncarcă fișierul implicit de stare. Am reprodus local numai metadatele într-un director temporar, fără rețea sau restart de servicii: după reinstanțiere,1peer devine0 și un skill exclus de la sync devine din nou permis. Când state_path este explicit, ambele valori se păstrează. Dovada: sync-reproduction.json. Acest test explică de ce testele autorului cu state_path explicit ratează problema.
2. Directorul implicit synced_skills nu este printre directoarele descoperite de skill loader; descărcarea unui skill nu îl face automat utilizabil.
3. La headul lot4, pull reaplică snapshoturi vechi fără cursor/revizie și poate suprascrie editări locale noi. Există o remediere propusă LWW pe branchul lot5-bench, încă neintegrată și nereverificată aici.

Referințe exacte și cod: core-review.md.

### Limitele produsului și benchmarkurilor

- H657 oferă primitivi manuali de failover; testul autorului permite încă scriere pe vechiul owner după promovare, până la demotarea explicită.
- MoA face gather după toți proposerii; nu începe imediat agregarea la atingerea quorumului, iar încărcarea modelului nu este încadrată de timeoutul generate.
- Opțiunea local-vlm din generatorul de pets folosește același generator procedural; culoarea imaginii este derivată din hash, nu extrasă din pixeli.
- Benchmarkurile rulează Nerva cu backenduri simulate și baselineuri sintetice. Nu execută Hermes/OpenClaw; unele rate de baseline sunt constante. Nu demonstrează superioritatea față de produse reale.

Referințe exacte: ui-review.md. Aceste constatări provin din citirea codului și probelor, nu dintr-o suită locală completă sau acceptare live.

## Lot5 și următorul pas

Checkpointul587977b consemnează pauză cerută de owner după limita de cotă. Patru branchuri de backup: Kanban cu teste raportate; benchmark/LWW și cost cascade cu review în așteptare (cascade neconectată la router); hermes-core și hermes-gw explicit WIP netestat. Nu există PR Lot5 în snapshotul verificat.

Prioritatea tehnică este stabilizarea bazei cumulative și închiderea regresiilor CI, remedierea sincronizării și revizuirea verdictelor equivalent afectate. Apoi pot fi integrate loturile neterminate și efectuate acceptanțele cross-platform/provider. Nu am reluat dezvoltarea pusă pe pauză.
