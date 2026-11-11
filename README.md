# Qui-Cam

Web app per il telefono che mostra in tempo reale le webcam delle autostrade italiane.
Scrivi **da dove parti** e **dove vai**: l'app calcola il percorso e mostra, in ordine, le telecamere
che incontrerai lungo la strada, con l'immagine dal vivo, il video delle ultime riprese, i chilometri
e il tempo che mancano. Senza percorso mostra le telecamere intorno a te.
Stesso aspetto e funzionamento di Qui-Distributori.

## Come funziona

- Ogni 6 ore GitHub esegue `aggiorna_telecamere.py` (workflow `.github/workflows/pubblica.yml`):
  scarica l'elenco delle telecamere di Autostrade per l'Italia e dell'A22 Brennero e lo salva in
  `dati/telecamere.json` nel sito pubblicato, con l'elenco delle strade coperte.
- La cartella `dati/` **non** sta nel repository: viene creata a ogni pubblicazione.
  Se una fonte non risponde, lo script tiene le telecamere già pubblicate di quella fonte.
- Le **immagini non vengono copiate**: l'app le carica direttamente dai siti dei gestori,
  quindi sono sempre quelle del momento.
- Il percorso si calcola nel telefono con OSRM (dati OpenStreetMap); gli indirizzi si cercano con Nominatim.
  Una telecamera fa parte del percorso se sta entro 400 m dalla strada calcolata (si cambia nell'app).
- Link diretto a un percorso: `…/Cam/?da=Varese&a=Bologna` (senza `da` parte dalla posizione del telefono).

## Pubblicazione

Impostazioni del repository → Pages → Source: **GitHub Actions**.
Per aggiornare subito l'elenco: Actions → *Pubblica sito e aggiorna telecamere* → *Run workflow*.
Nel registro del workflow trovi l'elenco delle strade con quante telecamere ha ciascuna.

## File

- `index.html`, `style.css`: interfaccia
- `core.js`: logica (distanze, telecamere vicine, telecamere lungo il percorso)
- `app.js`: mappa, GPS, percorso, immagini, elenco
- `config.js`: impostazioni iniziali e numero di versione
- `aggiorna_telecamere.py`, `.github/workflows/pubblica.yml`: elenco telecamere e pubblicazione
- `test_core.js`: prove della logica (`node test_core.js`)
- `sw.js`, `manifest.webmanifest`, icone PNG: installazione come app

## Fonti

Immagini e video: Autostrade per l'Italia e Autostrada del Brennero, mostrati dai loro siti.
Mappa, ricerca indirizzi e percorsi: © OpenStreetMap e chi contribuisce (ODbL), OSRM.
