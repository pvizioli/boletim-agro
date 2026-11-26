//VERSION=3
// Fenologia da soja por pixel, Sentinel-2 L2A, uma temporada (1/ago a 30/abr).
// Saidas: "soja" (1 = curva com forma e duracao de soja) e "fen" (so pixels de soja):
//   [0] sos  dia (desde 1/ago) do inicio de crescimento (15% da amplitude)
//   [1] pico NDVI maximo (mediana movel de 3)
//   [2] eos  dia da queda de 75% apos o pico (colheita), -1 se nao ocorreu
//   [3] integ area de NDVI acima da base entre sos e eos (ou pico+60)
//   [4] tpico dia do pico
//   [5] ndvi15jan NDVI interpolado em 15/jan (dia 167)
//   [6] integJan area acima da base de sos ate 15/jan
// Sem template literals (regra do projeto).
var DIA_INI = 0; // 1/ago
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: [
      { id: "soja", bands: 1, sampleType: "FLOAT32" },
      { id: "fen", bands: ["sos", "pico", "eos", "integ", "tpico", "ndvi15jan", "integJan"], sampleType: "FLOAT32" },
      { id: "dataMask", bands: ["soja", "fen"] }
    ],
    mosaicking: "ORBIT"
  };
}
var T0 = null;
function preProcessScenes(collections) {
  return collections;
}
function diaDe(s) {
  var d = new Date(s);
  return (d.getTime() - T0) / 86400000.0;
}
function fenologia(obs) {
  // obs: [[t, ndvi], ...] ordenado por t
  var r = { soja: 0, sos: -1, pico: -1, eos: -1, integ: -1, tpico: -1, n15: -1, ij: -1 };
  if (obs.length < 8) return r;
  // remove quedas isoladas (nuvem/sombra residual)
  var lim = [];
  for (var i = 0; i < obs.length; i++) {
    var a = i > 0 ? obs[i - 1][1] : obs[i + 1][1];
    var b = i < obs.length - 1 ? obs[i + 1][1] : obs[i - 1][1];
    if (Math.min(a, b) - obs[i][1] > 0.15) continue;
    lim.push(obs[i]);
  }
  obs = lim;
  if (obs.length < 8) return r;
  // mediana movel de 3
  var sm = [];
  for (i = 0; i < obs.length; i++) {
    var w = [obs[Math.max(0, i - 1)][1], obs[i][1], obs[Math.min(obs.length - 1, i + 1)][1]].sort(function (x, y) { return x - y; });
    sm.push([obs[i][0], w[1]]);
  }
  var ip = -1, pico = -1;
  for (i = 0; i < sm.length; i++) {
    if (sm[i][0] >= 106 && sm[i][0] <= 221 && sm[i][1] > pico) { pico = sm[i][1]; ip = i; }
  }
  if (ip < 0) return r;
  var tp = sm[ip][0];
  var esq = [], dir = [];
  for (i = 0; i < sm.length; i++) {
    if (sm[i][0] >= tp - 140 && sm[i][0] <= tp - 25) esq.push(sm[i][1]);
    if (sm[i][0] >= tp + 20 && sm[i][0] <= tp + 130) dir.push(sm[i][1]);
  }
  if (esq.length < 2) return r;
  esq.sort(function (x, y) { return x - y; });
  var base = esq[Math.floor(0.2 * (esq.length - 1))];
  var amp = pico - base;
  if (pico < 0.72 || base > 0.45 || amp < 0.30) return r;
  var lsos = base + 0.15 * amp, sos = -1;
  for (i = ip - 1; i >= 0; i--) {
    if (sm[i][1] < lsos) {
      var t1 = sm[i][0], v1 = sm[i][1], t2 = sm[i + 1][0], v2 = sm[i + 1][1];
      sos = t1 + (lsos - v1) * (t2 - t1) / Math.max(v2 - v1, 1e-6);
      break;
    }
  }
  if (sos < 0) return r;
  var eos = -1;
  if (dir.length >= 1) {
    var bdir = Math.min.apply(null, dir);
    var leos = pico - 0.75 * (pico - bdir);
    for (i = ip + 1; i < sm.length; i++) {
      if (sm[i][1] < leos) {
        var u1 = sm[i - 1][0], w1 = sm[i - 1][1], u2 = sm[i][0], w2 = sm[i][1];
        eos = u1 + (w1 - leos) * (u2 - u1) / Math.max(w1 - w2, 1e-6);
        break;
      }
    }
  }
  var subida = tp - sos;
  if (sos < 15 || sos > 170 || subida < 25 || subida > 100) return r;
  if (eos > 0 && (eos - sos < 70 || eos - sos > 160)) return r;
  // integrais (trapezio sobre a serie suavizada)
  function integral(t0, t1) {
    var s = 0;
    for (var k = 1; k < sm.length; k++) {
      var a0 = Math.max(sm[k - 1][0], t0), a1 = Math.min(sm[k][0], t1);
      if (a1 <= a0) continue;
      var f = function (t) { return sm[k - 1][1] + (sm[k][1] - sm[k - 1][1]) * (t - sm[k - 1][0]) / (sm[k][0] - sm[k - 1][0]); };
      s += ((f(a0) - base) + (f(a1) - base)) / 2 * (a1 - a0);
    }
    return Math.max(s, 0);
  }
  var n15 = -1;
  for (i = 1; i < sm.length; i++) {
    if (sm[i - 1][0] <= 167 && sm[i][0] >= 167) {
      n15 = sm[i - 1][1] + (sm[i][1] - sm[i - 1][1]) * (167 - sm[i - 1][0]) / Math.max(sm[i][0] - sm[i - 1][0], 1e-6);
      break;
    }
  }
  r.soja = 1; r.sos = sos; r.pico = pico; r.eos = eos; r.tpico = tp; r.n15 = n15;
  r.integ = integral(sos, eos > 0 ? eos : tp + 60);
  r.ij = integral(sos, 167);
  return r;
}
function evaluatePixel(samples, scenes) {
  if (T0 === null) {
    var tmin = Infinity;
    for (var q = 0; q < scenes.length; q++) tmin = Math.min(tmin, new Date(scenes[q].date).getTime());
    var d0 = new Date(tmin);
    var ano = d0.getUTCMonth() >= 7 ? d0.getUTCFullYear() : d0.getUTCFullYear() - 1;
    T0 = Date.UTC(ano, 7, 1);
  }
  var obs = [], algum = 0;
  for (var i = 0; i < samples.length; i++) {
    var s = samples[i];
    if (s.dataMask !== 1) continue;
    algum = 1;
    if (s.SCL !== 4 && s.SCL !== 5) continue;
    var den = s.B08 + s.B04;
    if (den <= 0) continue;
    obs.push([diaDe(scenes[i].date), (s.B08 - s.B04) / den]);
  }
  obs.sort(function (a, b) { return a[0] - b[0]; });
  var r = fenologia(obs);
  return {
    soja: [r.soja],
    fen: [r.sos, r.pico, r.eos, r.integ, r.tpico, r.n15, r.ij],
    dataMask: [algum, r.soja]
  };
}
