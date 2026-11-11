/*
 * Qui-Cam – interfaccia: mappa, posizione, percorso, telecamere, elenco.
 * Stessa struttura di Qui-Distributori.
 */
(function () {
  "use strict";
  const cfg = window.CAM_CONFIG;
  const $ = (id) => document.getElementById(id);
  const PREF = "cam.";
  const leggiPref = (k, def) => { try { const v = localStorage.getItem(PREF + k); return v === null ? def : v; } catch (e) { return def; } };
  const salvaPref = (k, v) => { try { localStorage.setItem(PREF + k, String(v)); } catch (e) { /* ignora */ } };

  const RAGGI = [5000, 10000, 25000, 50000];
  const SOGLIE = [200, 400, 1000];
  const stato = {
    gps: null,            // ultima posizione GPS {lat, lon, acc}
    centro: null,         // punto di ricerca senza percorso {lat, lon, daGps}
    raggio: +leggiPref("raggio", cfg.raggioMetri || 25000),
    soglia: +leggiPref("soglia", cfg.sogliaPercorsoMetri || 400),
    tutte: [],            // tutte le telecamere dell'elenco
    aggiornato: null,
    percorso: null,       // { linea: [[lon,lat]…], metri, secondi, da, a, daNome, aNome }
    mostrate: [],         // telecamere vicine o lungo il percorso, in ordine
    fonti: new Set(["aspi", "a22", "iv", "abp", "astm", "msv"].filter((f) => leggiPref("fonte-" + f, "1") !== "0")),
    seguiGps: true,
    indiceProssima: -1
  };
  if (!RAGGI.includes(stato.raggio)) stato.raggio = 25000;
  if (!SOGLIE.includes(stato.soglia)) stato.soglia = 400;

  // ---------- Mappa ----------
  const mappa = L.map("mappa", { zoomControl: false, attributionControl: true, preferCanvas: false })
    .setView([42.5, 12.5], 6);
  const ATTR = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Webcam: Autostrade per l\'Italia, A22';
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  const sfondi = {
    stradale: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: ATTR }),
    grande: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, tileSize: 512, zoomOffset: -1, attribution: ATTR }),
    satellite: L.layerGroup([
      L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        maxZoom: 19, attribution: "Immagini: Esri, Vantor, Earthstar Geographics · Strade: Esri, HERE, Garmin, © OpenStreetMap · Webcam: Autostrade per l'Italia, A22"
      }),
      L.tileLayer(ESRI + "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, opacity: .8 }),
      L.tileLayer(ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19 })
    ])
  };
  let sfondoAttivo = leggiPref("sfondo", "stradale");
  if (!sfondi[sfondoAttivo]) sfondoAttivo = "stradale";
  function impostaSfondo(nome) {
    Object.values(sfondi).forEach((l) => mappa.removeLayer(l));
    sfondoAttivo = sfondi[nome] ? nome : "stradale";
    sfondi[sfondoAttivo].addTo(mappa);
    $("mappa").classList.toggle("satellite", sfondoAttivo === "satellite");
    salvaPref("sfondo", sfondoAttivo);
  }
  impostaSfondo(sfondoAttivo);

  const tela = L.canvas({ padding: 0.3 });
  const livelli = {
    tutte: L.layerGroup().addTo(mappa),     // puntini di tutte le telecamere d'Italia
    raggio: L.layerGroup().addTo(mappa),
    percorso: L.layerGroup().addTo(mappa),
    mostrate: L.layerGroup().addTo(mappa),
    io: L.layerGroup().addTo(mappa)
  };
  const markerPerId = new Map();
  mappa.on("dragstart", () => { stato.seguiGps = false; });

  const colore = (nome, def) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim() || def;
  const icona = (cls, html) => L.divIcon({ className: "", html: `<div class="mk ${cls}">${html ?? ""}</div>`, iconSize: null });

  // ---------- Utilità UI ----------
  function messaggio(testo, errore) {
    const el = $("stato");
    el.textContent = testo;
    el.classList.toggle("errore", !!errore);
    if (errore && $("pannello").hidden) toast(testo);
  }
  let timerToast;
  function toast(testo) {
    const t = $("toast");
    t.textContent = testo;
    t.hidden = false;
    clearTimeout(timerToast);
    timerToast = setTimeout(() => { t.hidden = true; }, 3600);
  }
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const linkNavigazione = (lat, lon) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}&travelmode=driving`;
  const ora = () => new Date().toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

  async function fetchJson(url, opts, ms) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), ms);
    try {
      const r = await fetch(url, { ...opts, signal: ctrl.signal });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return await r.json();
    } finally {
      clearTimeout(t);
    }
  }

  // ---------- Immagini dal vivo ----------
  // Le immagini arrivano direttamente dai siti dei gestori. A ogni aggiornamento si aggiunge "?t=…"
  // all'indirizzo, così il browser non mostra quella vecchia che ha in memoria.
  let giroImmagini = Date.now();
  const conOra = (url) => url + (url.includes("?") ? "&" : "?") + "t=" + Math.floor(giroImmagini / 1000);

  // Riquadro dell'immagine: <img> che, se il gestore non dà il fotogramma, passa al video
  function htmlScatto(t, grande) {
    // Nel riquadro grande, se c'è, si mostra l'ultima ripresa video (la miniatura JPG di Autostrade è piccola)
    const media = !t.img && t.emb
      ? (grande
        ? `<iframe class="diretta" src="${esc(t.emb)}" title="Diretta della telecamera ${esc(t.n)}" allow="autoplay; fullscreen" loading="lazy" referrerpolicy="no-referrer"></iframe>`
        : `<span class="scatto-diretta"><span>▶</span>Diretta video</span>`)
      : grande && t.vid
      ? `<video data-live="1" autoplay muted loop playsinline preload="auto" poster="${esc(conOra(t.img))}" src="${esc(conOra(t.vid))}"></video>`
      : `<img alt="Immagine della telecamera ${esc(t.n)}" ${grande ? "" : 'loading="lazy"'} src="${esc(conOra(t.img))}">`;
    const orario = t.emb && !t.img ? "" : `<span class="scatto-ora">${esc(ora())}</span>`;
    return `<div class="scatto${grande ? " grande" : ""}" data-id="${esc(t.id)}">${media}${orario}</div>`;
  }
  function collegaScatti(radice) {
    radice.querySelectorAll(".scatto video[data-live]").forEach((v) => {
      if (v.dataset.collegata) return;
      v.dataset.collegata = "1";
      v.addEventListener("error", () => v.closest(".scatto")?.classList.add("rotto"));
      v.play().catch(() => {});
    });
    radice.querySelectorAll(".scatto img").forEach((img) => {
      if (img.dataset.collegata) return;
      img.dataset.collegata = "1";
      img.addEventListener("error", () => immagineRotta(img));
      img.addEventListener("load", () => img.closest(".scatto")?.classList.remove("rotto"));
    });
  }
  function immagineRotta(img) {
    const box = img.closest(".scatto");
    if (!box) return;
    const t = perId.get(box.dataset.id);
    if (t && t.vid && !box.querySelector("video")) {
      // niente fotogramma: si mostra il primo istante del video, che si può far partire
      const v = document.createElement("video");
      v.muted = true; v.playsInline = true; v.preload = "metadata";
      v.setAttribute("playsinline", "");
      v.src = t.vid + "#t=0.5";
      v.addEventListener("error", () => box.classList.add("rotto"));
      img.replaceWith(v);
      return;
    }
    box.classList.add("rotto");
  }
  function aggiornaImmagini() {
    giroImmagini = Date.now();
    document.querySelectorAll(".scatto").forEach((box) => {
      const t = perId.get(box.dataset.id);
      if (!t || box.querySelector("iframe, .scatto-diretta")) return;   // le dirette non si ricaricano
      const v = box.querySelector("video");
      if (v && v.dataset.live) {
        v.poster = conOra(t.img);
        v.src = conOra(t.vid);
        v.play().catch(() => {});
      } else if (v && !v.controls) {   // anteprima video al posto della foto: si ricarica la nuova ripresa
        v.src = t.vid + "?t=" + Math.floor(giroImmagini / 1000) + "#t=0.5";
      } else if (!v) {
        const img = box.querySelector("img");
        if (img) img.src = conOra(t.img);
      }
      const o = box.querySelector(".scatto-ora");
      if (o) o.textContent = ora();
    });
    $("k-tempo").textContent = ora();
  }

  // ---------- Elenco delle telecamere ----------
  let perId = new Map();
  async function caricaElenco() {
    messaggio("Carico l'elenco delle telecamere…");
    try {
      const d = await fetchJson("dati/telecamere.json", { cache: "no-cache" }, 20000);
      stato.tutte = (d.t || []).filter((t) => isFinite(t.la) && isFinite(t.lo) && (t.img || t.emb));
      stato.aggiornato = d.aggiornato || null;
      perId = new Map(stato.tutte.map((t) => [t.id, t]));
      disegnaTutte();
      renderStrade(d.strade || []);
      return true;
    } catch (e) {
      console.warn("Elenco telecamere non disponibile", e);
      messaggio("Non riesco a scaricare l'elenco delle telecamere. Controlla la connessione e tocca Aggiorna.", true);
      return false;
    }
  }
  const visibile = (t) => stato.fonti.has(t.f);

  function disegnaTutte() {
    livelli.tutte.clearLayers();
    const c = colore("--blu", "#1b4f9c");
    for (const t of stato.tutte) {
      if (!visibile(t)) continue;
      L.circleMarker([t.la, t.lo], { renderer: tela, radius: 4, weight: 1.5, color: "#fff", fillColor: c, fillOpacity: .85 })
        .bindPopup(() => popupTelecamera(t), OPZ_POPUP)
        .addTo(livelli.tutte);
    }
  }

  // ---------- Elenco delle strade (nella guida) ----------
  function renderStrade(strade) {
    const box = $("strade-elenco");
    if (!strade.length) return;
    const tot = strade.reduce((n, s) => n + s.n, 0);
    $("btn-strade").textContent = `Strade con telecamere: ${new Set(strade.map((s) => s.s)).size} autostrade, ${tot} telecamere`;
    const agg = stato.aggiornato ? new Date(stato.aggiornato).toLocaleString("it-IT", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : "";
    box.innerHTML = `<table class="tab-strade"><thead><tr><th>Strada</th><th>Tratta</th><th>Km</th><th>Cam</th></tr></thead><tbody>${
      strade.map((s, i) => `<tr tabindex="0" data-i="${i}"><td><span class="strada">${esc(s.s)}</span></td>` +
        `<td>${esc(nomeTratta(s))}</td><td>${s.da != null ? esc(String(Math.round(s.da)) + "–" + String(Math.round(s.a))) : ""}</td><td>${s.n}</td></tr>`).join("")
    }</tbody></table><p class="g-versione">${tot} telecamere${agg ? " · elenco aggiornato il " + esc(agg) : ""}</p>`;
    box.querySelectorAll("tr[data-i]").forEach((tr) => {
      const vai = () => {
        const s = strade[+tr.dataset.i];
        const cams = stato.tutte.filter((t) => t.s === s.s && (t.sn || t.s) === s.sn);
        if (!cams.length) return;
        chiudiGuida(); chiudiElenco();
        stato.seguiGps = false;
        mappa.fitBounds(L.latLngBounds(cams.map((t) => [t.la, t.lo])), { padding: [40, 40], maxZoom: 13 });
      };
      tr.addEventListener("click", vai);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") vai(); });
    });
  }
  // "A1 MILANO-BOLOGNA" → "Milano-Bologna"
  function nomeTratta(s) {
    const n = (s.sn || "").replace(new RegExp("^" + s.s + "\\b\\s*", "i"), "").trim();
    if (n !== n.toUpperCase()) return n;
    return n ? n.toLowerCase().replace(/(^|[\s\-\/'(])\S/g, (c) => c.toUpperCase()) : "";
  }
  $("btn-strade").addEventListener("click", (e) => {
    apriGuida(e);
    setTimeout(() => $("g-strade").scrollIntoView({ block: "start" }), 50);
  });

  // ---------- Riquadro (popup) ----------
  const OPZ_POPUP = { maxWidth: 420, minWidth: 280, autoPanPaddingTopLeft: [16, 175], autoPanPaddingBottomRight: [16, 40], className: "pop-cam" };
  function descrizione(t) {
    const parti = [];
    if (t.s) parti.push(`<span class="strada">${esc(t.s)}</span>`);
    if (t.km != null) parti.push(esc(QC.formattaKm(t.km)));
    if (t.dir) parti.push("direzione " + esc(t.dir));
    return parti.join(" · ");
  }
  function quandoCiPassi(t) {
    if (!stato.percorso || t.lungo == null) return "";
    const p = stato.percorso;
    const sec = QC.secondiFinoA(t, p.metri, p.secondi);
    return `a ${QC.formattaDistanza(t.lungo)} dalla partenza · circa ${QC.formattaDurata(sec)}`;
  }
  function popupTelecamera(t) {
    const div = document.createElement("div");
    div.className = "pop";
    const num = t.ordine ? `<span class="pop-num">${t.ordine}</span>` : "";
    const quando = quandoCiPassi(t);
    div.innerHTML = `<h3>${num}${esc(titolo(t))}</h3>
      <p class="pop-meta">${descrizione(t)}</p>
      ${quando ? `<p class="pop-meta">${esc(quando)}</p>` : ""}
      ${htmlScatto(t, true)}
      ${t.emb && !t.img ? '<p class="pop-nota">Diretta video dal sito del gestore</p>' : t.vid ? '<p class="pop-nota">Ultima ripresa, rifatta ogni pochi minuti</p>' : ""}
      <p class="pop-rotto">Questa telecamera adesso non manda immagini (spenta o in manutenzione).</p>
      <div class="pop-azioni">
        <a class="pop-vai" href="${linkNavigazione(t.la, t.lo)}" target="_blank" rel="noopener">Portami qui</a>
      </div>
      <p class="fonte">${esc(nomeGestore(t))}</p>`;
    collegaScatti(div);
    return div;
  }
  const GESTORI = { aspi: "Autostrade per l'Italia", a22: "Autostrada del Brennero", iv: "Infoviaggiando", abp: "A4 Brescia-Padova", astm: "Gruppo ASTM", msv: "Milano Serravalle" };
  function nomeGestore(t) {
    if (t.f === "iv" && t.sn) return t.sn.replace(/^\S+\s*/, "") || GESTORI.iv;
    return t.g || GESTORI[t.f] || "";
  }
  // "km. 285 Arno a Firenze itinere nord" → "Arno a Firenze itinere nord"
  function titolo(t) {
    const n = (t.n || "").replace(/^km\.?\s*[\d.,]+\s*/i, "").trim();
    return n ? n.charAt(0).toUpperCase() + n.slice(1) : (t.sn || t.s || "Telecamera");
  }

  // ---------- Calcolo delle telecamere da mostrare ----------
  function ricalcola(adatta) {
    const lista = stato.tutte.filter(visibile);
    if (stato.percorso) {
      stato.mostrate = QC.lungoPercorso(lista, stato.percorso.linea, stato.soglia);
      stato.mostrate.forEach((t, i) => { t.ordine = i + 1; });
    } else if (stato.centro) {
      stato.mostrate = QC.vicine(lista, stato.centro.lat, stato.centro.lon, stato.raggio);
    } else {
      stato.mostrate = [];
    }
    stato.indiceProssima = -1;
    render(adatta);
  }

  function render(adatta) {
    livelli.raggio.clearLayers();
    livelli.percorso.clearLayers();
    livelli.mostrate.clearLayers();
    markerPerId.clear();
    const blu = colore("--blu", "#1b4f9c");

    if (stato.percorso) {
      const pts = stato.percorso.linea.map(([lo, la]) => [la, lo]);
      L.polyline(pts, { color: "#fff", weight: 9, opacity: .9, interactive: false }).addTo(livelli.percorso);
      const linea = L.polyline(pts, { color: blu, weight: 5, opacity: .9, interactive: false }).addTo(livelli.percorso);
      L.marker(pts[0], { icon: icona("tappa", "A"), interactive: false, zIndexOffset: 800 }).addTo(livelli.percorso);
      L.marker(pts[pts.length - 1], { icon: icona("tappa arrivo", "B"), interactive: false, zIndexOffset: 800 }).addTo(livelli.percorso);
      if (adatta) mappa.fitBounds(linea.getBounds(), { padding: [30, 30] });
    } else if (stato.centro) {
      L.circle([stato.centro.lat, stato.centro.lon], {
        radius: stato.raggio, color: blu, weight: 1.5, opacity: .6, fillOpacity: .04, dashArray: "6 6", interactive: false
      }).addTo(livelli.raggio);
      if (!stato.centro.daGps) {
        L.circleMarker([stato.centro.lat, stato.centro.lon], { radius: 6, color: "#fff", weight: 2, fillColor: "#172033", fillOpacity: 1 }).addTo(livelli.io);
      }
      if (adatta) mappa.fitBounds(L.latLng(stato.centro.lat, stato.centro.lon).toBounds(stato.raggio * 2.1));
    }

    for (const t of stato.mostrate) {
      const m = L.marker([t.la, t.lo], {
        icon: icona("cam" + (t.ordine ? " num" : ""), t.ordine ? String(t.ordine) : ""),
        title: titolo(t), zIndexOffset: 500 - (t.ordine || 0)
      }).bindPopup(() => popupTelecamera(t), OPZ_POPUP).addTo(livelli.mostrate);
      markerPerId.set(t.id, m);
    }

    renderRiepilogo();
    renderSommario();
    renderLista();
  }

  function renderRiepilogo() {
    const p = stato.percorso;
    $("riepilogo").hidden = !p;
    if (!p) return;
    const n = stato.mostrate.length;
    $("riep-titolo").textContent = `${p.daNome} → ${p.aNome}`;
    const strade = QC.stradePercorso(stato.mostrate);
    $("riep-dettagli").textContent = `${QC.formattaDistanza(p.metri)} · ${QC.formattaDurata(p.secondi)} · ` +
      (n ? `${n} telecamer${n === 1 ? "a" : "e"}${strade.length ? " su " + strade.slice(0, 5).join(", ") : ""}` : "nessuna telecamera");
  }

  function renderSommario() {
    const n = stato.mostrate.length;
    $("k-n").textContent = stato.tutte.length ? n : "–";
    const b = $("badge-elenco");
    b.hidden = !n;
    b.textContent = n > 99 ? "99+" : n;
    if (stato.percorso) {
      $("k-n-et").innerHTML = "telecamere<br>sul percorso";
      $("k-km").textContent = QC.formattaDistanza(stato.percorso.metri).replace(" km", "");
      $("k-km-et").innerHTML = "km<br>di percorso";
      $("btn-navi").hidden = false;
      const p = stato.percorso;
      $("btn-navi").href = `https://www.google.com/maps/dir/?api=1&origin=${p.da.lat},${p.da.lon}&destination=${p.a.lat},${p.a.lon}&travelmode=driving`;
    } else {
      $("k-n-et").innerHTML = "telecamere<br>vicine";
      $("k-km").textContent = stato.raggio / 1000;
      $("k-km-et").innerHTML = "km di raggio<br>intorno a te";
      $("btn-navi").hidden = true;
    }
  }

  function voceLista(t) {
    const li = document.createElement("li");
    li.className = "voce-cam";
    const destra = stato.percorso
      ? `<b>${QC.formattaDistanza(t.lungo)}</b><small>~${QC.formattaDurata(QC.secondiFinoA(t, stato.percorso.metri, stato.percorso.secondi))}</small>`
      : `<b>${QC.formattaDistanza(t.distanza)}</b><small>da te</small>`;
    li.innerHTML = `
      ${htmlScatto(t, false)}
      <div class="voce-cam-testo">
        <div class="voce-titolo">${t.ordine ? `<span class="n">${t.ordine}</span>` : ""}${esc(titolo(t))}</div>
        <div class="voce-meta">${descrizione(t)}</div>
        <div class="voce-dist">${destra}</div>
      </div>`;
    li.tabIndex = 0;
    const apri = () => { mostra(t); chiudiElenco(); };
    li.addEventListener("click", apri);
    li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); apri(); } });
    return li;
  }

  let quanteInLista = 40;
  function renderLista() {
    const ol = $("lista");
    ol.innerHTML = "";
    if (!stato.tutte.length) return;
    const lista = stato.mostrate;
    if (!lista.length) {
      const li = document.createElement("li");
      li.className = "vuoto";
      li.textContent = stato.percorso
        ? "Nessuna telecamera lungo questo percorso. Prova ad aumentare la distanza dal percorso: forse la strada non è un'autostrada con webcam."
        : stato.centro
          ? "Nessuna telecamera in questo raggio. Allargalo qui sopra o imposta un percorso."
          : "Consenti la posizione oppure scrivi partenza e arrivo in alto per vedere le telecamere.";
      ol.appendChild(li);
      return;
    }
    lista.slice(0, quanteInLista).forEach((t) => ol.appendChild(voceLista(t)));
    if (lista.length > quanteInLista) {
      const li = document.createElement("li");
      li.className = "altre";
      li.innerHTML = `<button type="button" class="btn-altre">Mostra altre ${Math.min(40, lista.length - quanteInLista)} telecamere (${lista.length - quanteInLista} in tutto)</button>`;
      li.querySelector("button").addEventListener("click", () => { quanteInLista += 40; renderLista(); });
      ol.appendChild(li);
    }
    collegaScatti(ol);
  }

  function mostra(t) {
    if (!t) return;
    stato.seguiGps = false;
    mappa.setView([t.la, t.lo], Math.max(mappa.getZoom(), 13));
    const m = markerPerId.get(t.id);
    if (m) setTimeout(() => m.openPopup(), 250);
    else L.popup(OPZ_POPUP).setLatLng([t.la, t.lo]).setContent(popupTelecamera(t)).openOn(mappa);
  }

  // Prossima telecamera: con un percorso la prima davanti a te, poi le successive a ogni tocco
  function prossima() {
    const lista = stato.mostrate;
    if (!lista.length) { toast(stato.percorso ? "Nessuna telecamera sul percorso." : "Nessuna telecamera vicina."); return; }
    let i;
    if (stato.indiceProssima >= 0) {
      i = (stato.indiceProssima + 1) % lista.length;
    } else if (stato.percorso && stato.gps) {
      const io = QC.lungoPercorso([{ id: "io", la: stato.gps.lat, lo: stato.gps.lon }], stato.percorso.linea, 3000)[0];
      i = io ? lista.findIndex((t) => t.lungo > io.lungo) : 0;
      if (i < 0) { toast("Hai già passato tutte le telecamere del percorso."); i = lista.length - 1; }
    } else {
      i = 0;
    }
    stato.indiceProssima = i;
    mostra(lista[i]);
  }

  // ---------- Percorso ----------
  async function cercaLuogo(q) {
    const url = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=it,sm,va,ch,at,fr,si&accept-language=it&q=" + encodeURIComponent(q);
    const [primo] = await fetchJson(url, { headers: { Accept: "application/json" } }, 12000);
    if (!primo) return null;
    const nome = (primo.name || primo.display_name.split(",")[0]).trim();
    return { lat: +primo.lat, lon: +primo.lon, nome };
  }
  const QUI = /^(la mia posizione|qui|posizione)$/i;

  async function calcolaPercorso(daTesto, aTesto) {
    messaggio("Calcolo il percorso…");
    $("btn-vai").disabled = true;
    $("btn-vai").classList.add("gira-testo");
    try {
      let da;
      if (!daTesto || QUI.test(daTesto)) {
        if (!stato.gps) { messaggio("Non so ancora dove sei: scrivi anche la partenza.", true); $("da").focus(); return; }
        da = { lat: stato.gps.lat, lon: stato.gps.lon, nome: "La tua posizione" };
      } else {
        da = await cercaLuogo(daTesto);
        if (!da) { messaggio("Partenza non trovata: prova ad aggiungere la città.", true); return; }
      }
      const a = await cercaLuogo(aTesto);
      if (!a) { messaggio("Arrivo non trovato: prova ad aggiungere la città.", true); return; }

      let rotta = null, ultimoErrore = null;
      for (const base of cfg.serverPercorso) {
        try {
          const url = `${base}${da.lon},${da.lat};${a.lon},${a.lat}?overview=full&geometries=geojson&alternatives=false&steps=false`;
          const r = await fetchJson(url, {}, 20000);
          if (r.code === "Ok" && r.routes && r.routes[0]) { rotta = r.routes[0]; break; }
          ultimoErrore = new Error(r.code || "nessun percorso");
        } catch (e) { ultimoErrore = e; }
      }
      if (!rotta) { console.warn(ultimoErrore); messaggio("Non riesco a calcolare il percorso adesso. Riprova tra poco.", true); return; }

      stato.percorso = {
        linea: rotta.geometry.coordinates, metri: rotta.distance, secondi: rotta.duration,
        da, a, daNome: da.nome, aNome: a.nome
      };
      stato.seguiGps = false;
      salvaPref("percorso-da", daTesto || "");
      salvaPref("percorso-a", aTesto);
      quanteInLista = 40;
      ricalcola(true);
      const n = stato.mostrate.length;
      messaggio(`${da.nome} → ${a.nome}: ${QC.formattaDistanza(rotta.distance)}, ${QC.formattaDurata(rotta.duration)}, ` +
        `${n} telecamer${n === 1 ? "a" : "e"} lungo la strada · ${ora()}`);
      if (window.goatcounter && window.goatcounter.count) window.goatcounter.count({ path: "percorso", title: "Percorso calcolato", event: true });
    } catch (e) {
      console.warn(e);
      messaggio("Ricerca non riuscita. Controlla la connessione.", true);
    } finally {
      $("btn-vai").disabled = false;
      $("btn-vai").classList.remove("gira-testo");
    }
  }

  function togliPercorso() {
    stato.percorso = null;
    stato.mostrate.forEach((t) => { delete t.ordine; });
    $("a").value = "";
    salvaPref("percorso-a", "");
    stato.seguiGps = true;
    if (stato.gps) stato.centro = { lat: stato.gps.lat, lon: stato.gps.lon, daGps: true };
    quanteInLista = 40;
    ricalcola(true);
    messaggioVicine();
  }

  function messaggioVicine() {
    if (!stato.centro) return;
    const dove = stato.centro.daGps ? "intorno a te" : "intorno al punto cercato";
    messaggio(`${stato.mostrate.length} telecamere entro ${QC.formattaDistanza(stato.raggio)} ${dove} · scrivi dove vai per vedere quelle lungo la strada`);
  }

  $("form-percorso").addEventListener("submit", (e) => {
    e.preventDefault();
    const da = $("da").value.trim(), a = $("a").value.trim();
    if (!a) { $("a").focus(); toast("Scrivi dove vai."); return; }
    document.activeElement && document.activeElement.blur();
    calcolaPercorso(da, a);
  });
  $("da").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("a").focus(); } });
  $("btn-inverti").addEventListener("click", () => {
    const da = $("da").value, a = $("a").value;
    $("da").value = a;
    $("a").value = da;
    if (stato.percorso && $("a").value.trim()) calcolaPercorso($("da").value.trim(), $("a").value.trim());
    else if (stato.percorso && !$("a").value.trim()) {
      // ritorno verso la tua posizione: l'arrivo è il punto di partenza di prima
      $("a").value = stato.percorso.daNome === "La tua posizione" ? "" : stato.percorso.daNome;
    }
  });
  $("btn-togli-percorso").addEventListener("click", togliPercorso);

  // ---------- Posizione ----------
  let marcatoreIo, cerchioPrecisione, primaPosizione = true;
  function suPosizione(p) {
    const { latitude: lat, longitude: lon, accuracy: acc } = p.coords;
    stato.gps = { lat, lon, acc };
    if (!marcatoreIo) {
      marcatoreIo = L.marker([lat, lon], { icon: L.divIcon({ className: "", html: '<div class="io-box"><div class="io-cono" hidden></div><div class="io"></div></div>', iconSize: [18, 18] }), zIndexOffset: 1000, interactive: false }).addTo(livelli.io);
      cerchioPrecisione = L.circle([lat, lon], { radius: acc, color: "#2f7cf6", weight: 0, fillOpacity: .12, interactive: false }).addTo(livelli.io);
    } else {
      marcatoreIo.setLatLng([lat, lon]);
      cerchioPrecisione.setLatLng([lat, lon]).setRadius(acc);
    }
    if (window.QuiBussola) QuiBussola.gps(p.coords);
    if (stato.percorso) return;
    const prima = stato.centro;
    const spostato = !prima || !prima.daGps || QC.distanza(prima.lat, prima.lon, lat, lon) > 1000;
    if (stato.seguiGps && spostato) {
      stato.centro = { lat, lon, daGps: true };
      if (stato.tutte.length) { ricalcola(primaPosizione); primaPosizione = false; messaggioVicine(); }
    }
  }
  function erroreGps(e) {
    const testi = {
      1: "Posizione non autorizzata: scrivi partenza e arrivo in alto per vedere le telecamere.",
      2: "Posizione non disponibile: scrivi partenza e arrivo in alto.",
      3: "Il GPS non risponde: scrivi partenza e arrivo in alto."
    };
    if (!stato.gps && !stato.percorso) messaggio(testi[e.code] || testi[2], true);
  }
  function avviaGps() {
    if (!("geolocation" in navigator)) { messaggio("Questo browser non fornisce la posizione: scrivi partenza e arrivo in alto.", true); return; }
    navigator.geolocation.watchPosition(suPosizione, erroreGps, { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 });
  }

  // ---------- Controlli ----------
  $("btn-centra").addEventListener("click", () => {
    if (!stato.gps) { toast("Posizione non ancora disponibile."); return; }
    stato.seguiGps = true;
    if (!stato.percorso) {
      stato.centro = { lat: stato.gps.lat, lon: stato.gps.lon, daGps: true };
      ricalcola(true);
      messaggioVicine();
    } else {
      mappa.setView([stato.gps.lat, stato.gps.lon], Math.max(mappa.getZoom(), 12));
    }
  });
  $("btn-aggiorna").addEventListener("click", async () => {
    $("btn-aggiorna").classList.add("gira");
    if (!stato.tutte.length) { if (await caricaElenco()) ricalcola(true); }
    aggiornaImmagini();
    setTimeout(() => $("btn-aggiorna").classList.remove("gira"), 700);
    toast("Immagini aggiornate alle " + ora());
  });
  $("btn-prossima").addEventListener("click", prossima);

  $("raggio").value = String(stato.raggio);
  $("raggio").addEventListener("change", (e) => {
    stato.raggio = +e.target.value;
    salvaPref("raggio", stato.raggio);
    if (!stato.percorso) { ricalcola(true); messaggioVicine(); }
  });
  $("soglia").value = String(stato.soglia);
  $("soglia").addEventListener("change", (e) => {
    stato.soglia = +e.target.value;
    salvaPref("soglia", stato.soglia);
    if (stato.percorso) ricalcola(false);
  });
  document.querySelectorAll(".chip.filtro").forEach((c) => {
    c.setAttribute("aria-pressed", String(stato.fonti.has(c.dataset.filtro)));
    c.addEventListener("click", () => {
      const f = c.dataset.filtro;
      const on = !stato.fonti.has(f);
      on ? stato.fonti.add(f) : stato.fonti.delete(f);
      salvaPref("fonte-" + f, on ? "1" : "0");
      c.setAttribute("aria-pressed", String(on));
      disegnaTutte();
      ricalcola(false);
    });
  });
  $("sfondo").value = sfondoAttivo;
  $("sfondo").addEventListener("change", (e) => impostaSfondo(e.target.value));

  function apriElenco() {
    $("pannello").hidden = false;
    $("btn-elenco").setAttribute("aria-expanded", "true");
    $("btn-chiudi").focus();
    aggiornaImmagini();
  }
  function chiudiElenco() {
    if ($("pannello").hidden) return;
    $("pannello").hidden = true;
    $("btn-elenco").setAttribute("aria-expanded", "false");
    $("btn-elenco").focus();
  }
  $("btn-elenco").addEventListener("click", apriElenco);
  $("btn-chiudi").addEventListener("click", chiudiElenco);

  const linkApp = location.origin + location.pathname + "?ref=whatsapp";
  $("btn-condividi").href = "https://wa.me/?text=" + encodeURIComponent(
    "Ti consiglio Qui-Cam: scrivi da dove parti e dove vai e vedi in diretta le webcam delle autostrade lungo la strada. " +
    "Gratis e senza registrazione: " + linkApp);

  // ---------- Guida ----------
  let tornaA = null;
  function apriGuida(e) {
    tornaA = e && e.currentTarget ? e.currentTarget : $("btn-guida");
    $("guida").hidden = false;
    $("guida").querySelector(".pannello-corpo").scrollTop = 0;
    $("btn-guida").setAttribute("aria-expanded", "true");
    $("btn-chiudi-guida").focus();
  }
  function chiudiGuida() {
    if ($("guida").hidden) return false;
    $("guida").hidden = true;
    $("btn-guida").setAttribute("aria-expanded", "false");
    if (tornaA && tornaA.offsetParent) tornaA.focus();
    return true;
  }
  $("btn-guida").addEventListener("click", apriGuida);
  $("btn-chiudi-guida").addEventListener("click", chiudiGuida);
  $("guida").querySelectorAll(".g-indice a").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const dest = $("guida").querySelector(a.getAttribute("href"));
    if (dest) dest.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  $("guida-versione").textContent = "Versione " + (cfg.versione || "");
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !chiudiGuida()) chiudiElenco(); });

  // ---------- Aggiornamento automatico delle immagini ----------
  let timerAuto, autoAttivo = false;
  function impostaAuto(sec) {
    clearInterval(timerAuto);
    if (sec > 0) timerAuto = setInterval(() => { if (!document.hidden) aggiornaImmagini(); }, sec * 1000);
    autoAttivo = sec > 0;
    aggiornaSchermoAcceso();
    salvaPref("auto", sec);
  }
  let bloccoSchermo = null, richiestaInCorso = false;
  function mostraOcchio() { $("occhio").hidden = !bloccoSchermo; }
  async function aggiornaSchermoAcceso() {
    const vuole = autoAttivo && document.visibilityState === "visible";
    if (!vuole) {
      if (bloccoSchermo) { const b = bloccoSchermo; bloccoSchermo = null; b.release().catch(() => {}); }
      mostraOcchio();
      return;
    }
    if (bloccoSchermo || richiestaInCorso || !("wakeLock" in navigator)) { mostraOcchio(); return; }
    richiestaInCorso = true;
    try {
      const b = await navigator.wakeLock.request("screen");
      b.addEventListener("release", () => { if (bloccoSchermo === b) { bloccoSchermo = null; mostraOcchio(); } });
      if (autoAttivo && document.visibilityState === "visible") bloccoSchermo = b;
      else b.release().catch(() => {});
    } catch (e) { /* non supportato o negato */ }
    richiestaInCorso = false;
    mostraOcchio();
  }
  document.addEventListener("visibilitychange", () => {
    aggiornaSchermoAcceso();
    if (!document.hidden) aggiornaImmagini();
  });
  document.addEventListener("pointerdown", () => { if (autoAttivo && !bloccoSchermo) aggiornaSchermoAcceso(); }, { passive: true });

  let secAuto = cfg.autoRefreshSecondi ?? 60;
  const salvato = leggiPref("auto", null);
  if (salvato !== null && ["0", "30", "60", "120"].includes(salvato)) secAuto = +salvato;
  $("auto-refresh").value = String(secAuto);
  impostaAuto(secAuto);
  $("auto-refresh").addEventListener("change", (e) => {
    impostaAuto(+e.target.value);
    toast(+e.target.value ? `Immagini aggiornate ogni ${e.target.value} secondi` : "Aggiornamento automatico spento");
  });

  mappa.on("popupopen", (e) => {
    const el = e.popup.getElement && e.popup.getElement();
    if (el) collegaScatti(el);
  });

  $("elenco-versione").textContent = "Versione " + (cfg.versione || "");
  $("k-tempo").textContent = ora();

  // ---------- Avvio ----------
  // Percorso dal link (?da=…&a=…) oppure l'ultimo arrivo scritto
  const q = new URLSearchParams(location.search);
  $("da").value = q.get("da") || leggiPref("percorso-da", "");
  $("a").value = q.get("a") || leggiPref("percorso-a", "");
  caricaElenco().then((ok) => {
    if (!ok) return;
    if (q.get("a")) { calcolaPercorso($("da").value.trim(), $("a").value.trim()); return; }
    if (stato.centro) { ricalcola(primaPosizione); primaPosizione = false; messaggioVicine(); }
    else messaggio(`${stato.tutte.length} telecamere in elenco. Scrivi dove vai per vedere quelle lungo la strada.`);
  });
  avviaGps();

  if ("serviceWorker" in navigator && window.isSecureContext) {
    const cerano = !!navigator.serviceWorker.controller;
    let ricaricata = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (cerano && !ricaricata) { ricaricata = true; location.reload(); }
    });
    navigator.serviceWorker.register("sw.js").then((reg) => reg.update()).catch(() => {});
  }
})();
