/*
 * Qui-Cam – configurazione
 */
window.CAM_CONFIG = {
  // Versione dell'app, mostrata in fondo alla pagina Elenco. Aumentala a ogni aggiornamento
  // (insieme al nome della cache in sw.js e ai ?v= in index.html).
  versione: "4",

  // Senza percorso: telecamere entro questo raggio (metri) dalla tua posizione
  raggioMetri: 25000,

  // Con un percorso: una telecamera conta se è entro questi metri dalla strada calcolata
  sogliaPercorsoMetri: 400,

  // Ogni quanti secondi ricaricare le immagini (0 = mai). Si cambia anche dalla pagina Elenco.
  autoRefreshSecondi: 60,

  // Calcolo del percorso (OSRM, dati OpenStreetMap). Si prova il primo, poi il secondo.
  serverPercorso: [
    "https://router.project-osrm.org/route/v1/driving/",
    "https://routing.openstreetmap.de/routed-car/route/v1/driving/"
  ]
};
