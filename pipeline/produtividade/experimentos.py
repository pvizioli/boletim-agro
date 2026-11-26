# -*- coding: utf-8 -*-
"""Experimentos reprodutiveis sobre dados SINTETICOS (ver simulacao.py).

  python -m produtividade.experimentos            # imprime e grava JSON

E1  Protocolo da tese (ajuste por ano, erro in-sample) com o numero de
    grupos da Tabela 4.1 da tese; compara agrupamento real x rotulos
    ALEATORIOS com o mesmo numero de grupos.
E2  Validacao cruzada (LOYO e LOMO) de: media do municipio, Jensen,
    Jensen modificado com grupos climatologicos.
E3  Recuperacao dos lambdas verdadeiros (teste da implementacao).
"""

import json
import os
import sys

import numpy as np

from . import agrupamento, avaliacao, simulacao

# Numero de grupos por fase, Tabela 4.1 da tese (k-medias + d-HC)
K_TESE = {2003: (3, 6, 4, 6), 2004: (12, 10, 5, 8), 2005: (10, 3, 10, 5),
          2006: (6, 3, 3, 4), 2007: (3, 4, 7, 3)}


def _grupos_forcados(oa, ks, seed=0):
    muns = [o["mun"] for o in oa]
    feats = {o["mun"]: o["feat"] for o in oa}
    cols = []
    for i, k in enumerate(ks):
        X = np.vstack([feats[m][i] for m in muns])
        Z, _, _ = agrupamento._padronizar(X)
        lab, _, _ = agrupamento.kmeans(Z, k, seed=seed)
        cols.append(lab)
    return [[int(cols[i][j]) for i in range(4)] for j in range(len(oa))]


def e1(cenario, seed=42, reps=60):
    d = simulacao.gerar(cenario=cenario, seed=seed)
    linhas = []
    for ano, ks in K_TESE.items():
        oa = [o for o in d["obs"] if o["ano"] == ano]
        G = _grupos_forcados(oa, ks)
        real = avaliacao.protocolo_tese_in_sample(oa, G)
        rng = np.random.default_rng(ano)
        aleat = []
        for _ in range(reps):
            Gr = [[int(rng.integers(0, k)) for k in ks] for _ in oa]
            aleat.append(avaliacao.protocolo_tese_in_sample(oa, Gr)["melhora_pct"])
        linhas.append({"ano": ano, "k": list(ks),
                       "n_obs": real["n_obs"],
                       "n_parametros_modificado": real["n_parametros_modificado"],
                       "melhora_agrupamento_real_pct": round(real["melhora_pct"], 1),
                       "melhora_rotulos_aleatorios_pct_media": round(float(np.mean(aleat)), 1),
                       "melhora_rotulos_aleatorios_pct_p90": round(float(np.percentile(aleat, 90)), 1)})
    return linhas


def e2(cenario, sementes=range(20), anos=(2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010)):
    acc = {}
    for s in sementes:
        d = simulacao.gerar(cenario=cenario, seed=s, anos=anos)
        for prot in ("loyo", "lomo"):
            for metodo in ("media_mun", "jensen", "jensen_grupos"):
                m, _ = avaliacao.cv(d["obs"], metodo, prot)
                acc.setdefault((prot, metodo), []).append(m["rmse"])
    saida = {}
    for (prot, metodo), v in acc.items():
        saida.setdefault(prot, {})[metodo] = {
            "rmse_sc_ha_media": round(float(np.mean(v)), 2),
            "rmse_sc_ha_dp": round(float(np.std(v)), 2)}
    for prot in saida:
        b = np.array(acc[(prot, "jensen")])
        g = np.array(acc[(prot, "jensen_grupos")])
        saida[prot]["grupos_melhor_que_jensen_em_n_de"] = "%d/%d" % (
            int(np.sum(g < b)), len(b))
    return saida


def e3(seed=7):
    d = simulacao.gerar(cenario="sem_efeito", seed=seed, ruido=0.03,
                        anos=tuple(range(2003, 2013)))
    from .jensen import Jensen
    ym = {}
    for o in d["obs"]:
        ym[o["mun"]] = max(ym.get(o["mun"], 0), o["y"])
    m = Jensen(lambda_nao_negativo=True).ajustar(
        [o["razoes"] for o in d["obs"]], [o["y"] / ym[o["mun"]] for o in d["obs"]])
    return {"lambda_verdade": d["lambdas"],
            "lambda_estimado": [round(float(x), 3) for x in m.lambdas]}


def main():
    res = {"aviso": "Dados sinteticos: validam a implementacao e o efeito de "
                    "sobreajuste; nao medem acuracia no mundo real."}
    for cen in ("sem_efeito", "clusters_reais"):
        res["E1_" + cen] = e1(cen)
        res["E2_" + cen] = e2(cen)
    res["E3_recuperacao_lambda"] = e3()
    caminho = os.path.join(os.path.dirname(__file__), "docs",
                           "resultados_simulacao.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
