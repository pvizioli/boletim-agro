# -*- coding: utf-8 -*-
"""Previsao de produtividade da soja a partir de series de clima em JSON.

Fluxo: serie observada (+ previsao do tempo) -> completar ETo -> balanco
hidrico por fase -> Jensen (calibrado ou prior) -> sc/ha, com cenarios de
clima para os dias que faltam (anos analogos) e intervalo de incerteza.

Integridade (regras do projeto): a saida e sempre rotulada "estimativa",
leva confianca e premissas; nunca substitui dado oficial.
"""

import datetime
import math

import numpy as np

from . import balanco_hidrico, config, ingestao
from .jensen import Jensen


def _data(d):
    return datetime.date.fromisoformat(d)


def deslocar_ano(serie_analogo, ano_origem, ano_destino):
    """Reaproveita a serie de outro ano (mesmo dia/mes). 29/fev ignorado."""
    out = {}
    for dia, reg in serie_analogo.items():
        d = _data(dia)
        try:
            novo = d.replace(year=d.year + (ano_destino - ano_origem))
        except ValueError:
            continue
        out[novo.isoformat()] = reg
    return out


def _preencher(base, analogo_deslocado, apos):
    """Completa os dias > `apos` (ISO) ausentes em base com o analogo."""
    out = {d: dict(r) for d, r in base.items()}
    for dia, reg in analogo_deslocado.items():
        if dia <= apos:
            continue
        atual = out.get(dia)
        if atual is None or atual.get("prec") is None or atual.get("eto") is None:
            out[dia] = dict(reg)
    return out


def _rel_para_sc(modelo, razoes, ym, grupos=None):
    r = [1.0 if x is None else x for x in razoes]
    rel = float(modelo.prever_rel([r], None if grupos is None else [grupos])[0])
    return rel, rel * ym


def prever_safra(serie, plantio, hoje, ym_sc_ha, modelo=None, cad_mm=None,
                 lat=None, alt_m=0.0, analogos=None, grupos=None,
                 rmse_modelo_sc_ha=None):
    """
    serie     : serie normalizada observada + previsao (ingestao.*)
    plantio   : 'AAAA-MM-DD' (assumido; ver README sobre ZARC/colheita.csv)
    hoje      : 'AAAA-MM-DD' data de referencia (ultimo dia observado)
    ym_sc_ha  : produtividade potencial de referencia (sc/ha) -- obrigatorio
    modelo    : Jensen calibrado; None => prior generico (confianca baixa)
    analogos  : {ano: serie_diaria} anos historicos para cenarios
    grupos    : [g1..g4] do municipio (se o modelo usa grupos)
    """
    calibrado = modelo is not None and modelo.calibrado
    if modelo is None:
        modelo = Jensen.prior_generico()
    if lat is not None:
        serie, eto_resumo = ingestao.completar_eto(serie, lat, alt_m)
    else:
        eto_resumo = {"nota": "lat ausente: ETo nao completada"}

    ano_plantio = _data(plantio).year
    sim_obs = balanco_hidrico.simular(serie, plantio, cad_mm=cad_mm)
    faltantes = sim_obs["dias_faltantes"]
    frac_obs = 1.0 - faltantes / float(config.CICLO_DIAS)
    razoes_obs = balanco_hidrico.razoes(sim_obs)

    cenarios = []
    if faltantes > 0 and analogos:
        for ano, s_an in sorted(analogos.items()):
            if ano == ano_plantio:
                continue
            desl = deslocar_ano(s_an, ano, ano_plantio)
            # analogos de safras que cruzam a virada de ano: aceita-se serie
            # com 2 anos civis; deslocar_ano trata o intervalo inteiro
            comp = _preencher(serie, desl, hoje)
            sim = balanco_hidrico.simular(comp, plantio, cad_mm=cad_mm)
            if sim["dias_faltantes"] > 0.05 * config.CICLO_DIAS:
                continue
            _, sc = _rel_para_sc(modelo, balanco_hidrico.razoes(sim), ym_sc_ha,
                                 grupos)
            cenarios.append({"ano_analogo": ano, "sc_ha": sc,
                             "razoes": balanco_hidrico.razoes(sim)})

    rel_det, sc_det = _rel_para_sc(modelo, razoes_obs, ym_sc_ha, grupos)
    if cenarios:
        v = np.array([c["sc_ha"] for c in cenarios])
        p10, p50, p90 = [float(np.percentile(v, q)) for q in (10, 50, 90)]
        sd_clima = float(v.std(ddof=1)) if len(v) > 1 else 0.0
        metodo = "cenarios_analogos"
    else:
        p10 = p50 = p90 = sc_det
        sd_clima = 0.0
        metodo = "deterministico" if faltantes == 0 else "parcial_sem_cenarios"
    rm = rmse_modelo_sc_ha if rmse_modelo_sc_ha is not None else 0.0
    sd_tot = math.sqrt(sd_clima ** 2 + rm ** 2)
    ic80 = [round(p50 - 1.2816 * sd_tot, 1), round(p50 + 1.2816 * sd_tot, 1)]

    conf = _confianca(calibrado, frac_obs, rmse_modelo_sc_ha, ym_sc_ha,
                      metodo, modelo.n_obs)
    avisos = []
    if not calibrado:
        avisos.append("Modelo sem calibracao regional: prior generico FAO-33 "
                      "(Ky=0,85). Usar apenas como indicativo.")
    if metodo == "parcial_sem_cenarios":
        avisos.append("Dias futuros sem dados e sem anos analogos: fases "
                      "incompletas assumidas SEM estresse (resultado otimista).")
    if frac_obs < 0.5:
        avisos.append("Menos de 50% do ciclo observado: incerteza dominada "
                      "pelo clima futuro.")

    return {
        "rotulo": "estimativa",
        "plantio_assumido": plantio, "data_referencia": hoje,
        "fim_ciclo_estimado": (_data(plantio) + datetime.timedelta(
            days=config.CICLO_DIAS - 1)).isoformat(),
        "fracao_ciclo_com_dados": round(frac_obs, 3),
        "fases": [{"fase": f["fase"], "razao_etr_etm": f["razao"],
                   "etr_mm": f["etr_mm"], "etm_mm": f["etm_mm"],
                   "prec_mm": f["prec_mm"], "dias_faltantes": f["dias_faltantes"]}
                  for f in sim_obs["por_fase"]],
        "agua": {"etr_total_mm": sim_obs["etr_total_mm"],
                 "etm_total_mm": sim_obs["etm_total_mm"],
                 "prec_total_mm": sim_obs["prec_total_mm"],
                 "cad_mm": sim_obs["cad_mm"]},
        "produtividade_rel": round(rel_det, 4),
        "produtividade_sc_ha": {"p10": round(p10, 1), "p50": round(p50, 1),
                                "p90": round(p90, 1)},
        "intervalo_80_total_sc_ha": ic80,
        "metodo_incerteza": metodo, "n_cenarios": len(cenarios),
        "confianca": conf, "ym_sc_ha": round(ym_sc_ha, 1),
        "eto_origem": eto_resumo, "avisos": avisos,
    }


def _confianca(calibrado, frac_obs, rmse, ym, metodo, n_obs):
    if not calibrado:
        return "baixa"
    erro_rel = (rmse / ym) if (rmse is not None and ym) else None
    if frac_obs >= 0.9 and erro_rel is not None and erro_rel <= 0.12 and n_obs >= 60:
        return "alta"
    if frac_obs >= 0.5 and (erro_rel is None or erro_rel <= 0.20):
        return "media"
    return "baixa"
