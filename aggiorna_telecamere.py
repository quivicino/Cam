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

A22_PAGINE = ["https://www.autobrennero.it/it/", "https://www.autobrennero.it/it/in-viaggio/webcam/"]
# l'elenco è una variabile JavaScript nella pagina: var puntiWebcam = {...};
A22_VAR = re.compile(r"puntiWebcam\s*=\s*")


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
    foto = []
    for k, v in (cam.get("frames") or {}).items():
        if k == "V" or not isinstance(v, dict):
            continue
        u = v.get("t_url")
        if isinstance(u, str) and re.search(r"\.(jpe?g|png)$", u, re.I):
            foto.append(u if u.startswith("http") else ASPI_FOTO + u.lstrip("/"))
    # meglio il fotogramma grande della miniatura ("-thumb.jpg")
    foto.sort(key=lambda u: "thumb" in u)
    return foto[0] if foto else ASPI_FOTO + clip[:-4] + "-3.jpg"


def leggi_aspi():
    dati = json.loads(scarica(ASPI_ELENCO, referer="https://viabilita.autostrade.it/"))
    lista = dati.get("webcams") if isinstance(dati, dict) else None
    if not isinstance(lista, list):
        raise ValueError("risposta senza 'webcams'")
    out, scartate = [], {"senza video": 0, "fuori posto": 0, "spente": 0}
    if lista:
        esempio = {k: v for k, v in lista[0].items() if k in ("c_tel", "c_str", "t_des", "t_des_str", "n_prg_km", "frames",
                                                               "n_prg_km_ini", "n_prg_km_fin", "t_dir", "c_dir")}
        print("  campi:", sorted(lista[0].keys()))
        print("  esempio:", json.dumps(esempio, ensure_ascii=False)[:600])
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
        strada = re.sub(r"^([A-Za-z]+)0+(\d)", r"\1\2", strada)   # "A01" → "A1"
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
def json_da(html, inizio):
    """Legge l'oggetto JSON che comincia in html[inizio] ({ o [) fino alla parentesi che lo chiude."""
    dati, _ = json.JSONDecoder().raw_decode(html[inizio:])
    return dati


A22_SITO = "https://www.autobrennero.it"
A22_KM_TOTALI = 314.0   # Brennero (km 0) → Modena, innesto A1 (km 314)
# Brennero, confine di Stato → Campogalliano, innesto con l'A1
A22_ESTREMI = ((11.5066, 47.0028), (10.8716, 44.6839))
A22_SLIDE = re.compile(
    r'class="webcam swiper-slide[^"]*"\s+data-km=["\']?(\d+(?:[.,]\d+)?)["\']?.*?<img\s+src=["\']?([^"\' >]+)'
    r'.*?webcam-title[^>]*>([^<]*)<.*?webcam-place[^>]*>(.*?)</div>', re.S)


def linea_a22():
    """Tracciato dell'A22 da Brennero a Modena (OSRM su dati OpenStreetMap), con i metri progressivi."""
    (lo1, la1), (lo2, la2) = A22_ESTREMI
    url = (f"https://router.project-osrm.org/route/v1/driving/{lo1},{la1};{lo2},{la2}"
           "?overview=full&geometries=geojson")
    r = json.loads(scarica(url, tentativi=3))
    pts = r["routes"][0]["geometry"]["coordinates"]
    prog = [0.0]
    for a, b in zip(pts, pts[1:]):
        prog.append(prog[-1] + metri(a[1], a[0], b[1], b[0]))
    return pts, prog


def metri(la1, lo1, la2, lo2):
    import math
    r = math.pi / 180
    a = math.sin((la2 - la1) * r / 2) ** 2 + math.cos(la1 * r) * math.cos(la2 * r) * math.sin((lo2 - lo1) * r / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def punto_al_km(pts, prog, km):
    """Punto del tracciato al km indicato (in proporzione alla lunghezza del tracciato)."""
    obiettivo = prog[-1] * min(max(km / A22_KM_TOTALI, 0), 1)
    for i in range(1, len(prog)):
        if prog[i] >= obiettivo:
            f = (obiettivo - prog[i - 1]) / ((prog[i] - prog[i - 1]) or 1)
            lo = pts[i - 1][0] + f * (pts[i][0] - pts[i - 1][0])
            la = pts[i - 1][1] + f * (pts[i][1] - pts[i - 1][1])
            return la, lo
    return pts[-1][1], pts[-1][0]


def leggi_a22():
    """Le webcam A22 sono nella pagina principale del sito (carosello "Avvisi e webcam"): km, nome, comune,
    direzione e immagine, ma senza coordinate. La posizione si ricava dal km lungo il tracciato dell'A22."""
    html = None
    for url in A22_PAGINE:
        try:
            html = scarica(url, tentativi=2).decode("utf-8", "replace")
            if "WebCamImg" in html or A22_VAR.search(html):
                break
        except Exception as e:
            print(f"  A22: {url} non risponde ({e})")
    if not html:
        raise ValueError("sito non raggiungibile")
    m = A22_VAR.search(html)
    if m:   # vecchia versione del sito, con le coordinate
        return a22_da_variabile(json_da(html, m.end()))

    trovate = {}
    for km, img, nome, luogo in A22_SLIDE.findall(html):
        km = float(km.replace(",", "."))
        luogo = pulisci(re.sub(r"<[^>]+>", " | ", luogo))
        if km not in trovate:
            trovate[km] = (img, pulisci(nome), luogo)
    if not trovate:
        raise ValueError("webcam non trovate nella pagina")
    pts, prog = linea_a22()
    print(f"  A22: {len(trovate)} webcam, tracciato di {prog[-1] / 1000:.0f} km")
    out = []
    for km, (img, nome, luogo) in sorted(trovate.items()):
        la, lo = punto_al_km(pts, prog, km)
        if not img.startswith("http"):
            img = A22_SITO + "/" + img.lstrip("/")
        comune = luogo.split("|")[0].strip()
        testo = luogo.lower()
        out.append({
            "id": f"a22-km{km:g}",
            "la": round(la, 5), "lo": round(lo, 5),
            "s": "A22", "sn": "A22 Brennero-Modena",
            "n": f"{nome} ({comune})" if comune and comune.lower() not in nome.lower() else nome,
            "km": km,
            "dir": "Modena" if "modena" in testo else "Brennero" if "brennero" in testo else "",
            "img": img, "vid": None, "f": "a22"
        })
    print(f"A22 Brennero: {len(out)} telecamere")
    return out


def a22_da_variabile(dati):
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
                img = A22_SITO + img
            des = pulisci(c.get("Descrizione"))
            km = numero(c.get("Distanza"))
            d = des.lower()
            out.append({
                "id": "a22-" + str(c.get("ID")),
                "la": round(lat, 5), "lo": round(lon, 5),
                "s": "A22", "sn": "A22 Brennero-Modena",
                "n": des or "A22",
                "km": round(km, 1) if km is not None else None,
                "dir": "Modena" if "modena" in d else "Brennero" if "brennero" in d else "",
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
    import fonti_altre as altre
    altre.scarica, altre.pulisci, altre.numero = scarica, pulisci, numero
    vecchie = pubblicate()
    # posizioni già calcolate (dal km o dal nome) nelle pubblicazioni precedenti
    altre.POSIZIONI_NOTE = {t["id"]: (t["la"], t["lo"]) for t in vecchie if t.get("f") == "astm"}
    fonti = {"aspi": leggi_aspi, "a22": leggi_a22, "iv": altre.leggi_infoviaggiando,
             "abp": altre.leggi_abp, "astm": altre.leggi_astm, "msv": altre.leggi_serravalle, "anas": altre.leggi_anas}
    tutte, esito = [], {}
    for nome, leggi in fonti.items():
        try:
            tutte += leggi()
            esito[nome] = "nuove"
        except Exception as e:
            print(f"!! {nome}: {e}")
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
