// Entrena cultivos de PongBrain con distintas reglas y guarda resultados y pesos.
// Uso: node entrenar.mjs <núcleo> <núcleos> <segundos>
import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire(import.meta.url);
const Cultivo = require('./cultivo.js');
const [core, cores, budget] = process.argv.slice(2).map(Number);
const MIN = 20;   // minutos de juego por corrida
const t0 = Date.now(), base = JSON.parse(JSON.stringify(Cultivo.PARAMS));
// variantes a probar: intensidad de aprendizaje, memoria de las conexiones, tamaño de lo que siente cada electrodo
// qué le muestran los electrodos (stimMode) e intensidad de aprendizaje; y controles sin retroalimentación
const variantes = [];
variantes.push({ stimMode: 'lado', lr: 0.6 }, { stimMode: 'lado', lr: 0.6, plasticMotor: true }, { stimMode: 'lado', lr: 2, plasticMotor: true }, { stimMode: 'lado', control: true });
const corridas = [];
for (const seed of [11, 22]) for (const v of variantes) corridas.push({ v, seed });
const mias = corridas.filter((_, k) => k % cores === core);
fs.mkdirSync('resultados', { recursive: true });
let mejor = null;
for (const { v, seed } of mias) {
  if ((Date.now() - t0) / 1000 > budget - 90) break;   // no pasarse del tiempo
  Object.assign(Cultivo.PARAMS, base, v);
  const c = new Cultivo({ seed, condition: v.control ? 'sinfeedback' : 'estimulo' });
  c.growAll(); c.setCondition(v.control ? 'sinfeedback' : 'estimulo');
  const curva = []; let cortada = false;
  for (let m = 0; m < MIN; m += 2.5) {
    if ((Date.now() - t0) / 1000 > budget - 60) { cortada = true; break; }   // terminar a tiempo para poder escribir
    c.run(150000); const s = c.summary(m * 60000, (m + 2.5) * 60000); curva.push(+s.hitsPerRally.toFixed(3));
  }
  if (curva.length < 2) break;
  if (cortada) console.log('cortada', JSON.stringify(v), seed);
  const final = +(curva.slice(-2).reduce((a, b) => a + b) / 2).toFixed(3);
  const r = { v, seed, curva, final, goles: c.goals, golesAdv: c.totalMisses, golpes: c.totalHits, mejora: +(curva.slice(-2).reduce((a, b) => a + b) / 2 - curva.slice(0, 2).reduce((a, b) => a + b) / 2).toFixed(3) };
  fs.writeFileSync(`resultados/corrida_${core}_${corridas.indexOf(corridas.find((x) => x.v === v && x.seed === seed))}.json`, JSON.stringify(r));
  console.log(JSON.stringify(r));
  if (!v.control && (!mejor || r.final > mejor.final)) {
    mejor = r;
    mejor.W = Buffer.from(new Float32Array(c.W).buffer).toString('base64'); mejor.params = { ...Cultivo.PARAMS };
  }
}
// el mejor de este núcleo, con sus pesos, en el registro (es lo que se puede leer desde afuera)
if (mejor) { fs.writeFileSync(`resultados/pesos_nucleo_${core}.json`, JSON.stringify(mejor)); console.log('PESOS ' + JSON.stringify(mejor)); }
console.log('núcleo', core, 'terminó en', Math.round((Date.now() - t0) / 1000), 's');
