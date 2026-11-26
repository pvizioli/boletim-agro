# -*- coding: utf-8 -*-
"""Modelo de Jensen (1968) e Jensen modificado com indicadores de grupo.

Jensen:       Y/Ym = prod_i (ETR_i/ETm_i)^lambda_i
Modificado:   Y/Ym = prod_i (ETR_i/ETm_i)^lambda_i * prod_i exp(gamma_i[g_i])
Em log:       log(Y/Ym) = b0 + sum_i lambda_i * log(r_i) + sum_i gamma_i[g_i]
onde g_i e o grupo (k-medias) do municipio na fase i (grupo 0 = referencia).

Melhorias de estabilidade em relacao a tese (que reportou parametros
singulares): ridge nos gammas e lambda >= 0 opcional (lambda negativo nao
tem sentido fisiologico; a tese estimou lambda_2 < 0 em 2007).
"""

import numpy as np
from scipy.optimize import lsq_linear

from . import config


def _log_razoes(razoes):
    r = np.asarray(razoes, dtype=float)
    return np.log(np.clip(r, config.RAZAO_MIN, 1.0))


class Jensen(object):
    """usar_grupos=False => Jensen classico (4 lambdas + intercepto)."""

    def __init__(self, usar_grupos=False, ridge=1.0, lambda_nao_negativo=True):
        self.usar_grupos = usar_grupos
        self.ridge = ridge
        self.lambda_nn = lambda_nao_negativo
        self.b0 = 0.0
        self.lambdas = np.full(4, config.KY_PRIOR)
        self.gammas = [dict() for _ in range(4)]   # fase -> {grupo: gamma}
        self.grupos_por_fase = [[0] for _ in range(4)]
        self.calibrado = False
        self.n_obs = 0

    # -- desenho -----------------------------------------------------------
    def _montar(self, razoes, grupos):
        L = _log_razoes(razoes)
        cols = [L]
        self._colmap = []
        if self.usar_grupos and grupos is not None:
            G = np.asarray(grupos, dtype=int)
            for i in range(4):
                for g in sorted(set(G[:, i].tolist())):
                    if g == 0:
                        continue
                    cols.append((G[:, i] == g).astype(float)[:, None])
                    self._colmap.append((i, g))
        return np.hstack([np.ones((L.shape[0], 1))] + cols)

    def ajustar(self, razoes, y_rel, grupos=None):
        y = np.log(np.clip(np.asarray(y_rel, dtype=float), 1e-3, None))
        if self.usar_grupos and grupos is not None:
            G = np.asarray(grupos, dtype=int)
            self.grupos_por_fase = [sorted(set(G[:, i].tolist()))
                                    for i in range(4)]
        X = self._montar(razoes, grupos)
        p = X.shape[1]
        # ridge somente nos gammas (colunas apos intercepto + 4 lambdas)
        pen = np.zeros(p)
        pen[5:] = np.sqrt(self.ridge)
        Xa = np.vstack([X, np.diag(pen)[5:]]) if p > 5 else X
        ya = np.concatenate([y, np.zeros(p - 5)]) if p > 5 else y
        lb = np.full(p, -np.inf)
        ub = np.full(p, np.inf)
        if self.lambda_nn:
            lb[1:5] = 0.0
        sol = lsq_linear(Xa, ya, bounds=(lb, ub), method="bvls")
        b = sol.x
        self.b0 = float(b[0])
        self.lambdas = b[1:5].copy()
        self.gammas = [dict() for _ in range(4)]
        for k, (i, g) in enumerate(self._colmap):
            self.gammas[i][g] = float(b[5 + k])
        self.calibrado = True
        self.n_obs = int(len(y))
        self.n_parametros = int(p)
        return self

    def prever_rel(self, razoes, grupos=None):
        L = _log_razoes(razoes)
        out = self.b0 + L @ self.lambdas
        if self.usar_grupos and grupos is not None:
            G = np.asarray(grupos, dtype=int)
            for i in range(4):
                for k in range(G.shape[0]):
                    out[k] += self.gammas[i].get(int(G[k, i]), 0.0)
        return np.clip(np.exp(out), 0.05, 1.3)

    # -- serializacao -------------------------------------------------------
    def to_dict(self):
        return {"tipo": "jensen_modificado" if self.usar_grupos else "jensen",
                "b0": self.b0, "lambdas": [float(x) for x in self.lambdas],
                "gammas": [{str(g): v for g, v in d.items()}
                           for d in self.gammas],
                "ridge": self.ridge, "lambda_nao_negativo": self.lambda_nn,
                "calibrado": self.calibrado, "n_obs": self.n_obs}

    @classmethod
    def from_dict(cls, d):
        m = cls(usar_grupos=(d["tipo"] == "jensen_modificado"),
                ridge=d.get("ridge", 1.0),
                lambda_nao_negativo=d.get("lambda_nao_negativo", True))
        m.b0 = d["b0"]
        m.lambdas = np.array(d["lambdas"], dtype=float)
        m.gammas = [{int(g): v for g, v in x.items()} for x in d["gammas"]]
        m.calibrado = d.get("calibrado", True)
        m.n_obs = d.get("n_obs", 0)
        return m

    @classmethod
    def prior_generico(cls):
        """Sem calibracao: b0 = 0 e lambda uniforme = Ky FAO-33 / 4 por fase
        NAO e usado; aqui Y/Ym = (ETR/ETm_total)^Ky aproximado por lambda_i
        iguais a Ky/4 aplicados sobre as 4 razoes (media geometrica)."""
        m = cls(usar_grupos=False)
        m.lambdas = np.full(4, config.KY_PRIOR / 4.0)
        m.b0 = 0.0
        m.calibrado = False
        return m
