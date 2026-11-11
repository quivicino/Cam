#!/usr/bin/env python3
"""Sonda: scarica gli indirizzi indicati e descrive cosa contengono (serve per aggiungere nuovi gestori).
Uso: python3 strumenti/sonda.py URL [URL...]"""
import json, re, sys, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def descrivi_json(d, prof=0, chiave="radice"):
    pre = "    " * prof
    if isinstance(d, dict):
        print(f"{pre}{chiave}: oggetto con {len(d)} chiavi: {list(d)[:25]}")
        if prof < 3:
            for k in list(d)[:6]:
                if isinstance(d[k], (dict, list)):
                    descrivi_json(d[k], prof + 1, k)
    elif isinstance(d, list):
        print(f"{pre}{chiave}: lista di {len(d)}")
        if d and prof < 4:
            print(f"{pre}  primo: {json.dumps(d[0], ensure_ascii=False)[:700]}")


for url in sys.argv[1:]:
    print("=" * 100)
    print(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "it-IT,it;q=0.9"})
        with urllib.request.urlopen(req, timeout=30) as r:
            corpo = r.read()
            print(f"HTTP {r.status} · {r.headers.get('Content-Type')} · {len(corpo)} byte · finale {r.geturl()}")
    except Exception as e:
        print("ERRORE:", e)
        continue
    testo = corpo.decode("utf-8", "replace")
    try:
        descrivi_json(json.loads(testo))
        continue
    except Exception:
        pass
    t = re.search(r"<title[^>]*>(.*?)</title>", testo, re.S | re.I)
    print("titolo:", t.group(1).strip()[:120] if t else "-")
    print("parola webcam:", len(re.findall(r"(?i)webcam", testo)), "· telecamer:", len(re.findall(r"(?i)telecamer", testo)))
    for nome, pat in [("jpg", r"[\w/.:%-]+\.jpe?g[\w?=&.%-]*"), ("mp4", r"[\w/.:%-]+\.mp4[\w?=&.%-]*"),
                      ("m3u8", r"[\w/.:%-]+\.m3u8[\w?=&.%-]*"), ("json/api", r"[\w/.:%-]*(?:api|json|ajax|rest|wfs|geojson|webcam)[\w/.:%-]*\.(?:json|php|aspx|ashx|js)[\w?=&.%-]*")]:
        v = sorted(set(re.findall(pat, testo, re.I)))
        print(f"{nome} ({len(v)}):", v[:12])
    print("script:", re.findall(r"<script[^>]*src=[\"']?([^\"' >]+)", testo, re.I)[:15])
    print("iframe:", re.findall(r"<iframe[^>]*src=[\"']?([^\"' >]+)", testo, re.I)[:10])
    for m in list(re.finditer(r"(?i)webcam|telecamer", testo))[:3]:
        print("  contesto:", repr(testo[max(0, m.start() - 200):m.start() + 400])[:620])
    k = re.search(r"(?i)(lat(?:itude)?[\"']?\s*[:=]\s*[\"']?4\d\.\d+)", testo)
    if k:
        print("  coordinate:", repr(testo[max(0, k.start() - 300):k.start() + 300]))
