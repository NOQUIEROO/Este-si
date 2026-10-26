// PongBrain: el cultivo corre acá, aparte de la imagen. Así el juego va siempre a tiempo real
// y el dibujo nunca se traba. Necesita cultivo.js cargado antes (window.Cultivo / self.Cultivo).
'use strict';
const CU = self.Cultivo, P = CU.PARAMS;
const PXA = -34.6, PXB = 34.6, PYA = -69.0, PYB = 37.9;          // la placa, en mm
const FW = 1100, FH = Math.round(FW * (PXB - PXA) / (PYB - PYA)); // tejido: ~10 px por mm
const pxmm = FW / (PYB - PYA);
const AW = 276, AH = Math.round(AW * (PXB - PXA) / (PYB - PYA));  // actividad: ~2,6 px por mm
const amm = AW / (PYB - PYA);
const GROW_REPLAY_MS = 9000;

let cul = null, cond = 'estimulo', state = 'idle', seedNo = 1;
let wallBase = 0, simBase = 0, lastPost = 0, lastTissue = 0, replayStart = 0, lastReplayPaint = 0, lastMin = -1;

// ---------- utilidades de pintura (sin depender de filtros del navegador)
function boxBlur(a, w, h, r, passes) {
  const tmp = new Float32Array(a.length), n = 2 * r + 1;
  for (let p = 0; p < passes; p++) {
    for (let y = 0; y < h; y++) {                       // horizontal a → tmp
      const o = y * w; let s = 0;
      for (let x = -r; x <= r; x++) s += a[o + Math.min(w - 1, Math.max(0, x))];
      for (let x = 0; x < w; x++) {
        tmp[o + x] = s / n;
        s += a[o + Math.min(w - 1, x + r + 1)] - a[o + Math.max(0, x - r)];
      }
    }
    for (let x = 0; x < w; x++) {                       // vertical tmp → a
      let s = 0;
      for (let y = -r; y <= r; y++) s += tmp[Math.min(h - 1, Math.max(0, y)) * w + x];
      for (let y = 0; y < h; y++) {
        a[y * w + x] = s / n;
        s += tmp[Math.min(h - 1, y + r + 1) * w + x] - tmp[Math.max(0, y - r) * w + x];
      }
    }
  }
}
// mancha suave (sin borde): 1 en el centro, 0,5 a 0,45 r, 0 en r
function prof(d) { return d < 0.45 ? 1 - (d / 0.45) * 0.5 : d < 1 ? 0.5 * (1 - (d - 0.45) / 0.55) : 0; }
function splat(F, w, h, cx, cy, r, a) {
  const x0 = Math.max(0, Math.floor(cx - r)), x1 = Math.min(w - 1, Math.ceil(cx + r));
  const y0 = Math.max(0, Math.floor(cy - r)), y1 = Math.min(h - 1, Math.ceil(cy + r));
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const d = Math.hypot(x - cx, y - cy) / r; if (d < 1) F[y * w + x] += a * prof(d);
  }
}
// franja (la paleta sobre la placa): cápsula a lo largo de x de Blender = filas de la imagen
function splatStrip(F, w, h, cx, cy, half, r, a) {
  const x0 = Math.max(0, Math.floor(cx - r)), x1 = Math.min(w - 1, Math.ceil(cx + r));
  const y0 = Math.max(0, Math.floor(cy - half - r)), y1 = Math.min(h - 1, Math.ceil(cy + half + r));
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    const dy = Math.max(0, Math.abs(y - cy) - half), d = Math.hypot(x - cx, dy) / r; if (d < 1) F[y * w + x] += a * prof(d);
  }
}

// ---------- el tejido: cordones de axón, dendritas, cuerpos y nudos en las conexiones fuertes
const T = { pLow: 0.6, synQ: 0.99, axA0: 0.06, axA1: 0.2, axW0: 0.08, axW1: 0.12, denA: 0.2, denW: 0.15, blur: 0.25, somR0: 0.5, somR1: 0.9, somA: 0.65, knR0: 0.35, knR1: 0.8, knA: 0.8 };
const linesCv = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(FW, FH) : null;
const fpx = (y) => (y - PYA) * pxmm, fpy = (x) => (x - PXA) * pxmm;
function cellStrengths() {
  const N = cul.N, st = new Float32Array(N), cnt = new Float32Array(N);
  const S = cul.syn.pre.length, W = cul.W || cul.syn.w;
  for (let s = 0; s < S; s++) { const i = cul.syn.pre[s]; if (cul.inh[i]) continue; st[i] += W[s] / P.wMax; cnt[i]++; }
  for (let i = 0; i < N; i++) st[i] = cnt[i] ? st[i] / cnt[i] : 0;
  const sorted = Array.from(st).filter((v, i) => !cul.inh[i]).sort((a, b) => a - b);
  const lo = sorted[Math.floor(sorted.length * T.pLow)], hi = sorted[Math.floor(sorted.length * 0.98)];
  for (let i = 0; i < N; i++) st[i] = cul.inh[i] ? 0 : Math.max(0, Math.min(1, (st[i] - lo) / (hi - lo || 1)));
  const ws = Array.from(W).sort((a, b) => a - b);
  return { st, wq: ws[Math.floor(ws.length * T.synQ)], wmx: ws[ws.length - 1] };
}
function paintTissue(step) {
  const { st, wq, wmx } = cellStrengths(), W = cul.W || cul.syn.w;
  const F = new Float32Array(FW * FH);
  if (linesCv) {
    const L = linesCv.getContext('2d'); L.clearRect(0, 0, FW, FH); L.lineCap = 'round'; L.strokeStyle = '#fff';
    const sg = cul.seg, ns = sg.x0.length, LV = 6;
    for (let lv = 0; lv < LV; lv++) {
      L.beginPath(); let any = false;
      for (let k = 0; k < ns; k++) {
        if (sg.born[k] > step) break;
        if (Math.min(LV - 1, Math.floor(st[sg.cell[k]] * LV)) !== lv) continue;
        L.moveTo(fpx(sg.y0[k]), fpy(sg.x0[k])); L.lineTo(fpx(sg.y1[k]), fpy(sg.x1[k])); any = true;
      }
      const f = lv / (LV - 1);
      if (any) { L.globalAlpha = T.axA0 + T.axA1 * f; L.lineWidth = (T.axW0 + T.axW1 * f) * pxmm; L.stroke(); }
    }
    const dd = cul.den; L.globalAlpha = T.denA; L.lineWidth = T.denW * pxmm; L.beginPath();
    for (let k = 0; k < dd.x0.length; k++) { if (dd.born[k] > step) break; L.moveTo(fpx(dd.y0[k]), fpy(dd.x0[k])); L.lineTo(fpx(dd.y1[k]), fpy(dd.x1[k])); }
    L.stroke(); L.globalAlpha = 1;
    const px = L.getImageData(0, 0, FW, FH).data;
    for (let i = 0; i < F.length; i++) F[i] = px[4 * i + 3] / 255;
    boxBlur(F, FW, FH, Math.max(1, Math.round(Math.sqrt(4 * Math.pow(T.blur * pxmm, 2) + 1) / 2)), 3);
  }
  for (let i = 0; i < cul.N; i++) {
    const r = (T.somR0 + T.somR1 * (cul.inh[i] ? 0.2 : st[i])) * pxmm;
    splat(F, FW, FH, fpx(cul.cy[i]), fpy(cul.cx[i]), r, T.somA);
  }
  const sy = cul.syn, S = sy.pre.length;
  for (let s = 0; s < S; s++) {
    if (sy.born[s] > step || cul.inh[sy.pre[s]] || W[s] < wq) continue;
    const v = (W[s] - wq) / (wmx - wq || 1), r = (T.knR0 + T.knR1 * v) * pxmm;
    splat(F, FW, FH, fpx(sy.y[s]), fpy(sy.x[s]), r, Math.min(1, T.knA * (0.3 + v)));
  }
  const field = new Uint8Array(FW * FH), Hh = new Float32Array(FW * FH);
  for (let i = 0; i < F.length; i++) { const v = Math.min(1, F[i]); field[i] = v * 255; Hh[i] = v; }
  boxBlur(Hh, FW, FH, Math.round(Math.sqrt(4 * Math.pow(0.55 * pxmm, 2) + 1) / 2), 3);
  const height = new Uint8Array(FW * FH);
  for (let i = 0; i < Hh.length; i++) height[i] = Hh[i] * 255;
  postMessage({ type: 'tissue', w: FW, h: FH, field, height }, [field.buffer, height.buffer]);
}

// ---------- actividad: quién dispara (rojo), quién siente (verde), dónde estimula el electrodo (azul)
const apx = (y) => (y - PYA) * amm, apy = (x) => (x - PXA) * amm;
function paintActivity() {
  const t = cul.t, n = AW * AH, R = new Float32Array(n), G = new Float32Array(n), B = new Float32Array(n);
  for (let i = 0; i < cul.N; i++) {
    const x = apx(cul.cy[i]), y = apy(cul.cx[i]), since = t - cul.lastSpike[i];
    if (since <= 90) { const f = 1 - since / 90; splat(R, AW, AH, x, y, (1.4 + 1.2 * f) * amm, f); }
    else { const dep = Math.max(0, Math.min(1, (cul.v[i] + 64) / 14)); if (dep > 0.05) splat(G, AW, AH, x, y, 1.6 * amm, dep); }
  }
  // el electrodo que tiene asignada la pelota y las paletas (sigue a la pelota todo el tiempo)
  const C = cul.phase === 'juego' && cond !== 'reposo';
  if (C) {
    for (const g of cul.targets()) {
      if (g.half != null) splatStrip(B, AW, AH, apx(g.y), apy(g.x), g.half * amm, P.padR * amm, 0.22);
      else splat(B, AW, AH, apx(g.y), apy(g.x), g.r * 1.2 * amm, 0.3);
    }
  }
  // los pulsos que de verdad salieron en los últimos 80 ms
  const Lg = cul.stimLog;
  for (let q = Math.max(0, Lg.length - 160); q < Lg.length; q += 4) {
    const age = t - Lg[q]; if (age > 80 || age < 0) continue;
    const f = 1 - age / 80, rad = Lg[q + 3];
    if (rad >= 0) splat(B, AW, AH, apx(Lg[q + 2]), apy(Lg[q + 1]), rad * 1.2 * amm, f);
    else splatStrip(B, AW, AH, apx(Lg[q + 2]), apy(Lg[q + 1]), -rad * amm, P.padR * amm, f);
  }
  if (Lg.length > 2000) cul.stimLog = Lg.slice(Lg.length - 400);
  const out = new Uint8Array(n * 4);
  for (let i = 0; i < n; i++) { out[4 * i] = Math.min(1, R[i]) * 255; out[4 * i + 1] = Math.min(1, G[i]) * 255; out[4 * i + 2] = Math.min(1, B[i]) * 255; out[4 * i + 3] = 255; }
  return out;
}

// ---------- ciclo
function sendFrame(now) {
  const act = paintActivity();
  postMessage({
    type: 'frame', t: cul.t, phase: cul.phase, ball: { x: cul.ball.x, y: cul.ball.y }, paddle: cul.paddle, adv: cul.adv,
    rateUp: cul.rateUp, rateDown: cul.rateDown, goals: cul.goals, misses: cul.totalMisses, hits: cul.totalHits,
    aw: AW, ah: AH, act,
  }, [act.buffer]);
  const m = Math.floor(cul.t / 60000);
  if (m !== lastMin) {
    lastMin = m; const series = [];
    for (let k = 0; k < m; k++) { const s = cul.summary(k * 60000, (k + 1) * 60000); series.push(s.n ? s.hitsPerRally : 0); }
    postMessage({ type: 'lcd', series });
  }
}
function loop() {
  const now = performance.now();
  if (state === 'replay') {
    const k = Math.min(1, (now - replayStart) / GROW_REPLAY_MS);
    if (now - lastReplayPaint > 400 || k >= 1) {
      lastReplayPaint = now; paintTissue(Math.floor(cul.growth.total * k));
      postMessage({ type: 'grow', day: Math.max(1, Math.ceil(cul.growth.total * k / P.stepsPerDay)), done: k >= 1 });
    }
    if (k >= 1) { state = 'play'; cul.setCondition(cond); wallBase = performance.now(); simBase = cul.t; lastTissue = wallBase; }
  } else if (state === 'play') {
    const target = simBase + (now - wallBase);          // 1 ms del cultivo = 1 ms real
    while (cul.t < target && performance.now() - now < 10) { cul.step(); cul.spikeLog.length = 0; }
    if (target - cul.t > 200) { simBase = cul.t; wallBase = performance.now(); }   // si la máquina no da, se va más lento pero parejo
    if (now - lastPost >= 16) { lastPost = now; sendFrame(now); }
    if (now - lastTissue > 3000) { lastTissue = now; paintTissue(1e9); }        // el tejido sigue a las conexiones que cambian
  }
  setTimeout(loop, 4);
}
function sembrar(seed, trained) {
  state = 'growing'; seedNo = seed; lastMin = -1;
  if (trained && trained.params) for (const k of ['lr', 'tauElig', 'ballR', 'stimMode', 'paddleGain', 'plasticMotor']) if (trained.params[k] != null) P[k] = trained.params[k];
  cul = new CU({ seed, condition: 'estimulo' });
  let lastDay = 0;
  while (!cul.growth.done) {
    cul.growStep();
    const day = Math.ceil(cul.growth.step / P.stepsPerDay);
    if (day !== lastDay) { lastDay = day; postMessage({ type: 'computing', day }); }
  }
  // lo que aprendió entrenando en Kaggle: las mismas células, con las conexiones como quedaron
  if (trained && trained.W) {
    const bin = atob(trained.W), u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const W = new Float32Array(u8.buffer);
    if (W.length === cul.W.length) cul.W.set(W); else postMessage({ type: 'aviso', msg: 'los pesos entrenados no corresponden a este cultivo' });
  }
  state = 'replay'; replayStart = performance.now(); lastReplayPaint = -1e9;
}
self.onmessage = (e) => {
  const m = e.data;
  if (m.type === 'seed') sembrar(m.seed, m.trained);
  if (m.type === 'cond') { cond = m.cond; if (cul && state === 'play') cul.setCondition(cond); }
};
loop();
