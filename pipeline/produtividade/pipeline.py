# -*- coding: utf-8 -*-
"""Execucao em lote para o boletim: municipios.csv -> JSON/CSV de previsao.

Regras do projeto: saida rotulada 'estimativa'; falha de um municipio nao
derruba o lote; se TODOS falharem, nada e sobrescrito (preserva a ultima
versao valida).
"""

import csv
import datetime
import json
import os

from . import backtest, config, fontes, ingestao, previsao
from .jensen import Jensen

COLUNAS_CSV = [
    "uf", "regiao_id", "regiao_nome", "municipio", "codigo_ibge", "cultura",
    "safra", "plantio_assumido", "data_referencia", "fracao_ciclo_com_dados",
    "prod_p10_sc_ha", "prod_p50_sc_ha", "prod_p90_sc_ha",
    "ic80_min_sc_ha", "ic80_max_sc_ha", "confianca", "metodo_incerteza",
    "rotulo", "gerado_em"]


def safra_de(plantio):
    a = int(plantio[:4])
    return "%d/%02d" % (a, (a + 1) % 100)


def plantio_para(uf, hoje, plantio_md=None):
    """Plantio da safra corrente: ano de 'hoje' se ja passou da data de
    plantio-padrao, senao o ano anterior (safra em andamento)."""
    md = plantio_md or config.PLANTIO_PADRAO_MD.get(
        uf, config.PLANTIO_MD_FALLBACK)
    d = datetime.date.fromisoformat(hoje)
    cand = datetime.date.fromisoformat("%d-%s" % (d.year, md))
    if cand > d:
        cand = datetime.date.fromisoformat("%d-%s" % (d.year - 1, md))
    return cand.isoformat()


def _analogos(serie_total, ano_corrente, n_anos=12):
    out = {}
    for a in range(ano_corrente - n_anos, ano_corrente):
        ini, fim = "%d-09-01" % a, "%d-04-15" % (a + 1)
        s = {d: r for d, r in serie_total.items() if ini <= d <= fim}
        if len(s) > 200:
            out[a] = s
    return out


def processar_municipio(m, hoje, modelo_json=None, baixar=fontes.baixar_json,
                        plantio=None, cad_mm=None, ym_padrao=None):
    plantio = plantio or plantio_para(m["uf"], hoje)
    ano_pl = int(plantio[:4])
    ini_hist = "%d-09-01" % (ano_pl - 12)
    ontem = (datetime.date.fromisoformat(hoje) -
             datetime.timedelta(days=1)).isoformat()
    obj_h = baixar(fontes.url_open_meteo_historico(m["lat"], m["lon"],
                                                   ini_hist, ontem))
    serie_h = ingestao.de_open_meteo(obj_h)
    obj_p = baixar(fontes.url_open_meteo_previsao(m["lat"], m["lon"], 7, 16))
    serie_p = ingestao.de_open_meteo(obj_p)
    # observado tem prioridade; previsao completa os dias sem dado
    serie = ingestao.mesclar(serie_h, serie_p)
    serie, _ = ingestao.completar_eto(serie, m["lat"])
    analogos = _analogos(serie_h, ano_pl)

    modelo, grupos, ym, rmse = None, None, ym_padrao, None
    if modelo_json:
        mj = modelo_json["modelo"]
        modelo = Jensen.from_dict(mj)
        rmse = modelo_json.get("rmse_cv_loyo_sc_ha")
        ym = (modelo_json.get("ym_sc_ha_por_municipio") or {}).get(
            str(m["codigo_ibge"]), ym_padrao)
        agr = modelo_json.get("agrupamento")
        if modelo.usar_grupos and agr:
            grupos = [agr["fases"][i]["labels"].get(str(m["codigo_ibge"]), 0)
                      for i in range(4)]
    if ym is None:
        raise ValueError("sem Ym (produtividade potencial) para " +
                         str(m["codigo_ibge"]))
    res = previsao.prever_safra(serie, plantio, hoje, ym, modelo=modelo,
                                cad_mm=cad_mm, lat=m["lat"], analogos=analogos,
                                grupos=grupos, rmse_modelo_sc_ha=rmse)
    res.update({"uf": m["uf"], "regiao_id": m.get("regiao_id", ""),
                "regiao_nome": m.get("regiao_nome", ""),
                "municipio": m.get("cidade", ""),
                "codigo_ibge": str(m["codigo_ibge"]), "cultura": "soja",
                "safra": safra_de(plantio),
                "area_soja_ha": m.get("area_soja_ha", 0.0),
                "fonte_clima": ["open-meteo (historico+previsao)"]})
    return res


def agregar_regioes(itens):
    por = {}
    for it in itens:
        por.setdefault((it["regiao_id"], it["regiao_nome"], it["uf"]), []).append(it)
    out = []
    for (rid, rnome, uf), v in sorted(por.items()):
        pesos = [max(x.get("area_soja_ha") or 0.0, 0.0) for x in v]
        if sum(pesos) == 0:
            pesos = [1.0] * len(v)
        W = float(sum(pesos))
        p50 = [x["produtividade_sc_ha"]["p50"] for x in v]
        media = sum(p * w for p, w in zip(p50, pesos)) / W
        var = sum(w * (p - media) ** 2 for p, w in zip(p50, pesos)) / W
        out.append({"uf": uf, "regiao_id": rid, "regiao_nome": rnome,
                    "cultura": "soja", "safra": v[0]["safra"],
                    "n_municipios": len(v),
                    "produtividade_media_sc_ha": round(media, 1),
                    "desvio_padrao": round(var ** 0.5, 1),
                    "rotulo": "estimativa",
                    "confianca_min": min((x["confianca"] for x in v),
                                         key=["baixa", "media", "alta"].index)})
    return out


def rodar_lote(municipios, hoje, saida_dir, modelo_json=None,
               baixar=fontes.baixar_json, ym_padrao=None):
    itens, falhas = [], []
    for m in municipios:
        try:
            itens.append(processar_municipio(m, hoje, modelo_json, baixar,
                                             ym_padrao=ym_padrao))
        except Exception as e:  # noqa: BLE001 - falha isolada por municipio
            falhas.append({"codigo_ibge": str(m.get("codigo_ibge")),
                           "erro": str(e)[:200]})
    if not itens:
        return {"gravado": False, "falhas": falhas}
    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc = {"schema": config.SCHEMA_SAIDA, "gerado_em": agora,
           "data_referencia": hoje,
           "modelo": {"id": "jensen-modificado-v1",
                      "calibrado": bool(modelo_json),
                      "descricao": "Jensen (1968) com indicadores de grupo "
                                   "(Rodrigues, dissertacao); CPU, sem GPU",
                      "calibracao": None if not modelo_json else {
                          k: modelo_json.get(k) for k in
                          ("n_obs", "anos", "rmse_cv_loyo_sc_ha", "r2_cv_loyo")}},
           "avisos": ["Estimativa de modelo. Nao substitui dado oficial "
                      "(IMEA/CONAB/IBGE). Plantio assumido por UF; ver config."],
           "itens": [{k: v for k, v in it.items() if k != "area_soja_ha"}
                     for it in itens],
           "regioes": agregar_regioes(itens),
           "falhas": falhas}
    os.makedirs(saida_dir, exist_ok=True)
    cam_json = os.path.join(saida_dir, "previsao_produtividade.json")
    tmp = cam_json + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, cam_json)
    cam_csv = os.path.join(saida_dir, "previsao_produtividade.csv")
    with open(cam_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUNAS_CSV)
        for it in itens:
            p = it["produtividade_sc_ha"]
            ic = it["intervalo_80_total_sc_ha"]
            w.writerow([it["uf"], it["regiao_id"], it["regiao_nome"],
                        it["municipio"], it["codigo_ibge"], "soja",
                        it["safra"], it["plantio_assumido"],
                        it["data_referencia"], it["fracao_ciclo_com_dados"],
                        p["p10"], p["p50"], p["p90"], ic[0], ic[1],
                        it["confianca"], it["metodo_incerteza"], "estimativa",
                        agora])
    # benchmark no formato lido pelo Pilar 2 do MdG (nome de coluna igual)
    cam_bm = os.path.join(saida_dir, "benchmark_regional_previsto.csv")
    with open(cam_bm, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cultura", "safra", "uf", "regiao_id", "regiao_nome",
                    "produtividade_media_sc_ha", "desvio_padrao", "fonte",
                    "rotulo"])
        for r in doc["regioes"]:
            w.writerow(["soja", r["safra"], r["uf"], r["regiao_id"],
                        r["regiao_nome"], r["produtividade_media_sc_ha"],
                        r["desvio_padrao"], "modelo_jensen_modificado",
                        "estimativa"])
    return {"gravado": True, "itens": len(itens), "falhas": falhas,
            "arquivos": [cam_json, cam_csv, cam_bm]}
