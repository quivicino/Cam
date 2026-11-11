// Prove della logica: node test_core.js
const QC = require("./core.js");
const assert = require("assert");

// percorso dritto verso est lungo il 45° parallelo, circa 78 km
const linea = [];
for (let i = 0; i <= 100; i++) linea.push([9 + i * 0.01, 45]);
const cams = [
  { id: "a", la: 45.001, lo: 9.2 },    // ~110 m a nord, al km ~15,7
  { id: "b", la: 45.0, lo: 9.05 },     // sulla strada, al km ~3,9
  { id: "c", la: 45.02, lo: 9.5 },     // ~2,2 km a nord: fuori
  { id: "d", la: 45.0, lo: 10.5 },     // oltre la fine: fuori
  { id: "e", la: 44.998, lo: 9.9 }     // ~220 m a sud, vicino alla fine
];
const lungo = QC.lungoPercorso(cams, linea, 400);
assert.deepStrictEqual(lungo.map((t) => t.id), ["b", "a", "e"]);
assert(Math.abs(lungo[1].scarto - 111) < 5, "scarto di a");
assert(Math.abs(lungo[1].lungo - 15720) < 200, "posizione di a: " + lungo[1].lungo);
assert.strictEqual(QC.lungoPercorso(cams, linea, 200).length, 2);

const vic = QC.vicine(cams, 45, 9.2, 1000);
assert.deepStrictEqual(vic.map((t) => t.id), ["a"]);

assert.strictEqual(QC.formattaDurata(3600 + 5 * 60), "1 h 05");
assert.strictEqual(QC.formattaDurata(40), "1 min");
assert.strictEqual(QC.formattaDistanza(1234), "1,2 km");
assert.strictEqual(QC.formattaDistanza(234567), "235 km");
assert.deepStrictEqual(QC.stradePercorso([{ s: "A8" }, { s: "A8" }, { s: "A7" }]), ["A8", "A7"]);

// prestazioni: percorso lungo e mille telecamere
const lunga = [];
for (let i = 0; i <= 20000; i++) lunga.push([8 + i * 0.0004, 44 + i * 0.0002]);
const tante = [];
for (let i = 0; i < 1000; i++) tante.push({ id: "t" + i, la: 38 + Math.random() * 8, lo: 7 + Math.random() * 11 });
const t0 = Date.now();
QC.lungoPercorso(tante, lunga, 400);
const ms = Date.now() - t0;
assert(ms < 1500, "troppo lento: " + ms + " ms");
console.log("Tutte le prove passano (" + ms + " ms per 1000 telecamere su 20000 punti)");
