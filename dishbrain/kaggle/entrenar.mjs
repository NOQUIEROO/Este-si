// Entrena cultivos de PongBrain con distintas reglas y guarda resultados y pesos.
// Uso: node entrenar.mjs <núcleo> <núcleos> <segundos>
import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire(import.meta.url);
const Cultivo = require('./cultivo.js');
const [core, cores, budget] = process.argv.slice(2).map(Number);
const MIN = +(process.env.MIN || (fs.existsSync('inicial.json') ? 50 : 20));   // minutos de juego por corrida
const t0 = Date.now(), base = JSON.parse(JSON.stringify(Cultivo.PARAMS));
// variantes a probar: intensidad de aprendizaje, memoria de las conexiones, tamaño de lo que siente cada electrodo
// qué le muestran los electrodos (stimMode) e intensidad de aprendizaje; y controles sin retroalimentación
const variantes = [];
variantes.push({ stimMode: 'lado', lr: 0.6 }, { stimMode: 'lado', lr: 0.6, plasticMotor: true }, { stimMode: 'lado', lr: 2, plasticMotor: true }, { stimMode: 'lado', control: true });
// seguir entrenando un cultivo ya entrenado (inicial.json): misma red, distintas intensidades, y una copia congelada para comparar
let inicial = null;
if (fs.existsSync('inicial.json')) {
  inicial = JSON.parse(fs.readFileSync('inicial.json', 'utf8'));
  variantes.length = 0;
  for (const lr of [0.3, 0.6, 1]) variantes.push({ ...inicial.params, lr });
  variantes.push({ ...inicial.params, lr: 0 });
}
if (process.env.VARIANTES) { variantes.length = 0; variantes.push(...JSON.parse(process.env.VARIANTES)); }
const SEMILLAS = process.env.SEMILLAS ? JSON.parse(process.env.SEMILLAS) : null;
{
}
const corridas = [];
for (const seed of SEMILLAS || (inicial ? [inicial.seed] : [11, 22])) for (const v of variantes) corridas.push({ v, seed });
const mias = corridas.filter((_, k) => k % cores === core);
fs.mkdirSync('resultados', { recursive: true });
let mejor = null;
for (const { v, seed } of mias) {
  if ((Date.now() - t0) / 1000 > budget - 90) break;   // no pasarse del tiempo
  Object.assign(Cultivo.PARAMS, base, v);
  const c = new Cultivo({ seed, condition: v.control ? 'sinfeedback' : 'estimulo' });
  c.growAll(); c.setCondition(v.control ? 'sinfeedback' : 'estimulo');
  if (inicial) c.W.set(new Float32Array(Uint8Array.from(Buffer.from(inicial.W, 'base64')).buffer));
  const curva = [], seg = []; let cortada = false, tramo = 60;
  for (let m = 0; m < MIN; m += 2.5) {
    if ((Date.now() - t0) / 1000 + tramo * 1.2 > budget - 30) { cortada = true; break; }   // no empezar un tramo que no llega a terminar
    const tt = Date.now();
    // además de golpes por rally: qué tan seguido la paleta se mueve hacia donde está la pelota (cuando viene)
    let bien = 0, n = 0;
    for (let k = 0; k < 150000; k++) {
      c.step();
      if (k % 10 === 0 && c.phase === 'juego' && c.ball.vx < 0) { const d = c.ball.y - c.paddle, v = c.rateDown - c.rateUp; if (Math.abs(d) > 0.05 && v !== 0) { n++; if (Math.sign(d) === Math.sign(v)) bien++; } }
    }
    const s = c.summary(m * 60000, (m + 2.5) * 60000); curva.push(+s.hitsPerRally.toFixed(3)); seg.push(n ? +(bien / n).toFixed(3) : 0);
    tramo = (Date.now() - tt) / 1000;
    console.log('tramo', JSON.stringify(v), seed, m + 2.5, 'min', curva[curva.length - 1], Math.round(tramo) + 's');
  }
  if (curva.length < 2) break;
  if (cortada) console.log('cortada', JSON.stringify(v), seed);
  const final = +(curva.slice(-2).reduce((a, b) => a + b) / 2).toFixed(3);
  const r = { v, seed, curva, seg, final, goles: c.goals, golesAdv: c.totalMisses, golpes: c.totalHits, mejora: +(curva.slice(-2).reduce((a, b) => a + b) / 2 - curva.slice(0, 2).reduce((a, b) => a + b) / 2).toFixed(3) };
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
