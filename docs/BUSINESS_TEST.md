# Probă de zece minute pentru Nerva Business

Pornește aplicația după [ghidul de instalare](BUSINESS.md) și deschide
`/v2/console/business`. La prima deschidere, închide panoul general de pornire
cu **continue to cockpit**. Pentru exemple și rapoarte nu ai nevoie de conturi
WooCommerce/HubSpot sau de un model AI.

1. Salvează compania `Magazin de probă`, domeniul **Comerț online**, moneda **RON**.
2. În zona CSV, alege exemplul sintetic de **comenzi**. Verifică formularul, apoi
   apasă **Importă CSV**. Datele sunt demonstrative și nu provin de la clienți.
3. Rulează **Vânzări**, fără filtru de perioadă. Rezultatul așteptat este **339,40
   RON**, cu **2 comenzi incluse** și **1 comandă anulată exclusă**. Statusul
   comenzii nu confirmă încasarea bancară.
4. Alege numai sursa exemplului de comenzi. Completează ambele date cu
   `2026-10-01` și rulează din nou **Vânzări**. Rezultatul așteptat este **249,90
   RON**, pentru o singură comandă. Verifică perioada salvată în raport.
5. Descarcă raportul în **JSON** și **CSV**. Compară suma, sursa și avertismentele
   cu ecranul. CSV conține metadate înaintea tabelului; în Excel este posibil să
   fie necesar importul explicit cu separator virgulă și codificare UTF-8.
6. Încarcă și importă exemplul sintetic de **produse**. Alege sursa lui și rulează
   **Stocuri**. Verifică diferența dintre stoc redus și stoc necunoscut.
7. Opțional, importă exemplul de **oportunități** și rulează raportul aferent.
   Monedele rămân separate; valoarea oportunităților nu reprezintă venit realizat.
8. Reîncarcă pagina. Profilul, sursele și rapoartele trebuie să rămână disponibile.
9. Dacă ai un model configurat, selectează raportul de vânzări filtrat și alege
   **Raportul salvat selectat** în zona întrebărilor. Întreabă „Ce valoare au
   comenzile din acest raport și ce limite au datele?”. Fără model configurat,
   aplicația trebuie să explice indisponibilitatea; nu să inventeze un răspuns.

Pentru proba cu magazinul real, adaugă separat conexiunea cu chei de citire și
apasă **Sincronizează**. Generează raportul numai pentru sursa reală. Exemplele
sintetice pot fi eliminate din lista surselor; rapoartele deja salvate rămân
istorice. Nu combina exemplele cu datele reale în interpretarea cifrelor.

Notează ce ai vrut să afli, sursa/perioada selectată, rezultatul observat și
rezultatul așteptat. Nu include chei API sau date personale în capturi de eroare.
Acest scenariu verifică interfața și calculele; nu validează automat conturile
furnizorilor, performanța modelului ori capacitatea DGX.
