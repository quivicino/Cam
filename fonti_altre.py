"""
Qui-Cam – webcam degli altri gestori autostradali (oltre ad Autostrade per l'Italia e A22).

  * Infoviaggiando (Autostrade Alto Adriatico, CAV - Passante di Mestre, A28, A57...): servizio WFS con
    le coordinate di ogni telecamera.
  * A4 Brescia-Verona-Vicenza-Padova: elenco JSON con le coordinate.
  * Gruppo ASTM (SATAP A4 Torino-Milano, Autostrada dei Fiori A6, Concessioni del Tirreno A10/A12,
    SALT A15, Autovia Padana A21): pagine "webcam" con immagine e video di ogni telecamera, il nome
    e quasi sempre il km, ma senza coordinate. La posizione si ricava:
      - dal km, lungo il tracciato dell'autostrada calcolato con OSRM (dati OpenStreetMap);
      - se il km manca, cercando il nome del luogo (Nominatim) e agganciandolo al tracciato.
    È una posizione approssimata (di solito entro uno o due km), ma sempre sull'autostrada giusta,
    quindi la telecamera compare nei percorsi che la attraversano.
"""
import html as htmlmod
import json
import math
import re
import time
import urllib.parse

# Le funzioni di rete e di pulizia arrivano dallo script principale (aggiorna_telecamere.py)
scarica = None
pulisci = None
numero = None

# Posizioni già calcolate nelle pubblicazioni precedenti: {id: (lat, lon)}. Evita di ricalcolarle ogni volta.
POSIZIONI_NOTE = {}


def metri(la1, lo1, la2, lo2):
    r = math.pi / 180
    a = math.sin((la2 - la1) * r / 2) ** 2 + math.cos(la1 * r) * math.cos(la2 * r) * math.sin((lo2 - lo1) * r / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


# ---------- Tracciati ----------
_tracciati = {}


def tracciato(punti):
    """Percorso in auto che passa per i punti [(lon, lat), ...], con i metri progressivi."""
    chiave = tuple(punti)
    if chiave in _tracciati:
        return _tracciati[chiave]
    coord = ";".join(f"{lo},{la}" for lo, la in punti)
    ultimo = None
    for base in ("https://router.project-osrm.org/route/v1/driving/",
                 "https://routing.openstreetmap.de/routed-car/route/v1/driving/"):
        try:
            r = json.loads(scarica(base + coord + "?overview=full&geometries=geojson", tentativi=2))
            pts = r["routes"][0]["geometry"]["coordinates"]
            break
        except Exception as e:
            ultimo = e
    else:
        raise ValueError(f"tracciato non calcolabile: {ultimo}")
    prog = [0.0]
    for a, b in zip(pts, pts[1:]):
        prog.append(prog[-1] + metri(a[1], a[0], b[1], b[0]))
    _tracciati[chiave] = (pts, prog)
    time.sleep(1)
    return pts, prog


def punto_lungo(pts, prog, frazione):
    obiettivo = prog[-1] * min(max(frazione, 0.0), 1.0)
    for i in range(1, len(prog)):
        if prog[i] >= obiettivo:
            f = (obiettivo - prog[i - 1]) / ((prog[i] - prog[i - 1]) or 1)
            return (pts[i - 1][1] + f * (pts[i][1] - pts[i - 1][1]),
                    pts[i - 1][0] + f * (pts[i][0] - pts[i - 1][0]))
    return pts[-1][1], pts[-1][0]


def aggancia(pts, la, lo):
    """Punto del tracciato più vicino a (la, lo) e la sua distanza in metri."""
    best, bp = float("inf"), None
    for p in pts:
        d = metri(la, lo, p[1], p[0])
        if d < best:
            best, bp = d, (p[1], p[0])
    return bp, best


_geocodifiche = {}


def cerca_luogo(testo):
    if testo in _geocodifiche:
        return _geocodifiche[testo]
    url = ("https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=it&q="
           + urllib.parse.quote(testo))
    try:
        r = json.loads(scarica(url, tentativi=2))
        ris = (float(r[0]["lat"]), float(r[0]["lon"])) if r else None
    except Exception:
        ris = None
    _geocodifiche[testo] = ris
    time.sleep(1.1)   # Nominatim: al massimo una richiesta al secondo
    return ris


# ---------- Infoviaggiando ----------
INFOVIAGGIANDO = ("https://www.infoviaggiando.it/WFS/?service=WFS&request=GetFeature"
                  "&typename=PortaleWeb:VW_WEBCAM&outputFormat=json")
INFOVIAGGIANDO_IMG = "https://www.infoviaggiando.it/webcam/webcamimage?ipAddr={ip}&progr=1"


def leggi_infoviaggiando():
    dati = json.loads(scarica(INFOVIAGGIANDO, referer="https://www.infoviaggiando.it/it/webcam"))
    out, scartate = [], 0
    for f in dati.get("features", []):
        p = f.get("properties") or {}
        if p.get("VIS_WEB") != "S":
            scartate += 1
            continue
        lo, la = (f.get("geometry") or {}).get("coordinates", [None, None])[:2]
        url = p.get("URL") or "---"
        if url.startswith("https://inviaggio.autobspd.it/"):
            continue   # telecamere A4 Brescia-Padova: arrivano dalla loro fonte
        if url == "---":
            url = INFOVIAGGIANDO_IMG.format(ip=p.get("IP", ""))
        if la is None or lo is None:
            continue
        strada = pulisci(p.get("AUTOSTRADA")) or "?"
        nome = pulisci(p.get("NOME"))
        out.append({
            "id": f"iv-{p.get('IDTELECAMERA')}",
            "la": round(la, 5), "lo": round(lo, 5),
            "s": strada, "sn": f"{strada} {pulisci(p.get('FONTE'))}".strip(),
            "n": re.sub(r"^" + re.escape(strada) + r"\s+", "", nome) or nome,
            "km": numero(p.get("PROG_KM")),
            "dir": pulisci(p.get("CARREGGIATA")).lower(),
            "img": url, "vid": None, "f": "iv"
        })
    print(f"Infoviaggiando: {len(out)} telecamere (nascoste dal gestore: {scartate})")
    if not out:
        raise ValueError("nessuna telecamera")
    return out


# ---------- A4 Brescia-Padova ----------
ABP_ELENCO = "https://inviaggio.autobspd.it/o/map-rest/webcam/A4AAA"
ABP_SITO = "https://inviaggio.autobspd.it"


def leggi_abp():
    lista = json.loads(scarica(ABP_ELENCO, referer=ABP_SITO + "/"))
    out = []
    for c in lista:
        la, lo = numero(c.get("lat")), numero(c.get("lng"))
        if la is None or lo is None or not c.get("url"):
            continue
        nome = pulisci(c.get("name"))
        m = re.search(r"km\s*([\d.,]+)", nome, re.I)
        out.append({
            "id": f"abp-{c.get('id')}",
            "la": round(la, 5), "lo": round(lo, 5),
            "s": "A4", "sn": "A4 BRESCIA-PADOVA",
            "n": nome,
            "km": numero(m.group(1).replace(",", ".")) if m else None,
            "dir": pulisci(c.get("direction")).lower(),
            "img": c["url"] if c["url"].startswith("http") else ABP_SITO + c["url"],
            "vid": None, "f": "abp"
        })
    print(f"A4 Brescia-Padova: {len(out)} telecamere")
    if not out:
        raise ValueError("nessuna telecamera")
    return out


# ---------- Gruppo ASTM ----------
# Per ogni pagina: le tratte che contiene. Ogni tratta ha i punti per calcolarne il tracciato
# [(lon, lat) dal km "da" al km "a"] e la provincia o zona da aggiungere ai nomi da cercare.
ASTM = [
    {"url": "https://www.satapweb.it/webcam-a4/", "gestore": "SATAP", "tratte": [
        {"s": "A4", "sn": "A4 TORINO-MILANO", "punti": [(7.7095, 45.1107), (9.0790, 45.5165)], "da": 0, "a": 126.5,
         "zona": "Piemonte"}]},
    {"url": "https://www.autostradadeifiori.it/webcam/", "gestore": "Autostrada dei Fiori", "tratte": [
        {"s": "A6", "sn": "A6 TORINO-SAVONA", "punti": [(7.6880, 44.9840), (8.4390, 44.3070)], "da": 0, "a": 124,
         "zona": "Piemonte"}]},
    {"url": "https://www.concessionideltirreno.it/webcam-a10/", "gestore": "Concessioni del Tirreno", "tratte": [
        {"s": "A10", "sn": "A10 SAVONA-VENTIMIGLIA", "punti": [(8.4390, 44.3070), (7.5370, 43.7880)], "da": 45.5, "a": 158,
         "zona": "Liguria", "alias": {"BARRIERA FRANCIA": "Grimaldi, Ventimiglia", "RACCORDO A10-A6": "Zinola, Savona"}}]},
    {"url": "https://www.concessionideltirreno.it/webcam-a12/", "gestore": "Concessioni del Tirreno", "tratte": [
        {"s": "A12", "sn": "A12 SESTRI LEVANTE-LIVORNO", "punti": [(9.4170, 44.2830), (10.4170, 43.6060)], "da": 48.6, "a": 166.5,
         "zona": "", "chiave": "A12"},
        {"s": "A11", "sn": "A11 LUCCA-VIAREGGIO", "punti": [(10.5220, 43.8650), (10.2930, 43.8890)], "da": 71.5, "a": 86,
         "zona": "Toscana", "chiave": "A11"},
        {"s": "A15", "sn": "A15 PARMA-LA SPEZIA", "punti": [(10.2640, 44.8420), (9.9520, 44.1330)], "da": 0, "a": 108,
         "zona": "", "chiave": "A15"}]},
    {"url": "https://www.salt.it/webcam/", "gestore": "SALT", "tratte": [
        {"s": "A15", "sn": "A15 PARMA-LA SPEZIA", "punti": [(10.2640, 44.8420), (9.9520, 44.1330)], "da": 0, "a": 108,
         "zona": "Emilia-Romagna"}]},
    {"url": "https://www.autoviapadana.it/webcam/", "gestore": "Autovia Padana", "tratte": [
        {"s": "A21", "sn": "A21 PIACENZA-BRESCIA", "punti": [(9.8240, 45.0480), (10.1690, 45.4800)], "da": None, "a": None,
         "zona": "", "alias": {"Ponte sul fiume Po": "Castelvetro Piacentino", "Bivio per Fiorenzuola": "San Pietro in Cerro"}}]},
    {"url": "https://www.sav-a5.it/webcam/", "gestore": "SAV", "tratte": [
        {"s": "A5", "sn": "A5 QUINCINETTO-AOSTA", "punti": [(7.8090, 45.5610), (7.2900, 45.7300)], "da": None, "a": None,
         "zona": "Valle d'Aosta", "alias": {"FUNIVIA PILA": "Charvensod", "P.S.MARTIN": "Pont-Saint-Martin"}}]},
    # A33: il km parte da Asti (allacciamento A21) e arriva a Cuneo
    {"url": "https://www.asticuneo.it/webcam/", "gestore": "Asti-Cuneo", "tratte": [
        {"s": "A33", "sn": "A33 ASTI-CUNEO", "punti": [(8.2560, 44.8960), (7.5480, 44.4080)], "da": 0, "a": 90,
         "zona": "Piemonte"}]},
    {"url": "https://www.sitaf.it/webcam-a32/", "gestore": "SITAF", "tratte": [
        {"s": "A32", "sn": "A32 TORINO-BARDONECCHIA", "punti": [(7.5660, 45.0740), (6.7040, 45.0820)], "da": None, "a": None,
         "zona": "Torino", "alias": {"Galleria La Perosa": "Rosta", "Galleria Prapontin": "Mattie",
                                     "Ingresso Circ": "Oulx", "Ingresso piazzale Frejus": "Bardonecchia"}}]},
    {"url": "https://www.tangenziale.esterna.it/webcam/", "gestore": "Tangenziale Esterna", "tratte": [
        {"s": "A58", "sn": "A58 TANGENZIALE EST ESTERNA DI MILANO", "punti": [(9.3520, 45.5830), (9.3300, 45.3520)],
         "da": None, "a": None, "zona": "Lombardia"}]},
]
ASTM_BLOCCO = re.compile(r"<!-- WEBCAM -->(.*?)<!-- /WEBCAM -->", re.S)


def km_da_testo(t):
    """'Rondissone KM 24+500' → 24.5 ; 'MASSA-CARRARA km. 114' → 114 ; '42+894 sud' → 42.894"""
    m = re.search(r"(?:km\.?\s*)?(\d{1,3})\s*\+\s*(\d{1,3})", t, re.I) or re.search(r"km\.?\s*(\d{1,3})\s(\d{3})\b", t, re.I)
    if m and "+" not in m.group(0):   # 'KM 14 895' = 14,895
        return int(m.group(1)) + int(m.group(2)) / 1000
    m = m or re.search(r"km\.?\s*(\d{1,3})(?:[.,](\d+))?", t, re.I)
    if not m:
        return None
    intero, dec = m.group(1), m.group(2) or "0"
    return int(intero) + (int(dec) / 1000 if "+" in m.group(0) else float("0." + dec))


def leggi_astm():
    out = []
    for pagina in ASTM:
        try:
            testo = scarica(pagina["url"], tentativi=2).decode("utf-8", "replace")
        except Exception as e:
            print(f"  ASTM: {pagina['url']} non risponde ({e})")
            continue
        n0 = len(out)
        for blocco in ASTM_BLOCCO.findall(testo):
            h2 = re.search(r"<h2[^>]*>(.*?)</h2>", blocco, re.S)
            img = re.search(r"<img[^>]+src=[\"']([^\"']+\.jpe?g)[^\"']*[\"']", blocco)
            vid = re.search(r"href=[\"']([^\"']+\.mp4)[^\"']*[\"']", blocco)
            if not h2 or not img:
                continue
            nome = pulisci(htmlmod.unescape(re.sub(r"<[^>]+>", " ", h2.group(1))))
            # una pagina può avere più tratte: si sceglie quella il cui codice compare nel nome
            tratta = pagina["tratte"][0]
            for tr in pagina["tratte"]:
                if tr.get("chiave") and re.match(tr["chiave"] + r"\b", nome):
                    tratta = tr
            id_cam = re.search(r"/([\w-]+)\.jpe?g", img.group(1)).group(1)
            ident = f"astm-{tratta['s'].lower()}-{id_cam}"
            km = km_da_testo(nome)
            pos = POSIZIONI_NOTE.get(ident)
            if not pos:
                try:
                    pos = posiziona(tratta, km, nome)
                except Exception as e:
                    print(f"  ASTM: posizione non trovata per {nome}: {e}")
                    pos = None
            if not pos:
                continue
            dirs = re.findall(r"DIR\.\s*([^<]+)<", blocco)
            out.append({
                "id": ident,
                "la": round(pos[0], 5), "lo": round(pos[1], 5),
                "s": tratta["s"], "sn": tratta["sn"],
                "n": re.sub(r"^" + tratta["s"] + r"\s+", "", nome),
                "km": round(km, 1) if km is not None else None,
                "dir": " / ".join(pulisci(d).lower() for d in dirs[:2]) if dirs else "",
                "img": img.group(1), "vid": vid.group(1) if vid else None, "f": "astm",
                "g": pagina["gestore"]
            })
        print(f"  ASTM: {len(out) - n0} telecamere da {pagina['url']}")
    print(f"Gruppo ASTM: {len(out)} telecamere")
    if not out:
        raise ValueError("nessuna telecamera")
    return out


def posiziona(tratta, km, nome):
    pts, prog = tracciato(tratta["punti"])
    if km is not None and tratta["da"] is not None and tratta["da"] - 2 <= km <= tratta["a"] + 2:
        return punto_lungo(pts, prog, (km - tratta["da"]) / (tratta["a"] - tratta["da"]))
    # niente km: si cerca il nome del luogo e lo si aggancia all'autostrada
    for k, v in (tratta.get("alias") or {}).items():
        if nome.lower().startswith(k.lower()):
            p = cerca_luogo(v)
            if p:
                return aggancia(pts, p[0], p[1])[0]
    luogo = re.sub(r"(?i)\b(km\.?\s*[\d+ ,.]*|svincolo|uscita|bivio( per)?|interc\.?|ads|area di (servizio|sosta)|"
                   r"raccordo|galleria|barriera|ponte sul fiume|nord|sud|est|ovest|cn|at|centro|lato\s+\S+)\b", " ", nome)
    luogo = re.sub(r"[–—-]", " ", luogo)
    luogo = pulisci(re.sub(r"\s+", " ", luogo))
    if not luogo:
        return None
    p = cerca_luogo(f"{luogo}, {tratta['zona']}" if tratta["zona"] and "(" not in luogo else luogo)
    if not p:
        return None
    punto, dist = aggancia(pts, p[0], p[1])
    if dist > 12000:
        print(f"  ASTM: {nome} trovato a {dist / 1000:.0f} km dall'autostrada, scartato")
        return None
    return punto


# ---------- Milano Serravalle - Milano Tangenziali ----------
# La mappa del sito contiene l'elenco: webcam[0] = {"url": "/admin/news/video/brugherio", "svincolo": "Brugherio - A51 ",
# "lat": 45.5380, "lng": 9.2857}. Ogni telecamera è una diretta video (HLS) in una pagina che si può incorporare.
MSV_MAPPA = "https://www.serravalle.it/index.php/map"
MSV_SITO = "https://www.serravalle.it"
MSV_NOMI = {"A7": "A7 MILANO-SERRAVALLE", "A50": "A50 TANGENZIALE OVEST DI MILANO",
            "A51": "A51 TANGENZIALE EST DI MILANO", "A52": "A52 TANGENZIALE NORD DI MILANO"}
# Coordinate sbagliate nell'elenco del gestore (Ghisolfa è dato vicino a Pero, ma è il nodo di viale Certosa/A4)
MSV_CORREZIONI = {"ghisolfa": (45.4993, 9.1497, "A4", "A4 MILANO GHISOLFA")}


def leggi_serravalle():
    pagina = scarica(MSV_MAPPA).decode("utf-8", "replace")
    out = []
    for blocco in re.findall(r"webcam\[\d+\]\s*=\s*(\{[^}]*\})", pagina):
        try:
            c = json.loads(blocco)
        except ValueError:
            continue
        url = c.get("url") or ""
        m = re.search(r"/video/([\w-]+)$", url)
        la, lo = numero(c.get("lat")), numero(c.get("lng"))
        if not m or la is None or lo is None:
            continue
        slug = m.group(1)
        nome = pulisci(c.get("svincolo"))
        r = re.search(r"\b(A\d+)\s*$", nome)
        strada = r.group(1) if r else ""
        sn = MSV_NOMI.get(strada, strada)
        if slug in MSV_CORREZIONI:
            la, lo, strada, sn = MSV_CORREZIONI[slug]
        out.append({
            "id": "msv-" + slug,
            "la": round(la, 5), "lo": round(lo, 5),
            "s": strada or "MI", "sn": sn or "MILANO SERRAVALLE",
            "n": pulisci(re.sub(r"\s*-\s*A\d+\s*$", "", nome)) or slug,
            "km": None, "dir": "",
            "img": None, "vid": None,
            "emb": (url if url.startswith("http") else MSV_SITO + url),
            "f": "msv"
        })
    print(f"Milano Serravalle: {len(out)} telecamere")
    if not out:
        raise ValueError("nessuna telecamera")
    return out
