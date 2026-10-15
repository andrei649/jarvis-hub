# Nerva Business: instalare și utilizare

Nerva Business oferă un spațiu pentru profilul companiei, surse de date, rapoarte și întrebări despre indicatorii salvați. Este o funcție opțională în HUD-ul Nerva. **Fiecare instalare și fiecare `JARVIS_HOME` deservesc o singură companie.** Utilizatorii autentificați ai acelei instalări văd aceleași date Business; pilotul nu are permisiuni separate pe departamente. Instalează Nerva separat, cu un director de date diferit, pentru fiecare client.

## Pornire

Pentru reluarea dezvoltării sau instalarea acestei ramuri pe Mac, vezi
[handover-ul curent](BUSINESS_HANDOVER.md), inclusiv commiturile și verificările.

Pentru Docker, folosește fișierul Business peste quickstart-ul existent, din rădăcina proiectului:

```bash
docker compose -f docker-compose.quickstart.yml -f docker-compose.business.yml up --build
```

Pe Mac, această comandă cere Docker Desktop 4.34+ cu **Settings → Resources →
Network → Enable host networking** activat. Poți folosi și instalarea nativă
din handover; verificarea din această sesiune a fost făcută pe Linux, nu pe macOS.

Pe Linux și NAS compatibil cu Docker host networking, această variantă păstrează datele în volumul persistent quickstart (`JARVIS_HOME=/data`) și activează Business prin `NERVA_BUSINESS_ENABLED=1`. Deschide `http://127.0.0.1:8080/v2`, apoi **Console → Business**. Quickstart-ul ascultă numai pe adresa locală; accesul de pe alt dispozitiv necesită configurarea separată a autentificării și a rețelei, descrisă în [PHONE_ACCESS.md](PHONE_ACCESS.md).

Dacă pornești Nerva fără Docker, setează `NERVA_BUSINESS_ENABLED=1` în mediul procesului înainte de pornire și alege un `JARVIS_HOME` persistent, dedicat companiei. [INSTALL.md](INSTALL.md) descrie instalarea generală. Când funcția este dezactivată, spațiul afișează starea, iar modificările Business sunt refuzate.

## Primii pași

Pentru o probă de zece minute fără conturi externe, urmează
[scenariul de test](BUSINESS_TEST.md). În ecran apar pașii de pornire și trei
butoane cu exemple sintetice. Alegerea unui exemplu completează formularul;
datele sunt salvate numai după apăsarea butonului **Importă CSV**.

1. În **Profilul companiei**, introdu numele, alege modelul de domeniu (*Comerț online*, *Auto* sau *Servicii*) și codul monedei de trei litere, de exemplu `RON`. Modelul organizează spațiul; nu încarcă automat date. Salvează profilul cu acces de administrator.
2. Adaugă o sursă. Poți importa un CSV local sau salva o conexiune WooCommerce/HubSpot. Conexiunea salvată este inițial **Neconfirmat**; apasă **Sincronizează** pentru a verifica accesul și a prelua date. Sincronizarea este manuală.
3. Rulează raportul potrivit tipului de date și citește **Acoperire** și **De verificat** înainte de a folosi indicatorii. Rapoartele se păstrează cu data generării; o sursă nesincronizată nu produce cifre inventate.
4. În **Întreabă Nerva**, formulează o întrebare precum „Ce valoare au comenzile completed/processing din datele sincronizate?”. Răspunsul folosește indicatori recalculați din instantaneele curente, împreună cu sursele, datele sincronizării și avertismentele. Nu interoghează în direct magazinul sau CRM-ul.

Profilul, conectarea, sincronizarea, importul și eliminarea surselor cer acces de administrator. Utilizatorii autentificați pot citi spațiul, rula și consulta rapoarte și pune întrebări. Datele și istoricul Business sunt păstrate sub `JARVIS_HOME/business`; credențialele conexiunilor sunt păstrate criptat și nu sunt returnate în ecranul surselor. Fă backup directorului de date conform politicii tale de operare.

## Surse de date

**CSV.** Alege tipul *Comenzi*, *Produse* sau *Oportunități*, dă un nume sursei și încarcă un fișier ori lipește conținutul. Fișierele [orders.csv](../examples/business/orders.csv), [products.csv](../examples/business/products.csv) și [deals.csv](../examples/business/deals.csv) conțin **date sintetice** pentru o probă manuală. Nu sunt importate automat. Importul cu același nume de sursă CSV înlocuiește explicit instantaneul acelei surse. Limita este 1 MB și 500 de rânduri; separatorul este virgula, iar fiecare rând trebuie să aibă un `id` distinct. Sumele folosesc punct zecimal și cod de monedă de trei litere.

| Tip | Coloane obligatorii | Alte coloane folosite |
| --- | --- | --- |
| Comenzi | `id,status,total,currency` | `created_at` |
| Produse | `id,name,stock_quantity` | — |
| Oportunități | `id,name,amount,currency,stage` | — |

Un `stock_quantity` gol înseamnă stoc necunoscut; o valoare negativă indică lipsă de stoc. Comenzile cu status `completed` sau `processing` intră în indicatorul de comenzi incluse; celelalte sunt excluse. Exemplul de comenzi include intenționat o comandă anulată pentru a face această diferență vizibilă.

**WooCommerce.** Introdu adresa publică HTTPS a magazinului și perechea de chei API `consumer_key` / `consumer_secret` cu acces de citire la comenzi și produse. Nerva citește cel mult 500 de comenzi și 500 de produse la o sincronizare. Nu trimite comenzi și nu modifică stocul. Dacă sursa are mai multe înregistrări, raportul marchează acoperirea parțială.

**HubSpot.** Folosește tokenul de acces al aplicației private, cu permisiune de citire a oportunităților. Conectorul accesează exclusiv `https://api.hubapi.com` și citește cel mult 500 de oportunități la o sincronizare. Dacă HubSpot nu furnizează moneda, raportul o marchează `XXX`; nu o înlocuiește cu moneda profilului.

Conexiunile externe nu fac cereri la simpla deschidere a paginii. Dacă o resincronizare eșuează după un instantaneu anterior, Nerva păstrează datele anterioare și indică starea **Date învechite**. Verifică data ultimei sincronizări și avertismentele raportului. Ștergerea unei surse elimină conexiunea și instantaneul aferent; rapoartele deja salvate rămân rezultate istorice.

## Rapoarte și întrebări

Poți selecta **o singură sursă** înainte de a genera raportul. Folosește această
opțiune când același magazin apare atât prin conector, cât și într-un CSV.
Opțiunea **Toate sursele** cumulează sursele relevante fără deduplicare.

Raportul de vânzări acceptă date de început și sfârșit în format `YYYY-MM-DD`,
incluse la ambele capete, în calendarul **UTC**. Filtrarea folosește data creării
comenzii din instantaneul disponibil; nu descarcă alte comenzi de la furnizor.
Datele cu fus orar sunt convertite în UTC. Cele fără fus orar sunt tratate ca UTC,
cu avertisment. Comenzile fără dată sau cu dată invalidă sunt excluse din raportul
filtrat și numărate separat. WooCommerce folosește prioritar `date_created_gmt`.
Stocurile și oportunitățile folosesc numai selecția sursei, fără filtru de dată.

- **Vânzări** însumează comenzile `completed`/`processing` separat pe monedă. Sumele includ valorile totale din sursă, nu reprezintă profit și nu reconciliază rambursările parțiale.
- **Stocuri** indică produsele cu maximum 3 unități, inclusiv valori negative, și numără separat stocurile necunoscute. Variațiile WooCommerce nu sunt importate separat.
- **Oportunități** grupează etapele din CRM și păstrează sumele separate pe monedă. Valoarea oportunităților nu este venit realizat.

Rapoartele arată sursele, data instantaneului, caracterul complet/parțial și avertismentele. Cu mai multe surse, Nerva nu deduplică automat înregistrările comune; evită importuri care se suprapun cu o conexiune. Datele remote sunt instantanee limitate, fără filtru de perioadă. Tabelul unui raport afișează cel mult 100 de rânduri, deși indicatorii folosesc înregistrările disponibile în instantanee.

**Descărcarea raportului** păstrează rezultatul salvat. JSON conține indicatorii,
filtrele, acoperirea, avertismentele și rândurile salvate. CSV include metadatele,
indicatorii și cel mult cele 100 de rânduri vizibile; nu este un export integral
al magazinului. Celulele care ar putea fi interpretate drept formule sunt
neutralizate. Raportul istoric rămâne neschimbat după o resincronizare.

În **Domeniul întrebării**, alege **Raportul salvat selectat** pentru a discuta
exact indicatorii și perioada acelui rezultat istoric. **Toate datele curente**
recalculează indicatorii din instantaneele existente. Un raport expirat din
istoricul limitat este refuzat explicit; întrebarea nu trece automat la alte date.

La import, erorile indică rândul și câmpul problematic, fără a repeta valoarea
celulei. Un răspuns HTTP 401 la sincronizare cere verificarea cheii/tokenului;
403 indică permisiunile de citire, iar 429 cere o nouă încercare mai târziu.

Întrebările folosesc routerul de modele deja configurat în Nerva. Opțiunea **Folosește doar modele AI locale** este activă implicit; dacă nu există un model local disponibil sau politica de date refuză ruta, întrebarea primește o eroare explicită. Dezactivarea opțiunii în profil permite încercarea rutei configurate, dar nu acordă prin ea însăși permisiune cloud: politica generală a Nerva rămâne în vigoare. Poți verifica modelul și ruta folosite lângă fiecare răspuns.

Această livrare nu a fost validată cu conturi WooCommerce/HubSpot reale sau cu un DGX. Exemplele CSV sunt o cale de verificare locală a importului și rapoartelor, fără a afirma că un conector extern funcționează în contul tău.

Importul repetat cu același nume trebuie să păstreze tipul sursei; un import de
produse peste o sursă de comenzi este refuzat. În HubSpot, o sumă absentă rămâne
necunoscută și este exclusă din totaluri, cu avertisment în raport.

Un abonament ChatGPT nu finanțează apelurile API ale aplicației. Pentru cloud,
configurează separat furnizorul API și politica agentului `stark` în Console;
plafonul contractual de consum și facturarea nu sunt implementate în acest pilot.
Modul local cere un endpoint verificat pe loopback: pentru un model pe alt host
din VPN este necesar un gateway/tunel local configurat și validat separat.
Limita de trei cereri AI simultane este per proces Nerva și nu reprezintă un
benchmark de capacitate hardware. Folosește un singur worker pentru pilot.
