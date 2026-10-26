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
    nCells: 1200, fracInh: 0.2,
    growDays: 21, stepsPerDay: 24,
    growStep: 0.35,          // mm que avanza la punta por paso
    persist: 0.93,           // cuánto mantiene la dirección
    branchP: 0.04, maxCones: 5,
    axonMaxE: 220, axonMaxI: 7,  // largo máximo del axón (mm, placa ampliada)
    // dendritas: ramas cortas que crecen de cada célula; la sinapsis se forma donde un axón cruza una
    dendPrimary: [4, 7], dendStep: 0.12, dendLenE: 1.9, dendLenI: 1.3, dendBranchP: 0.12, dendPersist: 0.7,
    dendSteps: 72,           // pasos de crecimiento (los primeros 3 días)
    // migración: los primeros días las células se mueven y se juntan con sus vecinas
    aggSteps: 48, aggRange: 3.2, aggPull: 0.05, aggPush: 0.6, aggNoise: 0.03, aggMax: 0.12,
    // fasciculación: una punta de axón que pasa cerca de otro axón tiende a seguirlo
    fascRange: 0.35, fascPull: 0.65,
    senseDist: 1.2, senseAngle: 0.55, turn: 0.9,    // la punta siente axones a 1,2 mm y gira hacia donde hay más
    contact: 0.09,           // mm: distancia a la que un axón que pasa toca una dendrita
    maxSynOut: 200,
    speed: 2.5,              // mm por ms: velocidad de la señal por el axón (escala ampliada)
    // actividad
    wE: [2.5, 7.0], wI: [3.0, 7.0], wMax: 14,
    inTotalE: 260, inTotalI: 520,   // tope de entrada total por célula (escalado sináptico)
    noise: 2.8, stimI: 24, stimP: 0.9,
    ballR: 4.5, padR: 3.0,
    // qué le muestran los electrodos al cultivo mientras juega:
    //  'pantalla'  la pelota, su paleta y la del adversario, cada una debajo de donde está (espejo)
    //  'pelota'    solo la pelota (como DishBrain: el lado dice dónde está, la frecuencia qué tan cerca)
    //  'relativa'  la pelota corrida según dónde está la paleta: el lado dice si está arriba o abajo de la paleta
    //  'relativa+adv'  lo anterior más la paleta del adversario
    //  'lado'      como DishBrain: siempre junto a la línea de la paleta; el lado dice si la pelota está arriba o abajo de la paleta y la frecuencia, qué tan cerca viene
    stimMode: 'pantalla',
    bandH: 14,               // alto de la franja de electrodos en modo 'lado' (mm)
    plasticMotor: false,
    // como el paper (Kagan et al. 2022): sin premio químico ni ruido en las conexiones; al fallar, un electrodo al azar
    // 5 veces por segundo durante 4 s; al acertar, todos juntos a 100 por segundo durante 0,1 s; las conexiones cambian
    // solo por STDP (lo que dispara junto se refuerza), aplicada cada 100 ms con intensidad stdpRate
    paper: true, stdpRate: 0.05,
    missStim: 2,             // la descarga al fallar es el doble de fuerte que la del juego (150 mV contra 75 mV en el paper)
    missScale: 1,            // cuánto pesa el castigo de una falla (0: solo se premian los aciertos)     // true: el premio solo cambia las conexiones que llegan a las células motoras
    // aprendizaje
    tauTrace: 6, tauElig: 900, aPlus: 1.0, aMinus: 0.25, lr: 0.6,
    expectRate: 0.05, missFloor: 0.3, jitter: 0.08,
    // juego (igual que el motor original)
    advSpeed: 0.28,          // el adversario sigue a la pelota a esta velocidad (cancha por segundo): a veces no llega
    paddleHalf: 0.18, paddleGain: 0.3, paddleVmax: 2, ballSpeed: 0.62, tauRate: 90,
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
    this.den = { x0: [], y0: [], x1: [], y1: [], cell: [], path: [], born: [] };   // cada tramo de dendrita
    this.dgrid = new Map();   // tramos de dendrita por casilla de 1 mm
    this.cones = []; this.dcones = [];
    this.syn = { pre: [], post: [], x: [], y: [], delay: [], w: [], born: [] };
    this.synSet = new Set();
    this.outCount = new Uint16Array(this.N); this.axLen = new Float32Array(this.N);
    this.agrid = new Map();   // tramos de axón por casilla de 1 mm (para que otros axones los sigan)
  };
  // al terminar la migración, cada célula empieza a crecer desde donde quedó
  Cultivo.prototype.startNeurites = function () {
    const r = this.r;
    for (let i = 0; i < this.N; i++) {
      const a = r() * Math.PI * 2;
      this.cones.push({ cell: i, x: this.cx[i], y: this.cy[i], dx: Math.cos(a), dy: Math.sin(a), path: 0, alive: true });
      const k = P.dendPrimary[0] + Math.floor(r() * (P.dendPrimary[1] - P.dendPrimary[0] + 1));
      const maxL = (this.inh[i] ? P.dendLenI : P.dendLenE) * (0.7 + r() * 0.6);
      for (let q = 0; q < k; q++) {
        const b = (q / k) * Math.PI * 2 + r() * 0.8;
        const r0 = this.size[i];   // las dendritas salen del borde del cuerpo
        this.dcones.push({ cell: i, x: this.cx[i] + Math.cos(b) * r0, y: this.cy[i] + Math.sin(b) * r0, a: b, path: r0, max: maxL, alive: true });
      }
    }
  };
  // migración: atracción entre vecinas cercanas, empuje si se pisan, y un poco de azar
  Cultivo.prototype.migrate = function () {
    const r = this.r, n = this.N, pl = P.plate, fx = new Float32Array(n), fy = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      this.near(this.cx[i], this.cy[i], P.aggRange, (j, d2) => {
        if (j === i || d2 === 0) return;
        const d = Math.sqrt(d2), ux = (this.cx[j] - this.cx[i]) / d, uy = (this.cy[j] - this.cy[i]) / d;
        const touch = (this.size[i] + this.size[j]) * 1.15;
        const f = d < touch ? -P.aggPush * (touch - d) : P.aggPull * (1 - d / P.aggRange);
        fx[i] += f * ux; fy[i] += f * uy;
      });
    }
    for (let i = 0; i < n; i++) {
      let vx = fx[i] + r.gauss() * P.aggNoise, vy = fy[i] + r.gauss() * P.aggNoise;
      const v = Math.hypot(vx, vy); if (v > P.aggMax) { vx *= P.aggMax / v; vy *= P.aggMax / v; }
      this.cx[i] = Math.max(pl.x0 + 0.5, Math.min(pl.x1 - 0.5, this.cx[i] + vx));
      this.cy[i] = Math.max(pl.y0 + 0.5, Math.min(pl.y1 - 0.5, this.cy[i] + vy));
    }
    this.reindexCells();
  };
  Cultivo.prototype.reindexCells = function () {
    for (const g of this.grid) g.length = 0;
    for (let i = 0; i < this.N; i++) this.grid[this.gidx(this.cx[i], this.cy[i])].push(i);
    const inZ = (z, x, y) => x >= z.x0 && x < z.x1 && y >= z.y0 && y < z.y1;
    for (let i = 0; i < this.N; i++) {
      const x = this.cx[i], y = this.cy[i];
      this.zone[i] = inZ(P.up, x, y) ? 2 : inZ(P.down, x, y) ? 3 : inZ(P.court, x, y) ? 1 : 0;
    }
  };
  Cultivo.prototype.nearestAxon = function (x, y, self) {
    const sg = this.seg, R2 = P.fascRange * P.fascRange;
    let best = null, bd = R2, seen = 0;
    const gx = Math.floor(x), gy = Math.floor(y);
    for (let ax = gx - 1; ax <= gx + 1; ax++) for (let ay = gy - 1; ay <= gy + 1; ay++) {
      const list = this.agrid.get(ax * 1000 + ay); if (!list) continue;
      for (let q = list.length - 1; q >= 0 && seen < 24; q--, seen++) {
        const k = list[q]; if (sg.cell[k] === self) continue;
        const vx = sg.x1[k] - sg.x0[k], vy = sg.y1[k] - sg.y0[k], L2 = vx * vx + vy * vy || 1;
        let t = ((x - sg.x0[k]) * vx + (y - sg.y0[k]) * vy) / L2; t = t < 0 ? 0 : t > 1 ? 1 : t;
        const ex = sg.x0[k] + t * vx - x, ey = sg.y0[k] + t * vy - y, d2 = ex * ex + ey * ey;
        if (d2 < bd) { bd = d2; const L = Math.sqrt(L2); best = { dx: vx / L, dy: vy / L }; }
      }
    }
    return best;
  };
    Cultivo.prototype.dkey = function (x, y) { return Math.floor(x) * 1000 + Math.floor(y); };
  // distancia al cuadrado entre dos tramos (para saber si un axón toca una dendrita)
  function segDist2(ax, ay, bx, by, cx, cy, dx, dy) {
    const o = (px, py, qx, qy, rx, ry) => (qx - px) * (ry - py) - (qy - py) * (rx - px);
    const d1 = o(ax, ay, bx, by, cx, cy), d2 = o(ax, ay, bx, by, dx, dy), d3 = o(cx, cy, dx, dy, ax, ay), d4 = o(cx, cy, dx, dy, bx, by);
    if (((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0))) return 0;
    const ps = (px, py, x0, y0, x1, y1) => {
      const vx = x1 - x0, vy = y1 - y0, L = vx * vx + vy * vy;
      let t = L ? ((px - x0) * vx + (py - y0) * vy) / L : 0; t = t < 0 ? 0 : t > 1 ? 1 : t;
      const ex = x0 + t * vx - px, ey = y0 + t * vy - py; return ex * ex + ey * ey;
    };
    return Math.min(ps(ax, ay, cx, cy, dx, dy), ps(bx, by, cx, cy, dx, dy), ps(cx, cy, ax, ay, bx, by), ps(dx, dy, ax, ay, bx, by));
  }
  Cultivo.prototype.growDendrites = function (born) {
    const r = this.r, d = this.den, st = P.dendStep, extra = [];
    for (const c of this.dcones) {
      if (!c.alive) continue;
      if (c.path >= c.max) { c.alive = false; continue; }
      c.a += r.gauss() * (1 - P.dendPersist) * 1.2;
      const nx = c.x + Math.cos(c.a) * st, ny = c.y + Math.sin(c.a) * st;
      const pl = P.plate;
      if (nx < pl.x0 || nx > pl.x1 || ny < pl.y0 || ny > pl.y1) { c.alive = false; continue; }   // fuera de la placa no crece
      const k = d.x0.length;
      d.x0.push(c.x); d.y0.push(c.y); d.x1.push(nx); d.y1.push(ny); d.cell.push(c.cell); c.path += st; d.path.push(c.path); d.born.push(born);
      const key = this.dkey((c.x + nx) / 2, (c.y + ny) / 2);
      let cell = this.dgrid.get(key); if (!cell) { cell = []; this.dgrid.set(key, cell); } cell.push(k);
      c.x = nx; c.y = ny;
      if (r() < P.dendBranchP) {
        const b = (r() < 0.5 ? 1 : -1) * (0.4 + r() * 0.5);
        extra.push({ cell: c.cell, x: nx, y: ny, a: c.a + b, path: c.path, max: c.max, alive: true });
        c.a -= b * 0.5;
      }
    }
    this.dcones.push(...extra);
  };
  Cultivo.prototype.growStep = function () {
    if (this.growth.done) return;
    const r = this.r, pl = P.plate, step = P.growStep;
    const born = this.growth.step;
    if (born < P.aggSteps) { this.migrate(); this.growth.step++; return; }
    if (born === P.aggSteps) this.startNeurites();
    if (born - P.aggSteps < P.dendSteps) this.growDendrites(born);
    const newCones = [], d = this.den, c2 = P.contact * P.contact;
    for (const c of this.cones) {
      if (!c.alive) continue;
      const i = c.cell, max = this.inh[i] ? P.axonMaxI : P.axonMaxE;
      if (this.axLen[i] >= max || this.outCount[i] >= P.maxSynOut) { c.alive = false; continue; }
      // dirección: sigue la que traía, con un poco de azar
      // la punta se adhiere a otros axones: mira adelante, a la izquierda y a la derecha, y gira hacia donde hay más.
      // más axones atraen más axones, y así se forman cordones (como en un moho mucilaginoso)
      let gx = c.dx, gy = c.dy;
      const f = this.nearestAxon(c.x, c.y, i);
      if (f) { const sg = f.dx * gx + f.dy * gy >= 0 ? 1 : -1; gx = gx * (1 - P.fascPull) + sg * f.dx * P.fascPull; gy = gy * (1 - P.fascPull) + sg * f.dy * P.fascPull; }
      let a = Math.atan2(gy, gx);
      const dens = (ang) => { const px = c.x + Math.cos(ang) * P.senseDist, py = c.y + Math.sin(ang) * P.senseDist; const l = this.agrid.get(Math.floor(px) * 1000 + Math.floor(py)); return l ? l.length : 0; };
      const dl = dens(a + P.senseAngle), dc = dens(a), dr = dens(a - P.senseAngle);
      if (dl > dc && dl >= dr) a += P.turn * Math.min(1, (dl - dc) / (dc + 4));
      else if (dr > dc && dr > dl) a -= P.turn * Math.min(1, (dr - dc) / (dc + 4));
      a += r.gauss() * (1 - P.persist) * 1.6;
      const nx = c.x + Math.cos(a) * step, ny = c.y + Math.sin(a) * step;
      // el borde de la placa la frena: ahí deja de crecer (no rebota ni se amontona)
      if (nx < pl.x0 || nx > pl.x1 || ny < pl.y0 || ny > pl.y1) { c.alive = false; continue; }
      c.dx = Math.cos(a); c.dy = Math.sin(a);
      const s = this.seg; s.x0.push(c.x); s.y0.push(c.y); s.x1.push(nx); s.y1.push(ny);
      s.cell.push(i); c.path += step; s.path.push(c.path); s.born.push(born);
      { const kk = s.x0.length - 1, key = Math.floor((c.x + nx) / 2) * 1000 + Math.floor((c.y + ny) / 2);
        let cellList = this.agrid.get(key); if (!cellList) { cellList = []; this.agrid.set(key, cellList); } cellList.push(kk); }
      this.axLen[i] += step;
      // ¿el axón cruza una dendrita de otra célula? → sinapsis justo ahí
      const gx0 = Math.floor(Math.min(c.x, nx) - 0.2), gx1 = Math.floor(Math.max(c.x, nx) + 0.2);
      const gy0 = Math.floor(Math.min(c.y, ny) - 0.2), gy1 = Math.floor(Math.max(c.y, ny) + 0.2);
      for (let gx = gx0; gx <= gx1; gx++) for (let gy = gy0; gy <= gy1; gy++) {
        const list = this.dgrid.get(gx * 1000 + gy); if (!list) continue;
        for (const k of list) {
          const j = d.cell[k]; if (j === i) continue;
          const key = i * 4096 + j;
          if (this.synSet.has(key) || this.outCount[i] >= P.maxSynOut) continue;
          if (segDist2(c.x, c.y, nx, ny, d.x0[k], d.y0[k], d.x1[k], d.y1[k]) > c2) continue;
          this.synSet.add(key); this.outCount[i]++;
          const sy = this.syn, px = (d.x0[k] + d.x1[k]) / 2, py = (d.y0[k] + d.y1[k]) / 2;
          sy.pre.push(i); sy.post.push(j); sy.x.push(px); sy.y.push(py); sy.born.push(born);
          sy.delay.push(Math.max(1, Math.min(31, Math.round(1 + (c.path + d.path[k]) / P.speed))));
          const wr = this.inh[i] ? P.wI : P.wE;
          sy.w.push(wr[0] + r() * (wr[1] - wr[0]));
        }
      }
      c.x = nx; c.y = ny;
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
    this.rally = 0; this.rallies = []; this.totalHits = 0; this.totalMisses = 0; this.goals = 0; this.expect = 0.2;
    this.adv = 0.5; this.lastEvent = '';
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
    // igual que en la pantalla: el centro de la pelota va de borde a borde menos su radio, y entre las caras de las paletas
    const br = 2.6, pt = 2.4;
    return { x: c.x0 + br + this.ball.y * (c.x1 - c.x0 - 2 * br), y: P.padY + pt + br + this.ball.x * (P.advY - P.padY - 2 * (pt + br)) };
  };
  Cultivo.prototype.paddleOnPlate = function () {
    const c = P.court; return { x: c.x0 + this.paddle * (c.x1 - c.x0), y: P.padY, half: P.paddleHalf * (c.x1 - c.x0) };
  };
  Cultivo.prototype.stimDisk = function (x, y, rad) {
    const r = this.r;
    this.near(x, y, rad, (j) => { if (r() < P.stimP) this.inp[j] += P.stimI; });
    if (this.stimLog.length < 4000) this.stimLog.push(this.t, x, y, rad);
  };
  Cultivo.prototype.advOnPlate = function () {
    const c = P.court; return { x: c.x0 + this.adv * (c.x1 - c.x0), y: P.advY, half: P.paddleHalf * (c.x1 - c.x0) };
  };
  // estimula la franja de células que hay debajo de una paleta (la propia o la del adversario)
  Cultivo.prototype.stimStrip = function (p) {
    const r = this.r;
    for (let x = p.x - p.half; x <= p.x + p.half; x += P.padR) {
      this.near(x, p.y, P.padR, (j) => { if (r() < P.stimP) this.inp[j] += P.stimI; });
    }
    if (this.stimLog.length < 4000) this.stimLog.push(this.t, p.x, p.y, -p.half);
  };
  Cultivo.prototype.stimRect = function (q) {
    const r = this.r;
    for (let i = 0; i < this.N; i++) if (this.cx[i] >= q[0] && this.cx[i] < q[1] && this.cy[i] >= q[2] && this.cy[i] < q[3] && r() < P.stimP) this.inp[i] += P.stimI;
    if (this.stimLog.length < 4000) this.stimLog.push(this.t, (q[0] + q[1]) / 2, (q[2] + q[3]) / 2, -1000 - (q[1] - q[0]) / 2);   // franja: radio < -1000
  };
  Cultivo.prototype.stimPaddle = function () { this.stimStrip(this.paddleOnPlate()); };
  // dónde apuntan los electrodos ahora (según lo que se le muestra al cultivo)
  Cultivo.prototype.targets = function () {
    const m = P.stimMode, c = P.court, b = this.ballOnPlate(), out = [];
    if (m === 'sombra') {
      // la franja de electrodos junto a la línea de la paleta, a la altura exacta de la pelota (su sombra)
      const w = (c.x1 - c.x0) / 2, cx = c.x0 + this.ball.y * (c.x1 - c.x0);
      out.push({ rect: [Math.max(c.x0, cx - w / 2), Math.min(c.x1, cx + w / 2), c.y0, c.y0 + P.bandH] });
    } else if (m === 'lado') {
      // una franja de electrodos junto a la línea de la paleta, de medio ancho de cancha, corrida hacia el lado de la pelota
      const rel = Math.max(0, Math.min(1, 0.5 + (this.ball.y - this.paddle))), w = (c.x1 - c.x0) / 2;
      const cx = c.x0 + w / 2 + rel * w;
      out.push({ rect: [cx - w / 2, cx + w / 2, c.y0, c.y0 + P.bandH] });
    } else if (m === 'relativa' || m === 'relativa+adv') {
      const rel = Math.max(0, Math.min(1, 0.5 + (this.ball.y - this.paddle)));
      out.push({ x: c.x0 + rel * (c.x1 - c.x0), y: b.y, r: P.ballR });
    } else out.push({ x: b.x, y: b.y, r: P.ballR });
    if (m === 'pantalla') out.push(this.paddleOnPlate());
    if (m === 'pantalla' || m === 'relativa+adv') out.push(this.advOnPlate());
    return out;
  };
  Cultivo.prototype.stimulate = function () {
    const C = CONDITIONS[this.condition], r = this.r, c = P.court;
    if (this.phase === 'predecible' || this.phase === 'gol') {
      if (this.t % 10 === 0) for (let k = 0; k < 8; k++) this.stimDisk(c.x0 + (k + 0.5) * (c.x1 - c.x0) / 8, (c.y0 + c.y1) / 2, 40);
    } else if (this.phase === 'impredecible') {
      if (P.paper) { if (this.t >= this.nextPulse) { const k = P.stimI; P.stimI = k * P.missStim; this.stimDisk(c.x0 + r() * (c.x1 - c.x0), c.y0 + r() * (c.y1 - c.y0), 6); P.stimI = k; this.nextPulse = this.t + 200; } }
      else if (r() < 0.04) this.stimDisk(c.x0 + r() * (c.x1 - c.x0), c.y0 + r() * (c.y1 - c.y0), 6);
      if (!P.paper && C.jitter && r() < 0.5) { const s = Math.floor(r() * this.S); if (!this.inh[this.pre[s]]) this.W[s] = Math.max(0, Math.min(P.wMax, this.W[s] + r.gauss() * P.jitter)); }
    } else if (this.phase === 'juego' && C.sensory && this.t >= this.nextPulse) {
      for (const g of this.targets()) { if (g.rect) this.stimRect(g.rect); else if (g.half != null) this.stimStrip(g); else this.stimDisk(g.x, g.y, g.r); }
      const f = 4 + 36 * Math.min(1, Math.max(0, 1 - this.ball.x));
      this.nextPulse = this.t + Math.round(1000 / f);
    }
  };
  Cultivo.prototype.modulate = function (m) {
    if (m !== 0) {
      const W = this.W, E = this.E, k = P.lr * m;
      for (let s = 0; s < this.S; s++) if (!this.inh[this.pre[s]] && (!P.plasticMotor || this.zone[this.post[s]] >= 2)) W[s] = Math.max(0, Math.min(P.wMax, W[s] + k * E[s]));
      // escalado sináptico por célula receptora
      const sum = new Float32Array(this.N);
      for (let s = 0; s < this.S; s++) if (!this.inh[this.pre[s]]) sum[this.post[s]] += W[s];
      for (let s = 0; s < this.S; s++) if (!this.inh[this.pre[s]] && sum[this.post[s]] > 0) W[s] = Math.min(P.wMax, W[s] * this.inSum[this.post[s]] / sum[this.post[s]]);
    }
    this.E.fill(0);
  };
  Cultivo.prototype.onHit = function () {
    const C = CONDITIONS[this.condition];
    this.rally++; this.totalHits++; this.lastEvent = 'golpe';
    if (!P.paper) this.modulate(C.modHit * (1 - this.expect)); this.expect += (1 - this.expect) * P.expectRate;
    if (C.hit === 'predecible') { this.phase = 'predecible'; this.phaseEnd = this.t + P.hitMs; }
  };
  // gol de las neuronas: el adversario no llegó. Mismo premio que un acierto (estímulo ordenado) y saque nuevo
  Cultivo.prototype.onGoal = function () {
    const C = CONDITIONS[this.condition];
    this.goals++; this.lastEvent = 'gol'; this.rallies.push({ t: this.t, hits: this.rally, gol: true }); this.rally = 0;
    if (!P.paper) this.modulate(C.modHit * (1 - this.expect)); this.expect += (1 - this.expect) * P.expectRate;
    if (C.hit === 'predecible') { this.phase = 'gol'; this.phaseEnd = this.t + P.hitMs; }   // la pelota se detiene mientras llega el premio
    else this.serve();
  };
  Cultivo.prototype.onMiss = function () {
    const C = CONDITIONS[this.condition];
    this.totalMisses++; this.lastEvent = 'fallo'; this.rallies.push({ t: this.t, hits: this.rally }); this.rally = 0;
    if (!P.paper) this.modulate(C.modMiss * (this.expect + P.missFloor) * P.missScale); this.expect += (0 - this.expect) * P.expectRate;
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
    // el adversario sigue a la pelota cuando viene hacia él, con velocidad limitada
    const want = b.vx > 0 ? b.y : 0.5, dv = Math.max(-P.advSpeed * dt, Math.min(P.advSpeed * dt, want - this.adv));
    this.adv = Math.max(P.paddleHalf, Math.min(1 - P.paddleHalf, this.adv + dv));
    if (b.x > 1) {
      if (Math.abs(b.y - this.adv) <= P.paddleHalf + 0.012) { b.x = 2 - b.x; b.vx = -b.vx; }
      else { b.x = 1; this.onGoal(); return; }
    }
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
    if (P.paper && this.condition !== 'reposo' && this.t % 100 === 0 && P.stdpRate > 0) { const lr = P.lr; P.lr = P.stdpRate; this.modulate(1); P.lr = lr; }
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
