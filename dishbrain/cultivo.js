/*
 * Cultivo: simulación física de neuronas sobre la placa de PongBrain.
 *
 * Nada está puesto a mano:
 *  - las células caen en lugares al azar sobre toda la placa y quedan pegadas;
 *  - a cada una le crece un axón, paso a paso, con ramificaciones;
 *  - una conexión (sinapsis) existe solo donde la punta de un axón pasa cerca
 *    del cuerpo de otra célula, y su demora sale del largo del camino;
 *  - los electrodos estimulan a las células que tienen encima: la pelota y la
 *    paleta excitan a las células que están debajo de ellas (el espejo);
 *  - las células que cayeron sobre las zonas SUBE y BAJA mueven la paleta;
 *  - aprender cambia la fuerza de esas sinapsis físicas.
 *
 * Unidades: milímetros sobre la placa (la placa del aparato está ampliada) y
 * milisegundos para la actividad. Coordenadas como en el modelo de Blender:
 * x va de arriba (−) a abajo (+) en la pantalla, y de izquierda (−) a derecha (+).
 */
(function (root) {
  'use strict';

  function rng(seed) {
    let a = seed >>> 0;
    const f = function () {
      a = (a + 0x6d2b79f5) >>> 0; let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    let spare = null;
    f.gauss = function () {
      if (spare !== null) { const s = spare; spare = null; return s; }
      let u = 0; while (u === 0) u = f(); const v = f(), r = Math.sqrt(-2 * Math.log(u));
      spare = r * Math.sin(2 * Math.PI * v); return r * Math.cos(2 * Math.PI * v);
    };
    return f;
  }

  const P = {
    // geometría de la placa y sus zonas (mm, del modelo de Blender)
    plate: { x0: -34.6, x1: 34.6, y0: -69.0, y1: 37.9 },
    court: { x0: -34.6, x1: 34.6, y0: -45.8, y1: 37.9 },
    padY: -39.45, advY: 30.85,
    up:   { x0: -33.8, x1: 0.0,  y0: -67.5, y1: -52.5 },   // ventana bajo SUBE
    down: { x0: 0.0,   x1: 33.8, y0: -67.5, y1: -52.5 },   // ventana bajo BAJA
    // siembra y crecimiento
    nCells: 600, fracInh: 0.2,
    growDays: 21, stepsPerDay: 24,
    growStep: 0.35,          // mm que avanza la punta por paso
    persist: 0.82,           // cuánto mantiene la dirección
    branchP: 0.015, maxCones: 5,
    axonMaxE: 46, axonMaxI: 7,   // largo máximo del axón (mm)
    reachE: 1.3, reachI: 1.0,    // radio de las dendritas de la célula que recibe (mm)
    maxSynOut: 70,
    speed: 2.5,              // mm por ms: velocidad de la señal por el axón (escala ampliada)
    // actividad
    wE: [2.0, 6.0], wI: [3.0, 7.0], wMax: 14,
    inTotalE: 40, inTotalI: 60,   // tope de entrada total por célula (escalado sináptico)
    noise: 3.4, stimI: 24, stimP: 0.9,
    ballR: 4.5, padR: 3.0,
    // aprendizaje
    tauTrace: 6, tauElig: 900, aPlus: 1.0, aMinus: 0.25, lr: 0.6,
    expectRate: 0.05, missFloor: 0.3, jitter: 0.08,
    // juego (igual que el motor original)
    paddleHalf: 0.18, paddleGain: 0.08, paddleVmax: 2, ballSpeed: 0.62, tauRate: 90,
    missMs: 4000, hitMs: 100,
  };
  const CONDITIONS = {
    estimulo:    { label: 'Estímulo',     sensory: true,  hit: 'predecible', miss: 'impredecible', modHit: 1, modMiss: -1,   jitter: true },
    silencio:    { label: 'Silencio',     sensory: true,  hit: 'nada',       miss: 'silencio',     modHit: 0, modMiss: -0.4, jitter: false },
    sinfeedback: { label: 'Sin feedback', sensory: true,  hit: 'nada',       miss: 'nada',         modHit: 0, modMiss: 0,    jitter: false },
    reposo:      { label: 'Reposo',       sensory: false, hit: 'nada',       miss: 'nada',         modHit: 0, modMiss: 0,    jitter: false },
  };

  function Cultivo(opts) {
    opts = opts || {};
    this.seed = opts.seed == null ? 1 : opts.seed;
    this.condition = opts.condition || 'estimulo';
    this.r = rng(this.seed);
    this.seedCells();
    this.growth = { step: 0, total: P.growDays * P.stepsPerDay, done: false };
    this.initGrowth();
  }
  Cultivo.PARAMS = P; Cultivo.CONDITIONS = CONDITIONS;

  // ---------- 1. siembra: caen al azar y quedan pegadas
  Cultivo.prototype.seedCells = function () {
    const r = this.r, n = P.nCells, pl = P.plate;
    this.N = n;
    this.cx = new Float32Array(n); this.cy = new Float32Array(n);
    this.inh = new Uint8Array(n); this.size = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      this.cx[i] = pl.x0 + r() * (pl.x1 - pl.x0);
      this.cy[i] = pl.y0 + r() * (pl.y1 - pl.y0);
      this.inh[i] = r() < P.fracInh ? 1 : 0;
      this.size[i] = 0.35 + r() * 0.25;
    }
    // grilla espacial para buscar vecinas
    this.gcell = 2.0;
    this.gw = Math.ceil((pl.x1 - pl.x0) / this.gcell) + 1; this.gh = Math.ceil((pl.y1 - pl.y0) / this.gcell) + 1;
    this.grid = Array.from({ length: this.gw * this.gh }, () => []);
    for (let i = 0; i < n; i++) this.grid[this.gidx(this.cx[i], this.cy[i])].push(i);
    // zona de cada célula
    const inZ = (z, x, y) => x >= z.x0 && x < z.x1 && y >= z.y0 && y < z.y1;
    this.zone = new Uint8Array(n);   // 0 nada, 1 cancha, 2 SUBE, 3 BAJA
    for (let i = 0; i < n; i++) {
      const x = this.cx[i], y = this.cy[i];
      this.zone[i] = inZ(P.up, x, y) ? 2 : inZ(P.down, x, y) ? 3 : inZ(P.court, x, y) ? 1 : 0;
    }
  };
  Cultivo.prototype.gidx = function (x, y) {
    const pl = P.plate;
    const gx = Math.max(0, Math.min(this.gw - 1, Math.floor((x - pl.x0) / this.gcell)));
    const gy = Math.max(0, Math.min(this.gh - 1, Math.floor((y - pl.y0) / this.gcell)));
    return gy * this.gw + gx;
  };
  Cultivo.prototype.near = function (x, y, rad, fn) {
    const pl = P.plate, c = this.gcell;
    const gx0 = Math.max(0, Math.floor((x - rad - pl.x0) / c)), gx1 = Math.min(this.gw - 1, Math.floor((x + rad - pl.x0) / c));
    const gy0 = Math.max(0, Math.floor((y - rad - pl.y0) / c)), gy1 = Math.min(this.gh - 1, Math.floor((y + rad - pl.y0) / c));
    const r2 = rad * rad;
    for (let gy = gy0; gy <= gy1; gy++) for (let gx = gx0; gx <= gx1; gx++) {
      for (const j of this.grid[gy * this.gw + gx]) {
        const dx = this.cx[j] - x, dy = this.cy[j] - y;
        if (dx * dx + dy * dy <= r2) fn(j, dx * dx + dy * dy);
      }
    }
  };

  // ---------- 2. crecimiento de axones y formación de sinapsis
  Cultivo.prototype.initGrowth = function () {
    const r = this.r;
    this.seg = { x0: [], y0: [], x1: [], y1: [], cell: [], path: [], born: [] };   // cada tramo de axón
    this.cones = [];
    this.syn = { pre: [], post: [], x: [], y: [], delay: [], w: [], born: [] };
    this.synSet = new Set();
    this.outCount = new Uint16Array(this.N); this.axLen = new Float32Array(this.N);
    for (let i = 0; i < this.N; i++) {
      const a = r() * Math.PI * 2;
      this.cones.push({ cell: i, x: this.cx[i], y: this.cy[i], dx: Math.cos(a), dy: Math.sin(a), path: 0, alive: true });
    }
  };
  Cultivo.prototype.growStep = function () {
    if (this.growth.done) return;
    const r = this.r, pl = P.plate, step = P.growStep;
    const born = this.growth.step;
    const newCones = [];
    for (const c of this.cones) {
      if (!c.alive) continue;
      const i = c.cell, max = this.inh[i] ? P.axonMaxI : P.axonMaxE;
      if (this.axLen[i] >= max || this.outCount[i] >= P.maxSynOut) { c.alive = false; continue; }
      // dirección: sigue la que traía, con un poco de azar
      const a = Math.atan2(c.dy, c.dx) + r.gauss() * (1 - P.persist) * 1.6;
      let nx = c.x + Math.cos(a) * step, ny = c.y + Math.sin(a) * step;
      // los bordes de la placa la frenan y la desvían
      if (nx < pl.x0 || nx > pl.x1) { c.dx = -Math.cos(a); nx = c.x; } else c.dx = Math.cos(a);
      if (ny < pl.y0 || ny > pl.y1) { c.dy = -Math.sin(a); ny = c.y; } else c.dy = Math.sin(a);
      const s = this.seg; s.x0.push(c.x); s.y0.push(c.y); s.x1.push(nx); s.y1.push(ny);
      s.cell.push(i); c.path += step; s.path.push(c.path); s.born.push(born);
      this.axLen[i] += step; c.x = nx; c.y = ny;
      // ¿toca a otra célula? → sinapsis en ese punto
      const reachOf = (j) => (this.inh[j] ? P.reachI : P.reachE);
      this.near(nx, ny, P.reachE, (j, d2) => {
        if (j === i || d2 > reachOf(j) * reachOf(j)) return;
        const key = i * 4096 + j;
        if (this.synSet.has(key) || this.outCount[i] >= P.maxSynOut) return;
        this.synSet.add(key); this.outCount[i]++;
        const sy = this.syn; sy.pre.push(i); sy.post.push(j); sy.x.push(nx); sy.y.push(ny); sy.born.push(born);
        sy.delay.push(Math.max(1, Math.min(31, Math.round(1 + c.path / P.speed))));
        const wr = this.inh[i] ? P.wI : P.wE;
        sy.w.push(wr[0] + r() * (wr[1] - wr[0]));
      });
      // ramificación
      if (r() < P.branchP && this.cones.length + newCones.length < this.N * P.maxCones) {
        const b = (r() < 0.5 ? 1 : -1) * (0.5 + r() * 0.6);
        newCones.push({ cell: i, x: nx, y: ny, dx: Math.cos(a + b), dy: Math.sin(a + b), path: c.path, alive: true });
      }
    }
    this.cones.push(...newCones);
    this.growth.step++;
    if (this.growth.step >= this.growth.total) { this.growth.done = true; this.buildNetwork(); }
  };
  Cultivo.prototype.growAll = function () { while (!this.growth.done) this.growStep(); };

  // ---------- 3. red activa
  Cultivo.prototype.buildNetwork = function () {
    const n = this.N, sy = this.syn, S = sy.pre.length;
    this.S = S;
    this.pre = Int32Array.from(sy.pre); this.post = Int32Array.from(sy.post);
    this.delay = Uint8Array.from(sy.delay); this.W = Float32Array.from(sy.w);
    this.E = new Float32Array(S);
    const outs = Array.from({ length: n }, () => []), ins = Array.from({ length: n }, () => []);
    for (let s = 0; s < S; s++) { outs[this.pre[s]].push(s); ins[this.post[s]].push(s); }
    this.outS = outs.map((a) => Int32Array.from(a)); this.inS = ins.map((a) => Int32Array.from(a));
    // escalado sináptico: cada célula ajusta el total que recibe, excitatorio e inhibitorio,
    // para no quedar ni muda ni en ráfagas (las neuronas reales regulan esto)
    const sumE = new Float32Array(n), sumI = new Float32Array(n);
    for (let s = 0; s < S; s++) (this.inh[this.pre[s]] ? sumI : sumE)[this.post[s]] += this.W[s];
    for (let s = 0; s < S; s++) {
      const j = this.post[s], inh = this.inh[this.pre[s]];
      const tot = inh ? sumI[j] : sumE[j], target = inh ? P.inTotalI : P.inTotalE;
      if (tot > target) this.W[s] = Math.min(P.wMax, this.W[s] * target / tot);
    }
    this.inSum = new Float32Array(n);
    for (let s = 0; s < S; s++) if (!this.inh[this.pre[s]]) this.inSum[this.post[s]] += this.W[s];
    this.v = new Float32Array(n).fill(-65); this.u = new Float32Array(n);
    this.a = new Float32Array(n); this.b = new Float32Array(n); this.c = new Float32Array(n); this.d = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      if (this.inh[i]) { this.a[i] = 0.1; this.b[i] = 0.2; this.c[i] = -65; this.d[i] = 2; }
      else { this.a[i] = 0.02; this.b[i] = 0.2; this.c[i] = -65; this.d[i] = 8; }
      this.u[i] = this.b[i] * this.v[i];
    }
    this.D = 32; this.buf = new Float32Array(this.D * n);
    this.inp = new Float32Array(n); this.spiked = new Uint8Array(n);
    this.xPre = new Float32Array(n); this.yPost = new Float32Array(n);
    this.lastSpike = new Float64Array(n).fill(-1e9);
    this.t = 0; this.spikeLog = [];
    this.upCells = []; this.downCells = [];
    for (let i = 0; i < n; i++) { if (this.zone[i] === 2) this.upCells.push(i); if (this.zone[i] === 3) this.downCells.push(i); }
    this.rateUp = 0; this.rateDown = 0;
    this.paddle = 0.5; this.phase = 'juego'; this.phaseEnd = 0; this.nextPulse = 0;
    this.rally = 0; this.rallies = []; this.totalHits = 0; this.totalMisses = 0; this.expect = 0.2;
    this.stimLog = [];   // [t, x, y, radio] de cada pulso, para dibujarlo
    this.serve();
  };

  Cultivo.prototype.setCondition = function (c) { this.condition = c; };
  Cultivo.prototype.serve = function () {
    const r = this.r; this.ball = { x: 1, y: 0.15 + 0.7 * r() };
    const ang = (r() * 0.9 - 0.45) * Math.PI / 2;
    this.ball.vx = -P.ballSpeed * Math.cos(ang); this.ball.vy = P.ballSpeed * Math.sin(ang);
    this.phase = 'juego';
  };
  // de coordenadas del juego a la placa (el espejo)
  Cultivo.prototype.ballOnPlate = function () {
    const c = P.court;
    return { x: c.x0 + this.ball.y * (c.x1 - c.x0), y: P.padY + this.ball.x * (P.advY - P.padY) };
  };
  Cultivo.prototype.paddleOnPlate = function () {
    const c = P.court; return { x: c.x0 + this.paddle * (c.x1 - c.x0), y: P.padY, half: P.paddleHalf * (c.x1 - c.x0) };
  };
  Cultivo.prototype.stimDisk = function (x, y, rad) {
    const r = this.r;
    this.near(x, y, rad, (j) => { if (r() < P.stimP) this.inp[j] += P.stimI; });
    if (this.stimLog.length < 4000) this.stimLog.push(this.t, x, y, rad);
  };
  Cultivo.prototype.stimPaddle = function () {
    const p = this.paddleOnPlate(), r = this.r;
    for (let x = p.x - p.half; x <= p.x + p.half; x += P.padR) {
      this.near(x, p.y, P.padR, (j) => { if (r() < P.stimP) this.inp[j] += P.stimI; });
    }
    if (this.stimLog.length < 4000) this.stimLog.push(this.t, p.x, p.y, -p.half);
  };
  Cultivo.prototype.stimulate = function () {
    const C = CONDITIONS[this.condition], r = this.r, c = P.court;
    if (this.phase === 'predecible') {
      if (this.t % 10 === 0) for (let k = 0; k < 8; k++) this.stimDisk(c.x0 + (k + 0.5) * (c.x1 - c.x0) / 8, (c.y0 + c.y1) / 2, 40);
    } else if (this.phase === 'impredecible') {
      if (r() < 0.04) this.stimDisk(c.x0 + r() * (c.x1 - c.x0), c.y0 + r() * (c.y1 - c.y0), 6);
      if (C.jitter && r() < 0.5) { const s = Math.floor(r() * this.S); if (!this.inh[this.pre[s]]) this.W[s] = Math.max(0, Math.min(P.wMax, this.W[s] + r.gauss() * P.jitter)); }
    } else if (this.phase === 'juego' && C.sensory && this.t >= this.nextPulse) {
      const b = this.ballOnPlate(); this.stimDisk(b.x, b.y, P.ballR); this.stimPaddle();
      const f = 4 + 36 * Math.min(1, Math.max(0, 1 - this.ball.x));
      this.nextPulse = this.t + Math.round(1000 / f);
    }
  };
  Cultivo.prototype.modulate = function (m) {
    if (m !== 0) {
      const W = this.W, E = this.E, k = P.lr * m;
      for (let s = 0; s < this.S; s++) if (!this.inh[this.pre[s]]) W[s] = Math.max(0, Math.min(P.wMax, W[s] + k * E[s]));
      // escalado sináptico por célula receptora
      const sum = new Float32Array(this.N);
      for (let s = 0; s < this.S; s++) if (!this.inh[this.pre[s]]) sum[this.post[s]] += W[s];
      for (let s = 0; s < this.S; s++) if (!this.inh[this.pre[s]] && sum[this.post[s]] > 0) W[s] = Math.min(P.wMax, W[s] * this.inSum[this.post[s]] / sum[this.post[s]]);
    }
    this.E.fill(0);
  };
  Cultivo.prototype.onHit = function () {
    const C = CONDITIONS[this.condition];
    this.rally++; this.totalHits++;
    this.modulate(C.modHit * (1 - this.expect)); this.expect += (1 - this.expect) * P.expectRate;
    if (C.hit === 'predecible') { this.phase = 'predecible'; this.phaseEnd = this.t + P.hitMs; }
  };
  Cultivo.prototype.onMiss = function () {
    const C = CONDITIONS[this.condition];
    this.totalMisses++; this.rallies.push({ t: this.t, hits: this.rally }); this.rally = 0;
    this.modulate(C.modMiss * (this.expect + P.missFloor)); this.expect += (0 - this.expect) * P.expectRate;
    if (C.miss === 'impredecible' || C.miss === 'silencio') { this.phase = C.miss; this.phaseEnd = this.t + P.missMs; }
    else this.serve();
  };
  Cultivo.prototype.updateGame = function (dt) {
    const b = this.ball;
    let vel = P.paddleGain * (this.rateDown - this.rateUp);
    vel = Math.max(-P.paddleVmax, Math.min(P.paddleVmax, vel));
    this.paddle = Math.max(P.paddleHalf, Math.min(1 - P.paddleHalf, this.paddle + vel * dt));
    if (this.phase !== 'juego' && this.phase !== 'predecible') return;
    b.x += b.vx * dt; b.y += b.vy * dt;
    if (b.y < 0) { b.y = -b.y; b.vy = -b.vy; } if (b.y > 1) { b.y = 2 - b.y; b.vy = -b.vy; }
    if (b.x > 1) { b.x = 2 - b.x; b.vx = -b.vx; }
    if (b.x <= 0) {
      if (Math.abs(b.y - this.paddle) <= P.paddleHalf + 0.012) {
        const off = (b.y - this.paddle) / P.paddleHalf, ang = off * 0.35 * Math.PI + (this.r() - 0.5) * 0.25;
        b.x = -b.x; b.vx = P.ballSpeed * Math.cos(ang); b.vy = P.ballSpeed * Math.sin(ang); this.onHit();
      } else { b.x = 0; this.onMiss(); }
    }
  };
  Cultivo.prototype.step = function () {
    if (!this.growth.done) return;
    const n = this.N, r = this.r, D = this.D, slot = (this.t % D) * n;
    if (this.phase !== 'juego' && this.t >= this.phaseEnd) { if (this.phase === 'predecible') this.phase = 'juego'; else this.serve(); }
    this.stimulate();
    const v = this.v, u = this.u, inp = this.inp, buf = this.buf, sp = this.spiked;
    let nUp = 0, nDown = 0;
    for (let i = 0; i < n; i++) {
      const I = inp[i] + buf[slot + i] + P.noise * r.gauss();
      buf[slot + i] = 0; inp[i] = 0;
      let vi = v[i], ui = u[i];
      vi += 0.5 * (0.04 * vi * vi + 5 * vi + 140 - ui + I);
      vi += 0.5 * (0.04 * vi * vi + 5 * vi + 140 - ui + I);
      ui += this.a[i] * (this.b[i] * vi - ui);
      if (vi >= 30) { sp[i] = 1; vi = this.c[i]; ui += this.d[i]; } else sp[i] = 0;
      v[i] = vi; u[i] = ui;
    }
    const dT = Math.exp(-1 / P.tauTrace);
    for (let i = 0; i < n; i++) { this.xPre[i] *= dT; this.yPost[i] *= dT; }
    const W = this.W, E = this.E;
    for (let i = 0; i < n; i++) {
      if (!sp[i]) continue;
      this.lastSpike[i] = this.t;
      if (this.spikeLog.length < 40000) this.spikeLog.push(this.t, i);
      const neg = this.inh[i] ? -1 : 1;
      for (const s of this.outS[i]) {
        const j = this.post[s];
        buf[((this.t + this.delay[s]) % D) * n + j] += neg * W[s];
        if (!this.inh[i]) E[s] -= P.aMinus * this.yPost[j];
      }
      for (const s of this.inS[i]) if (!this.inh[this.pre[s]]) E[s] += P.aPlus * this.xPre[this.pre[s]];
      this.xPre[i] += 1; this.yPost[i] += 1;
      if (this.zone[i] === 2) nUp++; else if (this.zone[i] === 3) nDown++;
    }
    if (this.t % 10 === 0) { const dE = Math.exp(-10 / P.tauElig); for (let s = 0; s < this.S; s++) E[s] *= dE; }
    const dR = Math.exp(-1 / P.tauRate);
    this.rateUp = this.rateUp * dR + nUp * 40 / Math.max(1, this.upCells.length);
    this.rateDown = this.rateDown * dR + nDown * 40 / Math.max(1, this.downCells.length);
    this.updateGame(0.001);
    this.t++;
  };
  Cultivo.prototype.run = function (ms) { for (let k = 0; k < ms; k++) this.step(); };
  Cultivo.prototype.summary = function (a, b) {
    const rs = this.rallies.filter((x) => x.t >= a && x.t < b);
    if (!rs.length) return { n: 0, hitsPerRally: 0, aces: 0 };
    let h = 0, ac = 0; for (const x of rs) { h += x.hits; if (!x.hits) ac++; }
    return { n: rs.length, hitsPerRally: h / rs.length, aces: ac / rs.length };
  };
  // cuántas sinapsis unen la cancha con cada zona motora (directo)
  Cultivo.prototype.wiring = function () {
    const o = { total: this.S, canchaASube: 0, canchaABaja: 0, celulasSube: this.upCells.length, celulasBaja: this.downCells.length };
    for (let s = 0; s < this.S; s++) {
      const a = this.zone[this.pre[s]], b = this.zone[this.post[s]];
      if (a === 1 && b === 2) o.canchaASube++; if (a === 1 && b === 3) o.canchaABaja++;
    }
    return o;
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = Cultivo;
  else root.Cultivo = Cultivo;
})(typeof window !== 'undefined' ? window : this);
