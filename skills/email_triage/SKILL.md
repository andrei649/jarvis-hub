# Email Triage

> Pepper's email triage — citește etichete Gmail, prioritizează, sugerează acțiuni

**Version:** 0.1.0
**Author:** claude
**Agents:** pepper
**Requires:** gmail_plugin

## Usage
Scanează inbox-ul Gmail pentru mesaje necitite, le prioritizează după:
- expeditori VIP (personal, family, direct reports)
- cuvinte-cheie urgente (urgent, deadline, ASAP, critical)
- recență (ultimele 24h vs. mai vechi)

Returnează o listă priorizată în română cu marcatori de prioritate și
sugestii de acțiune. Se degradează grațios dacă Gmail nu e disponibil.

## Commands
- `triage [query]` — rezumat priorizat al inbox-ului, opțional filtrat după query
