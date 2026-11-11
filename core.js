/*
 * Qui-Cam – logica pura (nessun accesso a DOM o rete).
 * Funziona sia nel browser (window.QC) sia in Node (module.exports) per i test.
 */
(function (root) {
  "use strict";

  const R_TERRA = 6371000;
  const RAD = Math.PI / 180;

  function distanza(lat1, lon1, lat2, lon2) {
    const dLat = (lat2 - lat1) * RAD;
    const dLon = (lon2 - lon1) * RAD;
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(dLon / 2) ** 2;
    return 2 * R_TERRA * Math.asin(Math.sqrt(a));
  }

  function formattaDistanza(m) {
    if (m < 1000) return Math.round(m / 10) * 10 + " m";
    if (m < 100000) return (m / 1000).toFixed(1).replace(".", ",") + " km";
    return Math.round(m / 1000) + " km";
  }

  function formattaDurata(sec) {
    const min = Math.max(1, Math.round(sec / 60));
    if (min < 60) return min + " min";
    const h = Math.floor(min / 60), m = min % 60;
    return h + " h" + (m ? " " + String(m).padStart(2, "0") : "");
  }

  function formattaKm(km) {
    return km == null ? "" : "km " + String(km).replace(".", ",");
  }

  // ---------- Telecamere vicine a un punto ----------
  function vicine(lista, lat, lon, raggio) {
    const out = [];
    for (const t of lista) {
      const d = distanza(lat, lon, t.la, t.lo);
      if (d <= raggio) out.push({ ...t, distanza: d });
    }
    return out.sort((a, b) => a.distanza - b.distanza);
  }

  // ---------- Telecamere lungo un percorso ----------
  // percorso: array di [lon, lat] (come GeoJSON). Per ogni telecamera cerca il punto del percorso
  // più vicino: se è entro "soglia" metri la tiene, con quanti metri di strada mancano per arrivarci
  // ("lungo"). Proiezione piana locale: a queste distanze l'errore è trascurabile.
  function lungoPercorso(lista, percorso, soglia) {
    if (!percorso || percorso.length < 2) return [];
    const n = percorso.length;
    // metri progressivi dall'inizio a ogni vertice
    const prog = new Float64Array(n);
    for (let i = 1; i < n; i++) {
      prog[i] = prog[i - 1] + distanza(percorso[i - 1][1], percorso[i - 1][0], percorso[i][1], percorso[i][0]);
    }
    // riquadro del percorso allargato della soglia, per scartare subito le telecamere lontane
    let minLa = 90, maxLa = -90, minLo = 180, maxLo = -180;
    for (const [lo, la] of percorso) {
      if (la < minLa) minLa = la; if (la > maxLa) maxLa = la;
      if (lo < minLo) minLo = lo; if (lo > maxLo) maxLo = lo;
    }
    const mLa = soglia / 111000, mLo = soglia / (111000 * Math.cos(((minLa + maxLa) / 2) * RAD));
    minLa -= mLa; maxLa += mLa; minLo -= mLo; maxLo += mLo;

    // tratti raggruppati a blocchi di 32 con il loro riquadro: si guardano solo i blocchi vicini
    const BLOCCO = 32, blocchi = [];
    for (let s = 0; s < n - 1; s += BLOCCO) {
      const e = Math.min(n - 1, s + BLOCCO);
      let a = 90, b = -90, c = 180, d = -180;
      for (let i = s; i <= e; i++) {
        const [lo, la] = percorso[i];
        if (la < a) a = la; if (la > b) b = la; if (lo < c) c = lo; if (lo > d) d = lo;
      }
      blocchi.push({ s, e, a: a - mLa, b: b + mLa, c: c - mLo, d: d + mLo });
    }

    const out = [];
    for (const t of lista) {
      if (t.la < minLa || t.la > maxLa || t.lo < minLo || t.lo > maxLo) continue;
      const kx = Math.cos(t.la * RAD) * 111320, ky = 110540;
      let best = Infinity, bestLungo = 0;
      for (const bl of blocchi) {
        if (t.la < bl.a || t.la > bl.b || t.lo < bl.c || t.lo > bl.d) continue;
        for (let i = bl.s; i < bl.e; i++) {
          const ax = (percorso[i][0] - t.lo) * kx, ay = (percorso[i][1] - t.la) * ky;
          const bx = (percorso[i + 1][0] - t.lo) * kx, by = (percorso[i + 1][1] - t.la) * ky;
          const dx = bx - ax, dy = by - ay;
          const l2 = dx * dx + dy * dy;
          let u = l2 > 0 ? -(ax * dx + ay * dy) / l2 : 0;
          u = u < 0 ? 0 : u > 1 ? 1 : u;
          const px = ax + u * dx, py = ay + u * dy;
          const d = Math.sqrt(px * px + py * py);
          if (d < best) { best = d; bestLungo = prog[i] + u * (prog[i + 1] - prog[i]); }
        }
      }
      if (best <= soglia) out.push({ ...t, scarto: best, lungo: bestLungo });
    }
    return out.sort((a, b) => a.lungo - b.lungo);
  }

  // Ora stimata di arrivo a una telecamera, in proporzione alla durata totale del viaggio
  function secondiFinoA(t, lunghezzaTotale, durataTotale) {
    if (!lunghezzaTotale) return 0;
    return durataTotale * (t.lungo / lunghezzaTotale);
  }

  // Strade del percorso in ordine di comparsa, dalle telecamere trovate: "A8 · A50 · A7"
  function stradePercorso(cams) {
    const viste = [];
    for (const t of cams) if (t.s && !viste.includes(t.s)) viste.push(t.s);
    return viste;
  }

  const api = { distanza, formattaDistanza, formattaDurata, formattaKm, vicine, lungoPercorso, secondiFinoA, stradePercorso };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.QC = api;
})(typeof window !== "undefined" ? window : globalThis);
