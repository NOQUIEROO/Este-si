/*
 * Motor de la simulación DishBrain.
 *
 * Modelo simplificado del experimento de Cortical Labs (Kagan et al., Neuron 2022):
 * un cultivo de neuronas sobre una matriz de electrodos (MEA) juega Pong.
 *
 *  - 8 electrodos sensoriales: codifican DÓNDE está la pelota respecto de la paleta
 *    (código de lugar) y QUÉ TAN CERCA está (código de frecuencia, 4–40 Hz).
 *  - 4 regiones motoras: 2 "arriba" y 2 "abajo". La paleta se mueve según qué
 *    par de regiones dispara más.
 *  - Retroalimentación: si la paleta le pega, estímulo PREDECIBLE (todos los
 *    electrodos sensoriales, 100 Hz, 100 ms). Si falla, estímulo IMPREDECIBLE
 *    (electrodos y momentos al azar, 5 Hz, 4 s).
 *
 * Las neuronas son de Izhikevich (regular spiking). El aprendizaje es STDP con
 * trazas de elegibilidad: la retroalimentación predecible consolida los cambios
 * recientes y la impredecible los revierte y sacude los pesos. Es una forma
 * sencilla de expresar la idea del principio de energía libre: la red se queda
 * con las configuraciones que hacen su entrada más predecible.
 *
 * Funciona igual en el navegador (window.DishBrain) y en Node (module.exports).
 */
(function (root) {
  'use strict';

  function rng(seed) {
    let a = seed >>> 0;
    const next = function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    let spare = null;
    next.gauss = function () {
      if (spare !== null) { const s = spare; spare = null; return s; }
      let u = 0, v = 0;
      while (u === 0) u = next();
      v = next();
      const r = Math.sqrt(-2 * Math.log(u));
      spare = r * Math.sin(2 * Math.PI * v);
      return r * Math.cos(2 * Math.PI * v);
    };
    return next;
  }

  // Condiciones del experimento original.
  const CONDITIONS = {
    estimulo:    { label: 'Estímulo',     sensory: true,  hit: 'predecible', miss: 'impredecible', modHit: 1,  modMiss: -1,   jitter: true  },
    silencio:    { label: 'Silencio',     sensory: true,  hit: 'nada',       miss: 'silencio',     modHit: 0,  modMiss: -0.4, jitter: false },
    sinfeedback: { label: 'Sin feedback', sensory: true,  hit: 'nada',       miss: 'nada',         modHit: 0,  modMiss: 0,    jitter: false },
    reposo:      { label: 'Reposo',       sensory: false, hit: 'nada',       miss: 'nada',         modHit: 0,  modMiss: 0,    jitter: false },
  };

  const P = {
    nElec: 8,          // electrodos sensoriales
    perElec: 12,       // neuronas bajo cada electrodo sensorial
    perMotor: 20,      // neuronas por región motora (4 regiones)
    wMin: 0, wMax: 4.5,
    wInit: [1.0, 2.4],
    noiseSens: 2.2,    // ruido de fondo (actividad espontánea)
    noiseMotor: 3.6,
    stimI: 22,         // pulso de un electrodo sobre sus neuronas
    stimP: 0.85,       // probabilidad de que cada neurona responda al pulso
    lateralInh: 3,   // inhibición entre regiones arriba/abajo
    tauTrace: 5,       // ms, trazas STDP
    tauElig: 900,      // ms, traza de elegibilidad
    aPlus: 1.0, aMinus: 0.2,
    lr: 2,
    expectRate: 0.05,  // qué tan rápido se ajusta lo esperado
    missFloor: 0.3,    // un fallo siempre sorprende un poco
    localFrac: 0.2,    // parte del cambio que depende de la sinapsis individual
    jitter: 0.06,      // sacudida de pesos durante el estímulo impredecible
    tauRate: 90,       // ms, filtro de la salida motora
    paddleGain: 0.2,
    paddleVmax: 2,     // alto de cancha por segundo
    paddleHalf: 0.1,
    ballSpeed: 0.62,
    relRange: 0.3,     // rango de posición relativa codificado por los 8 electrodos
    missMs: 4000,
    hitMs: 100,
  };

  function DishBrain(opts) {
    opts = opts || {};
    this.seed = opts.seed == null ? 1 : opts.seed;
    this.condition = opts.condition || 'estimulo';
    this.reset();
  }

  DishBrain.CONDITIONS = CONDITIONS;
  DishBrain.PARAMS = P;

  DishBrain.prototype.reset = function () {
    const r = this.rand = rng(this.seed);
    const NS = this.NS = P.nElec * P.perElec;
    const NM = this.NM = 4 * P.perMotor;
    const N = this.N = NS + NM;
    this.v = new Float32Array(N).fill(-65);
    this.u = new Float32Array(N).fill(-13);
    this.inp = new Float32Array(N);
    this.spiked = new Uint8Array(N);
    this.xPre = new Float32Array(NS);
    this.yPost = new Float32Array(NM);
    this.W = new Float32Array(NS * NM);
    this.E = new Float32Array(NS * NM);
    for (let k = 0; k < NS * NM; k++) this.W[k] = P.wInit[0] + r() * (P.wInit[1] - P.wInit[0]);
    this.rowSum = new Float32Array(NS);
    for (let i = 0; i < NS; i++) {
      let s = 0;
      for (let j = 0; j < NM; j++) s += this.W[i * NM + j];
      this.rowSum[i] = s;
    }
    // región motora de cada neurona motora: 0 y 3 = arriba, 1 y 2 = abajo
    this.region = new Uint8Array(NM);
    this.isUp = new Uint8Array(NM);
    for (let j = 0; j < NM; j++) {
      const reg = Math.floor(j / P.perMotor);
      this.region[j] = reg;
      this.isUp[j] = (reg === 0 || reg === 3) ? 1 : 0;
    }
    this.t = 0;
    this.rateUp = 0; this.rateDown = 0;
    this.elecActivity = new Float32Array(P.nElec);   // para dibujar
    this.regionActivity = new Float32Array(4);
    this.lastStim = new Float32Array(P.nElec).fill(-1e9);
    this.spikeLog = [];        // [t, idx] recientes, para el ráster
    this.paddle = 0.5;
    this.phase = 'juego';      // 'juego' | 'predecible' | 'impredecible' | 'silencio'
    this.phaseEnd = 0;
    this.nextPulse = 0;
    this.rally = 0;
    this.rallies = [];         // {t, hits}
    this.events = [];          // {t, type:'hit'|'miss'}
    this.totalHits = 0; this.totalMisses = 0;
    this.expect = 0.2;         // probabilidad de acierto que la red "espera"
    this.serve();
  };

  DishBrain.prototype.setCondition = function (c) {
    if (!CONDITIONS[c]) throw new Error('condición desconocida: ' + c);
    this.condition = c;
  };

  DishBrain.prototype.serve = function () {
    const r = this.rand;
    this.ball = { x: 1, y: 0.15 + 0.7 * r() };
    const ang = (r() * 0.9 - 0.45) * Math.PI / 2;   // hasta ~40° de inclinación
    this.ball.vx = -P.ballSpeed * Math.cos(ang);
    this.ball.vy = P.ballSpeed * Math.sin(ang);
    this.phase = 'juego';
  };

  // Electrodo sensorial que corresponde a la posición relativa pelota-paleta.
  DishBrain.prototype.placeElectrode = function () {
    const rel = this.ball.y - this.paddle;   // < 0: pelota arriba de la paleta
    let f = (rel + P.relRange) / (2 * P.relRange);
    f = Math.min(0.9999, Math.max(0, f));
    return Math.floor(f * P.nElec);
  };

  DishBrain.prototype.stimFrequency = function () {
    return 4 + 36 * Math.min(1, Math.max(0, 1 - this.ball.x));
  };

  DishBrain.prototype.pulse = function (e, strength) {
    const r = this.rand;
    const base = e * P.perElec;
    for (let k = 0; k < P.perElec; k++) {
      if (r() < P.stimP) this.inp[base + k] += P.stimI * (strength || 1);
    }
    this.lastStim[e] = this.t;
  };

  // La retroalimentación actúa sobre parches de tejido, no sinapsis por sinapsis:
  // cada sinapsis cambia según la elegibilidad promedio de su vía (electrodo → región motora).
  DishBrain.prototype.applyModulation = function (m) {
    if (m === 0) { this.E.fill(0); return; }
    const NS = this.NS, NM = this.NM, W = this.W, E = this.E;
    const nE = P.nElec, pe = P.perElec, pm = P.perMotor;
    const block = new Float32Array(nE * 4);
    for (let i = 0; i < NS; i++) {
      const e = Math.floor(i / pe), o = i * NM;
      for (let j = 0; j < NM; j++) block[e * 4 + this.region[j]] += E[o + j];
    }
    for (let b = 0; b < block.length; b++) block[b] /= pe * pm;
    const k = P.lr * m;
    for (let i = 0; i < NS; i++) {
      const e = Math.floor(i / pe), o = i * NM;
      for (let j = 0; j < NM; j++) {
        const w = W[o + j] + k * ((1 - P.localFrac) * block[e * 4 + this.region[j]] + P.localFrac * E[o + j]);
        W[o + j] = w < P.wMin ? P.wMin : (w > P.wMax ? P.wMax : w);
      }
    }
    this.normalize();
    E.fill(0);
  };

  // Escalado sináptico: cada neurona sensorial reparte siempre el mismo peso total.
  DishBrain.prototype.normalize = function () {
    const NS = this.NS, NM = this.NM, W = this.W;
    for (let i = 0; i < NS; i++) {
      let s = 0;
      const o = i * NM;
      for (let j = 0; j < NM; j++) s += W[o + j];
      if (s <= 0) continue;
      const f = this.rowSum[i] / s;
      for (let j = 0; j < NM; j++) {
        const w = W[o + j] * f;
        W[o + j] = w > P.wMax ? P.wMax : w;
      }
    }
  };

  DishBrain.prototype.jitterWeights = function () {
    const r = this.rand, W = this.W;
    for (let n = 0; n < 2; n++) {
      const q = Math.floor(r() * W.length);
      let w = W[q] + P.jitter * r.gauss();
      W[q] = w < P.wMin ? P.wMin : (w > P.wMax ? P.wMax : w);
    }
  };

  DishBrain.prototype.onHit = function () {
    const C = CONDITIONS[this.condition];
    this.rally++;
    this.totalHits++;
    this.events.push({ t: this.t, type: 'hit' });
    this.applyModulation(C.modHit * (1 - this.expect));
    this.expect += (1 - this.expect) * P.expectRate;
    if (C.hit === 'predecible') {
      this.phase = 'predecible';
      this.phaseEnd = this.t + P.hitMs;
    }
  };

  DishBrain.prototype.onMiss = function () {
    const C = CONDITIONS[this.condition];
    this.totalMisses++;
    this.events.push({ t: this.t, type: 'miss' });
    this.rallies.push({ t: this.t, hits: this.rally, cond: this.condition });
    this.rally = 0;
    this.applyModulation(C.modMiss * (this.expect + P.missFloor));
    this.expect += (0 - this.expect) * P.expectRate;
    if (C.miss === 'impredecible' || C.miss === 'silencio') {
      this.phase = C.miss;
      this.phaseEnd = this.t + P.missMs;
    } else {
      this.serve();
    }
  };

  DishBrain.prototype.updateGame = function (dt) {
    const b = this.ball;
    // paleta: arriba = y menor
    let vel = P.paddleGain * (this.rateDown - this.rateUp);
    if (vel > P.paddleVmax) vel = P.paddleVmax;
    if (vel < -P.paddleVmax) vel = -P.paddleVmax;
    this.paddle += vel * dt;
    if (this.paddle < P.paddleHalf) this.paddle = P.paddleHalf;
    if (this.paddle > 1 - P.paddleHalf) this.paddle = 1 - P.paddleHalf;

    if (this.phase !== 'juego' && this.phase !== 'predecible') return;
    b.x += b.vx * dt;
    b.y += b.vy * dt;
    if (b.y < 0) { b.y = -b.y; b.vy = -b.vy; }
    if (b.y > 1) { b.y = 2 - b.y; b.vy = -b.vy; }
    if (b.x > 1) { b.x = 2 - b.x; b.vx = -b.vx; }
    if (b.x <= 0) {
      if (Math.abs(b.y - this.paddle) <= P.paddleHalf + 0.012) {
        b.x = -b.x;
        b.vx = Math.abs(b.vx);
        // el rebote cambia el ángulo según dónde pegó
        const off = (b.y - this.paddle) / P.paddleHalf;
        const ang = off * 0.35 * Math.PI + (this.rand() - 0.5) * 0.25;
        b.vx = P.ballSpeed * Math.cos(ang);
        b.vy = P.ballSpeed * Math.sin(ang);
        this.onHit();
      } else {
        b.x = 0;
        this.onMiss();
      }
    }
  };

  DishBrain.prototype.stimulate = function () {
    const C = CONDITIONS[this.condition];
    const r = this.rand;
    if (this.phase === 'predecible') {
      // 100 Hz en los 8 electrodos a la vez
      if (this.t % 10 === 0) for (let e = 0; e < P.nElec; e++) this.pulse(e, 1);
    } else if (this.phase === 'impredecible') {
      // 5 Hz por electrodo, momentos al azar
      for (let e = 0; e < P.nElec; e++) if (r() < 0.005) this.pulse(e, 1);
      if (C.jitter) this.jitterWeights();
    } else if (this.phase === 'juego' && C.sensory) {
      if (this.t >= this.nextPulse) {
        this.pulse(this.placeElectrode(), 1);
        this.nextPulse = this.t + Math.round(1000 / this.stimFrequency());
      }
    }
  };

  // Avanza 1 ms.
  DishBrain.prototype.step = function () {
    const NS = this.NS, NM = this.NM, N = this.N;
    const v = this.v, u = this.u, inp = this.inp, sp = this.spiked, r = this.rand;
    const W = this.W, E = this.E, xPre = this.xPre, yPost = this.yPost;

    if (this.phase !== 'juego' && this.t >= this.phaseEnd) {
      if (this.phase === 'predecible') this.phase = 'juego';
      else this.serve();
    }

    this.stimulate();

    // ruido de fondo
    for (let i = 0; i < NS; i++) inp[i] += P.noiseSens * r.gauss();
    for (let j = NS; j < N; j++) inp[j] += P.noiseMotor * r.gauss();

    // Izhikevich RS, dos medios pasos de 0.5 ms
    let nUp = 0, nDown = 0;
    for (let i = 0; i < N; i++) {
      let vi = v[i], ui = u[i];
      const I = inp[i];
      vi += 0.5 * (0.04 * vi * vi + 5 * vi + 140 - ui + I);
      vi += 0.5 * (0.04 * vi * vi + 5 * vi + 140 - ui + I);
      ui += 0.02 * (0.2 * vi - ui);
      if (vi >= 30) {
        sp[i] = 1; vi = -65; ui += 8;
      } else sp[i] = 0;
      v[i] = vi; u[i] = ui; inp[i] = 0;
    }

    const decT = Math.exp(-1 / P.tauTrace);
    for (let i = 0; i < NS; i++) xPre[i] *= decT;
    for (let j = 0; j < NM; j++) yPost[j] *= decT;

    for (let i = 0; i < NS; i++) {
      if (!sp[i]) continue;
      this.elecActivity[Math.floor(i / P.perElec)] += 1;
      if (this.spikeLog.length < 20000) this.spikeLog.push(this.t, i);
      const o = i * NM;
      for (let j = 0; j < NM; j++) {
        inp[NS + j] += W[o + j];
        E[o + j] -= P.aMinus * yPost[j];      // post antes que pre: depresión
      }
      xPre[i] += 1;
    }
    for (let j = 0; j < NM; j++) {
      if (!sp[NS + j]) continue;
      if (this.spikeLog.length < 20000) this.spikeLog.push(this.t, NS + j);
      this.regionActivity[this.region[j]] += 1;
      if (this.isUp[j]) nUp++; else nDown++;
      for (let i = 0; i < NS; i++) E[i * NM + j] += P.aPlus * xPre[i];   // pre antes que post: potenciación
      yPost[j] += 1;
    }
    // inhibición lateral entre arriba y abajo
    if (nUp || nDown) {
      for (let j = 0; j < NM; j++) {
        inp[NS + j] -= P.lateralInh * (this.isUp[j] ? nDown : nUp);
      }
    }

    if (this.t % 10 === 0) {
      const dE = Math.exp(-10 / P.tauElig);
      for (let q = 0; q < E.length; q++) E[q] *= dE;
    }

    const dR = Math.exp(-1 / P.tauRate);
    this.rateUp = this.rateUp * dR + nUp;
    this.rateDown = this.rateDown * dR + nDown;

    this.updateGame(0.001);
    this.t++;
  };

  DishBrain.prototype.run = function (ms) {
    for (let k = 0; k < ms; k++) this.step();
  };

  // Resumen de rallies en ventanas de tiempo (minutos de simulación).
  DishBrain.prototype.summary = function (fromMs, toMs) {
    const rs = this.rallies.filter(function (x) { return x.t >= fromMs && x.t < toMs; });
    if (!rs.length) return { n: 0, hitsPerRally: 0, aces: 0, long: 0 };
    let h = 0, a = 0, l = 0;
    for (const x of rs) { h += x.hits; if (x.hits === 0) a++; if (x.hits >= 3) l++; }
    return { n: rs.length, hitsPerRally: h / rs.length, aces: a / rs.length, long: l / rs.length };
  };

  // Cuánto "entiende" la red: preferencia arriba-abajo por electrodo (−1 a 1).
  DishBrain.prototype.preference = function () {
    const NM = this.NM, out = new Float32Array(P.nElec);
    for (let e = 0; e < P.nElec; e++) {
      let up = 0, down = 0;
      for (let k = 0; k < P.perElec; k++) {
        const o = (e * P.perElec + k) * NM;
        for (let j = 0; j < NM; j++) { if (this.isUp[j]) up += this.W[o + j]; else down += this.W[o + j]; }
      }
      out[e] = (up - down) / (up + down || 1);
    }
    return out;
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = DishBrain;
  else root.DishBrain = DishBrain;
})(typeof window !== 'undefined' ? window : this);
