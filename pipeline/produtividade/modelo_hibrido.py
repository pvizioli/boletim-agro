# -*- coding: utf-8 -*-
"""Modelo hibrido: Jensen (agua por fase) + calendario/vigor por satelite
+ efeito do municipio + tendencia tecnologica.

log(Y) = a_mun + b*(ano-2018) + sum_i lambda_i*log(ETR/ETm)_i
         + sum_k beta_k * x_k  (indices de satelite padronizados)

- (ETR/ETm)_i vem do balanco hidrico rodado para COORTES de semeadura
  (p25/p50/p75 do satelite ou do Deral) com o ciclo das cultivares ou o
  ciclo observado pelo satelite, ponderadas.
- lambda >= 0; beta livre; a_mun absorve solo/manejo/potencial local.
- Municipio sem historico: a_mun = media dos demais (previsao fria).
"""

import numpy as np
from scipy.optimize import lsq_linear

from . import balanco_hidrico, config


def razoes_coortes(serie, coortes, cad_mm):
    """coortes: [(data_semeadura, ciclo_dias, peso)]. Retorna razoes
    ETR/ETm por fase (media ponderada) e dias faltantes maximos."""
    R, W, falt = [], [], 0
    for d, c, w in coortes:
        sim = balanco_hidrico.simular(serie, d, cad_mm=cad_mm, ciclo=int(round(c)))
        falt = max(falt, sim["dias_faltantes"])
        r = balanco_hidrico.razoes(sim)
        if any(x is None for x in r):
            continue
        R.append(r)
        W.append(w)
    if not R:
        return None, falt
    R, W = np.array(R, float), np.array(W, float)
    return list(np.sum(R * W[:, None], axis=0) / W.sum()), falt


class Hibrido(object):
    def __init__(self, usar_agua=True, extras=(), ano_ref=2018):
        self.usar_agua = usar_agua
        self.extras = tuple(extras)
        self.ano_ref = ano_ref

    def _X(self, obs):
        A = np.zeros((len(obs), len(self.muns)))
        for k, o in enumerate(obs):
            if o["mun"] in self.idx:
                A[k, self.idx[o["mun"]]] = 1.0
        cols = [A, np.array([[o["ano"] - self.ano_ref] for o in obs], float)]
        if self.usar_agua:
            cols.append(np.log(np.clip(np.array([o["razoes"] for o in obs], float),
                                       config.RAZAO_MIN, 1.0)))
        if self.extras:
            E = np.array([[o[k] for k in self.extras] for o in obs], float)
            cols.append((E - self.mu) / self.sd)
        return np.hstack(cols)

    def ajustar(self, obs):
        self.muns = sorted(set(o["mun"] for o in obs))
        self.idx = {m: i for i, m in enumerate(self.muns)}
        if self.extras:
            E = np.array([[o[k] for k in self.extras] for o in obs], float)
            self.mu, self.sd = E.mean(0), E.std(0)
            self.sd[self.sd == 0] = 1.0
        X = self._X(obs)
        y = np.log([o["y"] for o in obs])
        lb = np.full(X.shape[1], -np.inf)
        if self.usar_agua:
            i0 = len(self.muns) + 1
            lb[i0:i0 + 4] = 0.0
        self.b = lsq_linear(X, y, bounds=(lb, np.full(X.shape[1], np.inf))).x
        self.resid_sd = float(np.std(y - X @ self.b))
        return self

    def prever(self, obs):
        X = self._X(obs)
        a_med = float(self.b[:len(self.muns)].mean())
        out = []
        for k, o in enumerate(obs):
            v = X[k] @ self.b + (0.0 if o["mun"] in self.idx else a_med)
            out.append(float(np.exp(v)))
        return out

    def coeficientes(self):
        n = len(self.muns)
        d = {"tendencia_pct_ano": round(float(np.expm1(self.b[n]) * 100), 2)}
        j = n + 1
        if self.usar_agua:
            d["lambdas"] = [round(float(x), 3) for x in self.b[j:j + 4]]
            j += 4
        for k, nome in enumerate(self.extras):
            d["beta_" + nome] = round(float(self.b[j + k]), 4)
        return d


def cv(obs, fabrica, protocolo="loyo"):
    chave = "ano" if protocolo == "loyo" else "mun"
    out = []
    for c in sorted(set(o[chave] for o in obs)):
        tr = [o for o in obs if o[chave] != c]
        te = [o for o in obs if o[chave] == c]
        p = fabrica().ajustar(tr).prever(te)
        out += [dict(o, prev=v) for o, v in zip(te, p)]
    return out
