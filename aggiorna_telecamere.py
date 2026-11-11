#!/usr/bin/env python3
"""
Qui-Cam – scarica l'elenco delle webcam autostradali e lo salva in dati/telecamere.json.

Fonti (le stesse che usano le mappe del traffico ufficiali):
  * Autostrade per l'Italia: https://viabilita.autostrade.it/json/webcams.json
    (circa 1000 telecamere; ogni telecamera è un breve video MP4 che viene rifatto ogni pochi minuti
    allo stesso indirizzo, più un fotogramma JPG)
  * Autostrada del Brennero (A22): l'elenco è dentro la pagina https://www.autobrennero.it/it/
    (variabile JavaScript "puntiWebcam"), con un'immagine JPG per telecamera.

Le immagini NON vengono copiate: l'app le carica direttamente dai siti dei gestori, così sono
sempre quelle del momento. Qui si salva solo l'elenco (posizione, nome, indirizzi di immagine e video).

Se una fonte non risponde si tengono le telecamere di quella fonte già pubblicate sul sito (variabile
d'ambiente SITO), così l'app non resta mai vuota.
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CARTELLA = "dati"
FILE = os.path.join(CARTELLA, "telecamere.json")
SITO = os.environ.get("SITO", "").rstrip("/") + "/" if os.environ.get("SITO") else ""
ROMA = ZoneInfo("Europe/Rome")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

ASPI_ELENCO = "https://viabilita.autostrade.it/json/webcams.json"
ASPI_VIDEO = "https://video.autostrade.it/video-mp4_hq/"
ASPI_FOTO = "https://video.autostrade.it/video-frames/"
# "dt4/fdb2dcf0-d228-491f-948b-032d4a12a14e-23.mp4"
ASPI_CLIP = re.compile(r"^[a-z0-9]{2,8}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-\d{1,4}\.mp4$")
# Una telecamera che non rifà il video da più di questo tempo è spenta
ASPI_ORE_MAX = 24

A22_PAGINA = "https://www.autobrennero.it/it/"
A22_INIZIO, A22_FINE = "var puntiWebcam=", ";var puntiBarriere"


def scarica(url, referer=None, tentativi=3, timeout=40):
    testa = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
             "Accept-Language": "it-IT,it;q=0.9"}
    if referer:
        testa["Referer"] = referer
    errore = None
    for n in range(tentativi):
        try:
            req = urllib.request.Request(url, headers=testa)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # rete, HTTP, timeout
            errore = e
            print(f"  tentativo {n + 1} fallito per {url}: {e}")
            time.sleep(3 * (n + 1))
    raise errore


def in_italia(lat, lon):
    return 35.4 < lat < 47.2 and 6.5 < lon < 18.6


def pulisci(s):
    if not isinstance(s, str):
        return ""
    s = re.sub(r"[︀-️]", "", s)  # selettori di variante emoji in alcuni nomi
    return re.sub(r"\s+", " ", s).strip()


def numero(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def direzione_da_testo(t):
    """'... itinere nord' → 'nord'. Restituisce '' se non c'è."""
    m = re.search(r"\b(?:itinere|direzione|dir\.?|verso)\s+([A-Za-zÀ-ÿ' ]{2,30})$", t, re.I)
    return pulisci(m.group(1)).lower() if m else ""


# ---------- Autostrade per l'Italia ----------
def eta_clip(giorno, ora):
    """'09-10-2026' + '05:40' (ora italiana) → ore trascorse, oppure None."""
    try:
        d = datetime.strptime(f"{giorno} {ora}", "%d-%m-%Y %H:%M").replace(tzinfo=ROMA)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - d).total_seconds() / 3600


def foto_aspi(cam, clip):
    """Indirizzo del fotogramma JPG: se l'elenco lo dà si usa quello, altrimenti si ricava dal video."""
    for k, v in (cam.get("frames") or {}).items():
        if k == "V" or not isinstance(v, dict):
            continue
        u = v.get("t_url")
        if isinstance(u, str) and re.search(r"\.(jpe?g|png)$", u, re.I):
            return u if u.startswith("http") else ASPI_FOTO + u.lstrip("/")
    return ASPI_FOTO + clip[:-4] + "-3.jpg"


def leggi_aspi():
    dati = json.loads(scarica(ASPI_ELENCO, referer="https://viabilita.autostrade.it/"))
    lista = dati.get("webcams") if isinstance(dati, dict) else None
    if not isinstance(lista, list):
        raise ValueError("risposta senza 'webcams'")
    out, scartate = [], {"senza video": 0, "fuori posto": 0, "spente": 0}
    for c in lista:
        clip = ((c.get("frames") or {}).get("V") or {}).get("t_url")
        if not isinstance(clip, str) or not ASPI_CLIP.match(clip):
            scartate["senza video"] += 1
            continue
        lat, lon = numero(c.get("n_crd_lat")), numero(c.get("n_crd_lon"))
        if lat is None or lon is None or not in_italia(lat, lon):
            scartate["fuori posto"] += 1
            continue
        eta = eta_clip(c.get("t_day"), c.get("t_time"))
        if eta is not None and eta > ASPI_ORE_MAX:
            scartate["spente"] += 1
            continue
        strada = pulisci(c.get("c_str")) or pulisci(c.get("t_des_str")).split(" ")[0]
        nome_strada = pulisci(c.get("t_des_str"))
        des = pulisci(c.get("t_des"))
        km = numero(c.get("n_prg_km"))
        out.append({
            "id": "aspi-" + str(c.get("c_tel")),
            "la": round(lat, 5), "lo": round(lon, 5),
            "s": strada, "sn": nome_strada,
            "n": des or nome_strada or strada,
            "km": round(km, 1) if km is not None else None,
            "dir": direzione_da_testo(des),
            "img": foto_aspi(c, clip),
            "vid": ASPI_VIDEO + clip,
            "f": "aspi"
        })
    print(f"Autostrade per l'Italia: {len(out)} telecamere (scartate: {scartate})")
    if len(out) < 100:
        raise ValueError(f"troppo poche telecamere ({len(out)})")
    return out


# ---------- A22 Autostrada del Brennero ----------
def leggi_a22():
    html = scarica(A22_PAGINA).decode("utf-8", "replace")
    i, j = html.find(A22_INIZIO), html.find(A22_FINE)
    if i < 0 or j < 0:
        raise ValueError("elenco webcam non trovato nella pagina")
    dati = json.loads(html[i + len(A22_INIZIO):j].strip())
    gruppi = dati.values() if isinstance(dati, dict) else [dati]
    out = []
    for gruppo in gruppi:
        for c in gruppo if isinstance(gruppo, list) else []:
            lat, lon = numero(c.get("Lat")), numero(c.get("Lng"))
            img = c.get("Immagine") or ""
            if lat is None or lon is None or not in_italia(lat, lon) or not img:
                continue
            if img.startswith("//"):
                img = "https:" + img
            elif img.startswith("/"):
                img = "https://www.autobrennero.it" + img
            des = pulisci(c.get("Descrizione"))
            km = numero(c.get("Distanza"))
            d = des.lower()
            out.append({
                "id": "a22-" + str(c.get("ID")),
                "la": round(lat, 5), "lo": round(lon, 5),
                "s": "A22", "sn": "A22 Autostrada del Brennero",
                "n": des or "A22",
                "km": round(km, 1) if km is not None else None,
                "dir": "modena" if "modena" in d else "brennero" if "brennero" in d else "",
                "img": img, "vid": None, "f": "a22"
            })
    print(f"A22 Brennero: {len(out)} telecamere")
    if not out:
        raise ValueError("nessuna telecamera")
    return out


def pubblicate():
    """Telecamere già pubblicate sul sito, per non perderle se una fonte non risponde."""
    if not SITO:
        return []
    try:
        return json.loads(scarica(SITO + FILE.replace(os.sep, "/"), tentativi=2)).get("t", [])
    except Exception as e:
        print(f"Elenco già pubblicato non disponibile: {e}")
        return []


def main():
    os.makedirs(CARTELLA, exist_ok=True)
    fonti = {"aspi": leggi_aspi, "a22": leggi_a22}
    vecchie = None
    tutte, esito = [], {}
    for nome, leggi in fonti.items():
        try:
            tutte += leggi()
            esito[nome] = "nuove"
        except Exception as e:
            print(f"!! {nome}: {e}")
            if vecchie is None:
                vecchie = pubblicate()
            tenute = [t for t in vecchie if t.get("f") == nome]
            print(f"   tengo le {len(tenute)} telecamere già pubblicate")
            tutte += tenute
            esito[nome] = "vecchie" if tenute else "assenti"
    if not tutte:
        print("Nessuna telecamera da nessuna fonte: mi fermo.")
        sys.exit(1)
    # stessa telecamera ripetuta nell'elenco: si tiene la prima
    viste, uniche = set(), []
    for t in tutte:
        if t["id"] not in viste:
            viste.add(t["id"])
            uniche.append(t)
    uniche.sort(key=lambda t: (t["s"], t["km"] if t["km"] is not None else 1e9))
    strade = elenco_strade(uniche)
    adesso = datetime.now(ROMA).strftime("%Y-%m-%dT%H:%M")
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump({"aggiornato": adesso, "fonti": esito, "n": len(uniche), "strade": strade, "t": uniche},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"Salvate {len(uniche)} telecamere in {FILE} ({os.path.getsize(FILE) // 1024} kB) · {esito}")
    print(f"\nStrade con telecamere ({len(strade)}):")
    for s in strade:
        km = f"km {s['da']:g}–{s['a']:g}" if s["da"] is not None else ""
        print(f"  {s['s']:<6} {s['n']:>4}  {s['sn']}  {km}")


def chiave_strada(s):
    """A1 < A4 < A10 < A14 < RA… : prima la lettera, poi il numero."""
    m = re.match(r"([A-Za-z]+)(\d*)", s)
    return (m.group(1), int(m.group(2) or 0), s) if m else (s, 0, s)


def elenco_strade(cams):
    per = {}
    for t in cams:
        # una riga per tratta: "A1 MILANO-BOLOGNA", "A1 BOLOGNA-FIRENZE"…
        sn = t.get("sn") or t["s"] or "?"
        s = per.setdefault((t["s"], sn), {"s": t["s"] or "?", "sn": sn, "n": 0, "da": None, "a": None, "f": t["f"]})
        s["n"] += 1
        if t.get("km") is not None:
            s["da"] = t["km"] if s["da"] is None else min(s["da"], t["km"])
            s["a"] = t["km"] if s["a"] is None else max(s["a"], t["km"])
    return sorted(per.values(), key=lambda s: (chiave_strada(s["s"]), s["da"] if s["da"] is not None else 0))


if __name__ == "__main__":
    main()
