#!/usr/bin/env python3
"""
Qui-Cam – controlla le autostrade che non hanno ancora telecamere nell'app e scrive dati/mancanti.json.

Per ogni gestore:
  * se conosciamo un indirizzo delle sue webcam, lo si prova: "risponde" oppure "non risponde"
    (con il motivo: tempo scaduto, accesso negato, errore del server...);
  * se non lo conosciamo, si guarda la home page del sito cercando collegamenti a pagine webcam:
    "nessun link" se non ce ne sono, "link trovato" se compare qualcosa da esaminare.

Gira a ogni aggiornamento del sito (workflow "Pubblica"): quando un gestore pubblica le webcam o il
suo sito torna raggiungibile, lo si vede nella guida dell'app e nel registro del workflow.
"""
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
FILE = os.path.join("dati", "mancanti.json")

# link: indirizzi noti delle webcam (anche vecchi), sito: home page in cui cercare nuovi collegamenti
GESTORI = [
    {"strade": ["A2", "A19", "A29", "A90"], "nomi": "A2 Salerno-Reggio Calabria, A19 Palermo-Catania, A29 Palermo-Mazara, A90 GRA di Roma",
     "gestore": "ANAS",
     "link": ["https://www.stradeanas.it/it/webcam", "https://www.stradeanas.it/it/le-strade/webcam"],
     "sito": "https://www.stradeanas.it/"},
    {"strade": ["A24", "A25"], "nomi": "A24 Roma-L'Aquila-Teramo, A25 Torano-Pescara",
     "gestore": "ANAS (ex Strada dei Parchi)",
     "link": ["https://www.stradadeiparchi.it/traffico/webcam/", "https://www.stradeanas.it/it/webcam"],
     "sito": "https://www.stradadeiparchi.it/"},
    {"strade": ["A18", "A20"], "nomi": "A18 Messina-Catania e Siracusa-Gela, A20 Messina-Palermo",
     "gestore": "Consorzio Autostrade Siciliane",
     "link": [], "sito": "https://www.autostradesiciliane.it/"},
    {"strade": ["A36"], "nomi": "A36 Pedemontana Lombarda",
     "gestore": "Autostrada Pedemontana Lombarda",
     "link": [], "sito": "https://www.pedemontana.com/it"},
    {"strade": ["A35"], "nomi": "A35 Brebemi",
     "gestore": "Brebemi",
     "link": ["https://www.brebemi.it/wp-json/mappa/v1/webcams"], "sito": "https://www.brebemi.it/"},
]

WEBCAM_LINK = re.compile(r"""href=["']([^"'#]*(?:webcam|telecamer)[^"']*)["']""", re.I)


def prova(url):
    """→ (ok, testo, motivo, indirizzo finale)"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "it-IT,it;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return True, r.read(3_000_000).decode("utf-8", "replace"), f"HTTP {r.status}", r.geturl()
    except urllib.error.HTTPError as e:
        motivi = {403: "accesso negato (403)", 404: "pagina non trovata (404)", 503: "servizio non disponibile (503)"}
        return False, "", motivi.get(e.code, f"errore HTTP {e.code}"), url
    except (socket.timeout, TimeoutError):
        return False, "", "tempo scaduto, il sito non risponde", url
    except urllib.error.URLError as e:
        r = str(e.reason)
        if "timed out" in r:
            return False, "", "tempo scaduto, il sito non risponde", url
        if "Name or service" in r or "resolution" in r:
            return False, "", "indirizzo inesistente", url
        return False, "", "connessione non riuscita", url
    except Exception as e:
        return False, "", f"errore: {type(e).__name__}", url


def percorso(u):
    """'https://www.sito.it/traffico/webcam/' e '/traffico/webcam' → 'traffico/webcam'"""
    return urllib.parse.urlsplit(u).path.strip("/").lower()


def conta_webcam(testo):
    try:
        d = json.loads(testo)
        if isinstance(d, list):
            return len(d)
    except ValueError:
        pass
    # immagini e video, esclusi quelli del tema del sito (logo, intestazione, sfondi, icone)
    trovati = set(re.findall(r"[\w/.:%-]+\.(?:jpe?g|mp4|m3u8)", testo, re.I))
    return len([u for u in trovati if not re.search(r"(?i)/themes/|logo|header|sfondo|background|icon|banner", u)])


def controlla(g):
    esito = {"strade": g["strade"], "nomi": g["nomi"], "gestore": g["gestore"], "prove": []}
    noti = {percorso(u) for u in g["link"]}
    for url in g["link"]:
        ok, testo, motivo, finale = prova(url)
        noti.add(percorso(finale))
        n = conta_webcam(testo) if ok else 0
        esito["prove"].append({"url": url, "ok": ok, "motivo": motivo, "n": n})
        if ok and n:
            esito.update(stato="risponde", link=url,
                         dettaglio=f"il link risponde ({n} immagini o video): si può aggiungere all'app")
            return esito
    # nessun link funzionante: si guarda il sito
    ok, testo, motivo, _ = prova(g["sito"])
    trovati = sorted({u for u in WEBCAM_LINK.findall(testo)})[:5] if ok else []
    esito["sito"] = {"url": g["sito"], "ok": ok, "motivo": motivo, "link_webcam": trovati}
    nuovi = [u for u in trovati if percorso(u) not in noti]
    if nuovi:
        esito.update(stato="link trovato", link=nuovi[0],
                     dettaglio="sul sito compare un collegamento a webcam da esaminare")
    elif g["link"]:
        parti = [f"{urllib.parse.urlsplit(p['url']).hostname.removeprefix('www.')}: "
                 + (p["motivo"] if not p["ok"] else "la pagina delle webcam è vuota") for p in esito["prove"]]
        esito.update(stato="non risponde", link=g["link"][0], dettaglio="abbiamo il link ma " + "; ".join(dict.fromkeys(parti)))
    else:
        esito.update(stato="nessun link", link=None,
                     dettaglio="nessuna webcam pubblicata sul sito" if ok else f"nessun link e il sito non risponde ({motivo})")
    return esito


def main():
    with ThreadPoolExecutor(max_workers=len(GESTORI)) as ex:
        esiti = list(ex.map(controlla, GESTORI))
    os.makedirs("dati", exist_ok=True)
    adesso = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%dT%H:%M")
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump({"controllato": adesso, "gestori": esiti}, f, ensure_ascii=False, indent=1)
    print(f"Strade senza telecamere (controllo del {adesso}):")
    for e in esiti:
        print(f"  {', '.join(e['strade']):<16} {e['gestore']:<34} {e['stato'].upper():<13} {e['dettaglio']}")
        for p in e["prove"]:
            print(f"      {p['url']} → {p['motivo']}" + (f", {p['n']} elementi" if p["ok"] else ""))
        if e.get("sito"):
            s = e["sito"]
            print(f"      sito {s['url']} → {s['motivo']}" + (f", link webcam: {s['link_webcam']}" if s["link_webcam"] else ""))


if __name__ == "__main__":
    main()
