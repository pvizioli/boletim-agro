# -*- coding: utf-8 -*-
"""Validacao cruzada e metricas. Foco: medir erro FORA da amostra.

Dataset (lista de observacoes):
  {"mun": str, "ano": int, "y": produtividade observada (sc/ha),
   "razoes": [r1..r4]  (ETR/ETm por fase),
   "feat": [vetor_fase1..vetor_fase4]  (para agrupamento)}

Metodos comparados:
  media_mun        - media historica do municipio (baseline obrigatorio)
  jensen           - Jensen classico (lambda por fase)
  jensen_grupos    - Jensen modificado, grupos climatologicos estaveis
Protocolos:
  loyo - leave-one-year-out (preve uma safra nova)
  lomo - leave-one-municipality-out (preve municipio sem historico)
"""

import numpy as np

from . import agrupamento, config
from .jensen import Jensen


def metricas(obs, prev):
    y = np.asarray(obs, dtype=float)
    p = np.asarray(prev, dtype=float)
    e = p - y
    ss_res = float(np.sum(e ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    rho = float(np.corrcoef(y, p)[0, 1]) if y.std() > 0 and p.std() > 0 else float("nan")
    return {"n": int(len(y)), "rmse": float(np.sqrt(np.mean(e ** 2))),
            "mae": float(np.mean(np.abs(e))), "vies": float(np.mean(e)),
            "r2": 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
            "corr": rho}


def _ym(treino, modo):
    if modo == "global_p95":
        v = float(np.percentile([o["y"] for o in treino], 95))
        return lambda mun: v
    por = {}
    for o in treino:
        por.setdefault(o["mun"], []).append(o["y"])
    maxs = {m: max(v) for m, v in por.items()}
    media = float(np.mean(list(maxs.values())))
    return lambda mun: maxs.get(mun, media)


def _grupos_clim(treino, todos_mun_feat, kmax, min_tam, seed):
    """Agrupa com features climatologicas (media dos anos de treino)."""
    por = {}
    for o in treino:
        por.setdefault(o["mun"], []).append(o["feat"])
    clim = {m: agrupamento.media_anos(v) for m, v in por.items()}
    agr = agrupamento.agrupar(clim, kmax=kmax, min_tamanho=min_tam, seed=seed)
    return agr, clim


def _labels(agr, clim, mun, feat_clim_mun=None):
    out = []
    for i in range(4):
        f = agr["fases"][i]
        if mun in f["labels"]:
            out.append(f["labels"][mun])
        else:
            out.append(agrupamento.atribuir(f, feat_clim_mun[i]))
    return out


def prever_fold(treino, teste, metodo, ym_modo="mun_max", kmax=5,
                min_tam=3, seed=0, ridge=1.0, lambda_nn=True):
    """Ajusta no treino e preve o teste. Retorna lista de y previsto (sc/ha)."""
    ym = _ym(treino, ym_modo)
    if metodo == "media_mun":
        por = {}
        for o in treino:
            por.setdefault(o["mun"], []).append(o["y"])
        g = float(np.mean([o["y"] for o in treino]))
        return [float(np.mean(por[o["mun"]])) if o["mun"] in por else g
                for o in teste]
    R = [o["razoes"] for o in treino]
    yrel = [o["y"] / ym(o["mun"]) for o in treino]
    if metodo == "jensen":
        m = Jensen(usar_grupos=False, ridge=ridge, lambda_nao_negativo=lambda_nn)
        m.ajustar(R, yrel)
        rel = m.prever_rel([o["razoes"] for o in teste])
        return [float(r * ym(o["mun"])) for r, o in zip(rel, teste)]
    if metodo == "jensen_grupos":
        agr, clim = _grupos_clim(treino, None, kmax, min_tam, seed)
        # municipios de teste fora do treino: clima do proprio teste
        feat_teste = {}
        for o in teste:
            feat_teste.setdefault(o["mun"], []).append(o["feat"])
        G_tr = [_labels(agr, clim, o["mun"]) for o in treino]
        m = Jensen(usar_grupos=True, ridge=ridge, lambda_nao_negativo=lambda_nn)
        m.ajustar(R, yrel, G_tr)
        G_te = []
        for o in teste:
            fc = None
            if o["mun"] not in agr["fases"][0]["labels"]:
                fc = agrupamento.media_anos(feat_teste[o["mun"]])
            G_te.append(_labels(agr, clim, o["mun"], fc))
        rel = m.prever_rel([o["razoes"] for o in teste], G_te)
        return [float(r * ym(o["mun"])) for r, o in zip(rel, teste)]
    raise ValueError("metodo desconhecido: " + metodo)


def cv(obs, metodo, protocolo="loyo", **kw):
    """Retorna (metricas, lista de dicts {mun, ano, y, prev})."""
    saida = []
    if protocolo == "loyo":
        chaves = sorted(set(o["ano"] for o in obs))
        for a in chaves:
            tr = [o for o in obs if o["ano"] != a]
            te = [o for o in obs if o["ano"] == a]
            for o, p in zip(te, prever_fold(tr, te, metodo, **kw)):
                saida.append({"mun": o["mun"], "ano": o["ano"],
                              "y": o["y"], "prev": p})
    elif protocolo == "lomo":
        chaves = sorted(set(o["mun"] for o in obs))
        for mu in chaves:
            tr = [o for o in obs if o["mun"] != mu]
            te = [o for o in obs if o["mun"] == mu]
            for o, p in zip(te, prever_fold(tr, te, metodo, **kw)):
                saida.append({"mun": o["mun"], "ano": o["ano"],
                              "y": o["y"], "prev": p})
    else:
        raise ValueError(protocolo)
    return metricas([s["y"] for s in saida], [s["prev"] for s in saida]), saida


def protocolo_tese_in_sample(obs_ano, grupos_ano, ym_modo="global_max"):
    """Reproduz o protocolo da tese: ajusta UM modelo por ano com todos os
    municipios e mede o erro NA MESMA amostra (EQM). grupos_ano: lista de
    [g1..g4] por observacao (agrupamento do proprio ano).
    Retorna dict com EQM Jensen, EQM modificado e % de melhora (Eq. 4.7),
    alem de n_obs e n_parametros (para ver a saturacao)."""
    y = np.array([o["y"] for o in obs_ano])
    ym = float(y.max())  # tese: maior rendimento verificado no periodo
    R = [o["razoes"] for o in obs_ano]
    mj = Jensen(usar_grupos=False, ridge=1e-9, lambda_nao_negativo=False)
    mj.ajustar(R, y / ym)
    pj = mj.prever_rel(R) * ym
    mm = Jensen(usar_grupos=True, ridge=1e-9, lambda_nao_negativo=False)
    mm.ajustar(R, y / ym, grupos_ano)
    pm = mm.prever_rel(R, grupos_ano) * ym
    eqm_j = float(np.mean((y - pj) ** 2))
    eqm_m = float(np.mean((y - pm) ** 2))
    return {"eqm_jensen": eqm_j, "eqm_modificado": eqm_m,
            "melhora_pct": 100.0 * (eqm_j - eqm_m) / eqm_j if eqm_j > 0 else float("nan"),
            "n_obs": len(y), "n_parametros_modificado": mm.n_parametros,
            "n_parametros_jensen": mj.n_parametros}
