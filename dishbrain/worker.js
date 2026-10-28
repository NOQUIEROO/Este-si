/* Corre el experimento completo (varias condiciones y cultivos) fuera del hilo de la página. */
importScripts('engine.js');

function runCulture(cond, seed, mins, onMinute) {
  const d = new DishBrain({ seed: seed, condition: cond });
  const perMin = [];
  for (let m = 0; m < mins; m++) {
    d.run(60000);
    let n = 0, hits = 0, aces = 0, long = 0;
    for (const r of d.rallies) {
      if (r.t < m * 60000 || r.t >= (m + 1) * 60000) continue;
      n++; hits += r.hits; if (r.hits === 0) aces++; if (r.hits >= 3) long++;
    }
    perMin.push({ n: n, hits: hits, aces: aces, long: long });
    onMinute();
  }
  return perMin;
}

onmessage = function (ev) {
  const job = ev.data;
  const cultures = [];
  for (const seed of job.seeds) {
    cultures.push(runCulture(job.cond, seed, job.mins, function () {
      postMessage({ type: 'progress', cond: job.cond });
    }));
  }
  postMessage({ type: 'done', cond: job.cond, cultures: cultures });
};
