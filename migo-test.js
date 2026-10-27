/* Migo – test de nivel ADAPTATIVO (12 preguntas, escalera A2 → sube/baja).
   Se carga DESPUÉS del script principal de index.html:  <script src="migo-test.js"></script>
   Reutiliza tu banco QB, tu diseño y tus animaciones; solo reemplaza la lógica del test. */
const N_Q = 12;                       // preguntas del test
const NO_SE = 4;                      // índice de la opción "No sé" (se guarda como 5.ª opción de cada pregunta)
let AT = { seen: new Set(), path: [] };
function resetAT() { AT = { seen: new Set(), path: [] }; }

/* Elige una pregunta no repetida del nivel lv (0=A1 … 4=C1); si se agotó, usa el nivel vecino más cercano. */
function pickQ(lv) {
  lv = Math.max(0, Math.min(4, lv));
  let pool = QB[lv].filter(q => !AT.seen.has(q.q));
  if (!pool.length) for (const d of [1, -1, 2, -2]) {
    const l = lv + d;
    if (l >= 0 && l <= 4) { pool = QB[l].filter(q => !AT.seen.has(q.q)); if (pool.length) { lv = l; break; } }
  }
  const q = pool[Math.random() * pool.length | 0]; AT.seen.add(q.q);
  const o = shuf(q.o.map((t, k) => ({ t: t, ok: k === q.a })));
  return { lv: lv, q: q.q, o: o.map(x => x.t).concat('No sé'), a: o.findIndex(x => x.ok) };
}
/* Registra la respuesta y devuelve el nivel de la siguiente pregunta: acierto = sube, fallo o "No sé" = baja. */
function adaptStep(d, ok, skip) { AT.path.push({ lv: d.lv, ok: ok, skip: !!skip }); return d.lv + (ok ? 1 : -1); }

/* Nivel = habilidad θ (0=A1 … 4=C1) más probable dada TODA la secuencia de respuestas (modelo logístico con 25% de acierto por azar
   y un nivel "dominado" ≈ 80% de aciertos). "No sé" cuenta como fallo sin azar. La confianza sale de la incertidumbre (sd) de θ. */
function level() {
  const p = AT.path, raw = [0, 0, 0, 0, 0], tot = [0, 0, 0, 0, 0];
  p.forEach(x => { tot[x.lv]++; if (x.ok) raw[x.lv]++; });
  const cnt = raw.map((c, j) => tot[j] ? Math.round(2 * c / tot[j]) : 0);
  if (!p.length) return { k: 0, cnt: cnt, raw: raw, tot: tot, lo: 0, hi: 0, conf: 'baja', mean: 0, sd: 9 };
  const sg = x => 1 / (1 + Math.exp(-x)), G = [], W = [];
  for (let th = 0; th <= 4.0001; th += .05) {
    let ll = -0.5 * Math.pow((th - 1.8) / 1.5, 2);                 // prior suave centrado en A2
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

/* ---------- Pantalla del test ---------- */
function start() {
  Q = []; i = 0; done = []; tpicks = []; resetAT(); Q.push(pickQ(1));
  view('test'); const q = $('quiz'); q.className = 'qcard';
  q.innerHTML = shellHTML('nx', 'nbtn()', 'I’m Migo. Test time!', 'No help this time 💪'); render(true);
}
function render(first) {
  const d = Q[i]; locked = false; tsel = null;
  updBar($('quiz'), N_Q, i, done);
  $('quiz').querySelector('.cnt').textContent = 'Pregunta ' + (i + 1) + ' de ' + N_Q;
  slide($('quiz'), '<div class="q">' + (i + 1) + '. ' + d.q + ' <button class="spk" data-t="' + d.q.replace('___', 'blank') + '" onclick="speak(this.dataset.t)" aria-label="Escuchar la frase">🔊</button></div>' +
    '<div class="opts">' + d.o.slice(0, 4).map((t, k) => '<button class="opt" onclick="pick(' + k + ',this)">' + t + '</button>').join('') + '</div>' +
    '<p style="margin:2px 0 0;text-align:center"><button class="hint" onclick="idk()">No sé 🤷</button></p>');
  setBtn('nx', 'Verificar', false);
  if (!first) mood('idle', pickR(NEXTQ), 'No help this time 💪');
}
function idk() { if (locked) return; tsel = NO_SE; nbtn(); }
function nbtn() {
  if (locked) { next(); return; }
  if (tsel === null) return;
  locked = true;
  const d = Q[i], skip = tsel == NO_SE, ok = tsel === d.a;
  done[i] = ok; tpicks[i] = tsel;
  const nl = adaptStep(d, ok, skip);
  const bs = topts(); bs.forEach(o => { o.disabled = true; o.classList.remove('sel'); });
  if (bs[tsel]) bs[tsel].classList.add(ok ? 'good' : 'bad');
  bs[d.a].classList.add('good');
  if (ok) { mood('happy', pickR(GOOD)); burst(); } else mood('sad', skip ? 'No problem!' : pickR(BAD), 'The answer: ' + d.o[d.a]);
  speak(d.q.replace('___', d.o[d.a]), true);
  if (i < N_Q - 1) Q.push(pickQ(nl));
  setBtn('nx', i == N_Q - 1 ? 'Ver mi nivel' : 'Siguiente', true);
}
function next() { i++; i < N_Q ? render() : result(); }

/* ---------- Resultado: nivel + rango + confianza + botón a la app ---------- */
function goApp() {
  const lv = level(), s = done.filter(Boolean).length;
  location.href = 'app.html?lvl=' + LV[lv.k] + '&s=' + s + '&n=' + Q.length + '&conf=' + lv.conf + '&lo=' + LV[lv.lo] + '&hi=' + LV[lv.hi] + '&c=' + lv.raw.join(',') + '#registro';
}
function result() {
  const lv = level(), k = lv.k, l = L[k], s = done.filter(Boolean).length;
  view('result');
  const rg = lv.hi > lv.lo ? 'Probablemente entre <b>' + LV[lv.lo] + '</b> y <b>' + LV[lv.hi] + '</b>. ' : '';
  const ct = { alta: '🟢 <b>Confianza alta:</b> tus respuestas se estabilizaron en este nivel.',
    media: '🟡 <b>Confianza media:</b> oscilaste entre niveles cercanos; lo confirmamos con tu práctica.',
    baja: '🔴 <b>Confianza baja:</b> tus respuestas variaron mucho; lo confirmamos con una prueba práctica.' }[lv.conf];
  $('res').innerHTML = '<div class="card"><div class="coach" style="justify-content:center;min-height:0"><div class="figwrap">' + fig('happy') + '</div></div>' +
    '<h2 style="font-size:30px;margin-bottom:4px">¡Terminaste! ' + s + ' de ' + Q.length + ' 🎉</h2>' +
    '<div class="lvrow2"><div class="lvl sm" style="background:' + l.c + '">' + l.n + '<small>' + l.name + '</small></div>' +
    '<div class="lvinfo"><p class="k">Tu nivel estimado</p><p class="nm2">' + l.name + '</p><div class="chips">' +
    lv.raw.map((c, j) => lv.tot[j] ? '<span class="' + (c == lv.tot[j] ? 'f' : '') + '">' + LV[j] + ': ' + c + '/' + lv.tot[j] + '</span>' : '').join('') + '</div></div></div>' +
    '<div class="tip" style="margin:0 0 12px;font-size:17px">' + rg + ct + '</div>' +
    '<p style="margin:0 0 10px"><button class="btn pink" onclick="goApp()">🚀 Crear mi cuenta y empezar mi plan</button></p>' +
    '<p style="margin:0 0 4px"><button class="btn" id="pdfb" onclick="pdfGate(this)">📄 Descargar mi plan en PDF</button></p>' + offerCard() +
    '<h2 class="sec">Tu plan de estudio · ' + l.n + '</h2>' +
    '<div class="plan" style="margin-top:8px"><div style="--c:var(--pink)"><h3>Tu método de estudio</h3><ol>' + l.m.map(x => '<li>' + x + '</li>').join('') + '</ol></div>' +
    '<div style="--c:var(--sky)"><h3>Cada día</h3><ul><li>10 min: palabras con imagen</li><li>10 min: escuchar</li><li>10 min: hablar o escribir</li></ul></div></div>' +
    timeBox(k) +
    '<h2 class="sec">' + vocTitle(k) + '</h2><p class="note2">Toca cada palabra para ver su imagen y escuchar la frase. ' + vocNote + '</p>' + vocScreen(k) +
    '<div class="tip"><b>🖼️ Truco palabra-imagen:</b> ' + l.t + '</div>' +
    '<p style="margin-top:18px"><button class="btn pink" onclick="startMethod()">Practicar palabras</button> <button class="hint" onclick="start()">Repetir el test</button> <button class="hint" onclick="view(\'home\')">Inicio</button></p></div>';
  setTimeout(burst, 300);
}

/* ---------- Ajustes a piezas existentes (PDF y correo) ---------- */
const _rh = reportHTML;
reportHTML = function () {
  const lv = level();
  return _rh()
    .replace(/<span class="(f?)">(A1|A2|B1|B2|C1): \d\/2<\/span>/g, (m, f, n) => { const j = LV.indexOf(n); return lv.tot[j] ? '<span class="' + f + '">' + n + ': ' + lv.raw[j] + '/' + lv.tot[j] + '</span>' : ''; })
    .replace(/ de 10 respuestas/, ' de ' + Q.length + ' respuestas')
    .replace('Tu nivel es el más alto en el que acertaste las 2 preguntas y casi todas las anteriores.',
      'Test adaptativo de ' + Q.length + ' preguntas. Confianza ' + lv.conf + (lv.hi > lv.lo ? ' · probablemente entre ' + LV[lv.lo] + ' y ' + LV[lv.hi] : '') + '.');
};
function submitLead(ev) {
  ev.preventDefault();
  const email = $('leadE').value.trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) { leadErr('Escribe un correo válido, por ejemplo tu@correo.com'); $('leadE').focus(); return false; }
  if (!$('leadC').checked) { leadErr('Marca la casilla para continuar.'); return false; }
  const fin = done.length == N_Q, lv = fin ? level() : null;
  const rec = { email: email, consent: true, marketing: $('leadM').checked, source: leadMode, level: fin ? L[lv.k].n : '', score: fin ? done.filter(Boolean).length : null, confidence: fin ? lv.conf : '', ts: new Date().toISOString() };
  try { localStorage.setItem('mg-lead', email); } catch (e) {}
  queueLead(rec); flushLeads();
  if (leadMode == 'pdf') { const b = leadBtn || $('pdfb'); closeLead(); makePDF(b); }
  else $('leadBody').innerHTML = thanksHTML(email);
  return false;
}