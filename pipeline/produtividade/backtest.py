# -*- coding: utf-8 -*-
"""Calibracao e backtest com dados REAIS (roda onde ha rede: GitHub Actions).

Entradas: rendimentos observados (IBGE PAM via SIDRA, ou CSV proprio) e
series de clima por municipio-safra. A funcao `obter_serie` e injetada,
para o codigo ser testavel offline.

Regra de selecao (aprendida nos experimentos sinteticos): o Jensen
modificado (com grupos) so substitui o Jensen simples se vencer em LOYO
E em LOMO por margem >= MARGEM_GRUPOS; caso contrario, fica o simples.
"""

import csv
import datetime
import json

import numpy as np

from . import agrupamento, avaliacao, balanco_hidrico, config, fontes, ingestao
from .jensen import Jensen

MARGEM_GRUPOS = 0.05  # 5% de reducao de RMSE


def de_sidra(obj):
    """Resposta JSON da API SIDRA (lista; 1a linha = cabecalho).
    Retorna {(codigo_ibge, ano): rendimento_kg_ha}. Valores '-', '...',
    'X' viram ausentes."""
    if not obj or len(obj) < 2:
        return {}
    cab = obj[0]
    k_ano = next(k for k, v in cab.items() if k.endswith("N") and v == "Ano")
    k_mun = next(k for k, v in cab.items()
                 if k.endswith("N") and v.startswith("Munic"))
    k_mun_c = k_mun[:-1] + "C"
    k_ano_c = k_ano[:-1] + "C"
    saida = {}
    for r in obj[1:]:
        try:
            v = float(r["V"])
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        saida[(str(r[k_mun_c]), int(r[k_ano_c]))] = v
    return saida


def montar_dataset(rendimentos, municipios, obter_serie, plantio_md=None):
    """rendimentos: {(cod, ano_pam): kg/ha}. municipios: lista de dicts
    {codigo_ibge, uf, lat, lon}. Ano PAM Y <-> plantio no ano Y-1."""
    obs = []
    for m in municipios:
        md = plantio_md or config.PLANTIO_PADRAO_MD.get(
            m["uf"], config.PLANTIO_MD_FALLBACK)
        for (cod, ano), kg in sorted(rendimentos.items()):
            if cod != str(m["codigo_ibge"]):
                continue
            plantio = "%d-%s" % (ano - 1, md)
            serie = obter_serie(m, ano - 1)
            if not serie:
                continue
            serie, _ = ingestao.completar_eto(serie, float(m["lat"]))
            sim = balanco_hidrico.simular(serie, plantio)
            if sim["dias_faltantes"] > 0.05 * config.CICLO_DIAS:
                continue
            obs.append({"mun": cod, "ano": ano, "y": kg / config.SACA_KG,
                        "razoes": balanco_hidrico.razoes(sim),
                        "feat": agrupamento.features_fases(serie, plantio)})
    return obs


def rodar_backtest(obs, ym_modo="mun_max", kmax=5, min_tam=3):
    """Compara metodos em LOYO e LOMO e escolhe o modelo."""
    rel = {"n_obs": len(obs),
           "n_municipios": len(set(o["mun"] for o in obs)),
           "anos": sorted(set(o["ano"] for o in obs)), "cv": {}}
    for prot in ("loyo", "lomo"):
        rel["cv"][prot] = {}
        for metodo in ("media_mun", "jensen", "jensen_grupos"):
            m, _ = avaliacao.cv(obs, metodo, prot, ym_modo=ym_modo,
                                kmax=kmax, min_tam=min_tam)
            rel["cv"][prot][metodo] = {k: (round(v, 4) if isinstance(v, float) else v)
                                       for k, v in m.items()}
    c = rel["cv"]
    ganha = all(c[p]["jensen_grupos"]["rmse"] <
                (1 - MARGEM_GRUPOS) * c[p]["jensen"]["rmse"]
                for p in ("loyo", "lomo"))
    rel["modelo_escolhido"] = "jensen_grupos" if ganha else "jensen"
    rel["bate_baseline_media"] = {
        p: c[p][rel["modelo_escolhido"]]["rmse"] < c[p]["media_mun"]["rmse"]
        for p in ("loyo", "lomo")}
    return rel


def calibrar(obs, relatorio, ym_modo="mun_max", kmax=5, min_tam=3, seed=0):
    """Ajusta o modelo final com TODOS os dados e devolve JSON-serializavel
    (modelo + ym por municipio + grupos + metricas de CV para a previsao)."""
    por = {}
    for o in obs:
        por.setdefault(o["mun"], []).append(o["y"])
    ym = {m: max(v) for m, v in por.items()}
    usar = relatorio["modelo_escolhido"] == "jensen_grupos"
    R = [o["razoes"] for o in obs]
    yrel = [o["y"] / ym[o["mun"]] for o in obs]
    agr = None
    modelo = Jensen(usar_grupos=usar)
    if usar:
        clim = {}
        feats = {}
        for o in obs:
            feats.setdefault(o["mun"], []).append(o["feat"])
        clim = {m: agrupamento.media_anos(v) for m, v in feats.items()}
        agr = agrupamento.agrupar(clim, kmax=kmax, min_tamanho=min_tam, seed=seed)
        G = [[agr["fases"][i]["labels"][o["mun"]] for i in range(4)] for o in obs]
        modelo.ajustar(R, yrel, G)
    else:
        modelo.ajustar(R, yrel)
    cv = relatorio["cv"]["loyo"][relatorio["modelo_escolhido"]]
    return {"modelo": modelo.to_dict(), "ym_sc_ha_por_municipio": ym,
            "agrupamento": agr, "rmse_cv_loyo_sc_ha": cv["rmse"],
            "r2_cv_loyo": cv["r2"], "n_obs": len(obs),
            "anos": relatorio["anos"], "ym_modo": ym_modo,
            "gerado_em": datetime.datetime.now(
                datetime.timezone.utc).isoformat()}


def obter_serie_open_meteo(m, ano_plantio, baixar=fontes.baixar_json):
    """Serie historica Set/ano_plantio .. Abr/ano+1 via Open-Meteo archive."""
    ini = "%d-09-01" % ano_plantio
    fim = "%d-04-15" % (ano_plantio + 1)
    obj = baixar(fontes.url_open_meteo_historico(m["lat"], m["lon"], ini, fim))
    return ingestao.de_open_meteo(obj)


def carregar_municipios_csv(caminho, uf=None):
    """Le config/municipios.csv do boletim (colunas cidade, codigo_ibge,
    uf, latitude, longitude, area_soja_ha)."""
    out = []
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if uf and r.get("uf") != uf:
                continue
            try:
                out.append({"codigo_ibge": r["codigo_ibge"], "uf": r["uf"],
                            "cidade": r.get("cidade", ""),
                            "lat": float(r["latitude"]),
                            "lon": float(r["longitude"]),
                            "area_soja_ha": float(r.get("area_soja_ha") or 0),
                            "regiao_id": r.get("distrito_id", ""),
                            "regiao_nome": r.get("regional", "")})
            except (KeyError, ValueError):
                continue
    return out
