/* Motor adaptativo compartido (landing y app). Requiere QBANK (qbank.js) cargado antes.
   Escalera: acierto = sube un nivel, fallo o «No sé» = baja. Nivel = habilidad más probable con TODAS las respuestas (modelo logístico). */
const N_Q = 12, NO_SE = 4;                 // preguntas del test · índice de «No sé» (5.ª opción)
let AT = { seen: new Set(), path: [] };
function resetAT() { AT = { seen: new Set(), path: [] }; }
function _sh(a) { a = a.slice(); for (let k = a.length; k > 1; k--) { const j = Math.random() * k | 0; [a[k - 1], a[j]] = [a[j], a[k - 1]]; } return a; }

/* Pregunta no repetida del nivel lv (0=A1 … 4=C1); si se agotó, usa el nivel vecino más cercano. */
function pickQ(lv) {
  lv = Math.max(0, Math.min(4, lv));
  let pool = QBANK[lv].filter(q => !AT.seen.has(q.q));
  if (!pool.length) for (const d of [1, -1, 2, -2]) {
    const l = lv + d;
    if (l >= 0 && l <= 4) { pool = QBANK[l].filter(q => !AT.seen.has(q.q)); if (pool.length) { lv = l; break; } }
  }
  const q = pool[Math.random() * pool.length | 0]; AT.seen.add(q.q);
  const o = _sh(q.o.map((t, k) => ({ t: t, ok: k === q.a })));
  return { lv: lv, q: q.q, o: o.map(x => x.t).concat('No sé'), a: o.findIndex(x => x.ok) };
}
function adaptStep(d, ok, skip) { AT.path.push({ lv: d.lv, ok: ok, skip: !!skip }); return d.lv + (ok ? 1 : -1); }

/* θ (0=A1 … 4=C1) más probable: 25% de acierto por azar, nivel «dominado» ≈ 80% de aciertos; «No sé» = fallo sin azar.
   Confianza según la incertidumbre (sd) de θ: cortes calibrados en simulación. */
function adaptLevel() {
  const p = AT.path, raw = [0, 0, 0, 0, 0], tot = [0, 0, 0, 0, 0];
  p.forEach(x => { tot[x.lv]++; if (x.ok) raw[x.lv]++; });
  const cnt = raw.map((c, j) => tot[j] ? Math.round(2 * c / tot[j]) : 0);
  if (!p.length) return { k: 0, cnt: cnt, raw: raw, tot: tot, lo: 0, hi: 0, conf: 'baja', mean: 0, sd: 9 };
  const sg = x => 1 / (1 + Math.exp(-x)), G = [], W = [];
  for (let th = 0; th <= 4.0001; th += .05) {
    let ll = -0.5 * Math.pow((th - 1.8) / 1.5, 2);
    for (const x of p) {
      const s = sg(2.2 * (th - x.lv + .5)), pc = .25 + .75 * s;
      ll += Math.log(x.skip ? Math.max(1 - s, 1e-6) : x.ok ? pc : Math.max(1 - pc, 1e-6));
    }
    G.push(th); W.push(ll);
  }
  const mx = Math.max(...W), w = W.map(l => Math.exp(l - mx)), sw = w.reduce((a, b) => a + b, 0);
  const mean = G.reduce((a, t, j) => a + t * w[j], 0) / sw;
  const sd = Math.sqrt(G.reduce((a, t, j) => a + w[j] * (t - mean) * (t - mean), 0) / sw);
  const c = v => Math.max(0, Math.min(4, Math.round(v))), k = c(mean);
  const conf = sd < .40 ? 'alta' : sd < .49 ? 'media' : 'baja';
  return { k: k, cnt: cnt, raw: raw, tot: tot, lo: Math.min(k, c(mean - sd)), hi: Math.max(k, c(mean + sd)), conf: conf, mean: mean, sd: sd };
}