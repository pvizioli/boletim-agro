"""
Conector: colheita SUB-REGIONAL (piloto Imea/MT) — boletim-agro
================================================================

Camada de granularidade entre a UF e o municipio. Quando existe % de
plantio/colheita para a macrorregiao do municipio (ex.: Imea publica
semanalmente as 7 macrorregioes de MT), a estimativa municipal usa o
% REGIONAL em vez do estadual — bem mais fiel a realidade local.

Arquivos:
  config/crosswalk_regioes.csv    codigo_ibge -> (orgao, regiao_id, regiao_nome)
  data/colheita/colheita_regional.csv   uf+regiao_id -> % da semana

Regras (mesmos principios do colheita.csv):
  - linha sem pct_plantado E sem pct_colhido nao gera estimativa (fallback UF);
  - se a safra regional difere da safra corrente da UF, ignora (nao mistura
    safras na virada);
  - toda estimativa municipal e derivada e rotulada (granularidade, fonte).
"""

import csv
import os


def _num(v):
    v = (v or "").strip().replace(",", ".")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def carregar_crosswalk(caminho):
    """codigo_ibge (str) -> {orgao, regiao_id, regiao_nome, uf}."""
    m = {}
    if not os.path.isfile(caminho):
        return m
    with open(caminho, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ibge = (row.get("codigo_ibge") or "").strip()
            rid = (row.get("regiao_id") or "").strip()
            if not ibge or not rid:
                continue
            m[ibge] = {
                "orgao": (row.get("orgao") or "").strip(),
                "regiao_id": rid,
                "regiao_nome": (row.get("regiao_nome") or "").strip() or rid,
                "uf": (row.get("uf") or "").strip(),
            }
    return m


def carregar_regional(caminho):
    """(uf, regiao_id) -> item regional com pct/fonte/safra."""
    itens = {}
    if not os.path.isfile(caminho):
        return itens
    with open(caminho, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            uf = (row.get("uf") or "").strip()
            rid = (row.get("regiao_id") or "").strip()
            if not uf or not rid:
                continue
            itens[(uf, rid)] = {
                "uf": uf,
                "regiao_id": rid,
                "regiao_nome": (row.get("regiao_nome") or "").strip() or rid,
                "safra": (row.get("safra") or "").strip() or None,
                "data_referencia": (row.get("data_referencia") or "").strip() or None,
                "pct_plantado": _num(row.get("pct_plantado")),
                "pct_colhido": _num(row.get("pct_colhido")),
                "produtividade_kg_ha": _num(row.get("produtividade_kg_ha")),
                "condicao_lavoura": (row.get("condicao_lavoura") or "").strip() or None,
                "fonte": (row.get("fonte") or "").strip() or None,
            }
    return itens


def colheita_municipio_regional(ibge, uf, area_ha, crosswalk, itens_reg,
                                safra_uf=None):
    """Colheita derivada do municipio usando o % da SUA macrorregiao.

    Retorna None quando nao ha regiao mapeada ou dado regional utilizavel —
    o pipeline entao cai no % estadual (colheita_csv.colheita_municipio).
    Formato de saida identico ao do fallback estadual, com granularidade
    e regiao proprias.
    """
    cw = crosswalk.get(str(ibge or "").strip())
    if not cw or (cw.get("uf") and cw["uf"] != uf):
        return None
    it = itens_reg.get((uf, cw["regiao_id"]))
    if not it:
        return None
    pp = it.get("pct_plantado")
    pc = it.get("pct_colhido")
    if pp is None and pc is None:
        return None
    if safra_uf and it.get("safra") and it["safra"] != safra_uf:
        return None
    out = {
        "pct_plantado": pp,
        "pct_colhido": pc,
        "area_soja_ha": area_ha,
        "fonte": it.get("fonte"),
        "data_referencia": it.get("data_referencia"),
        "granularidade": "regional (" + it["regiao_nome"] + ") aplicado ao municipio",
        "regiao": it["regiao_nome"],
        "derivado": True,
    }
    if area_ha is not None:
        if pp is not None:
            out["ha_plantado_estim"] = int(round(area_ha * pp / 100.0))
        if pc is not None:
            out["ha_colhido_estim"] = int(round(area_ha * pc / 100.0))
    return out
