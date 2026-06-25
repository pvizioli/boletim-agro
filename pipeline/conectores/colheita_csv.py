"""
Conector de colheita por CSV — boletim-agro
===========================================

Lê data/colheita/colheita.csv (uma linha por UF, nivel estadual) e monta o
bloco `colheita` para cada distrito conforme a(s) UF(s) dele.

O CSV é produzido no chat (ritual "atualizar colheita": Claude busca Emater-RS,
Deral-PR e Epagri-SC, triangula e gera o CSV) e commitado por Pedro apos
conferencia — esse commit É a validação humana. Por isso o bloco sai com
status "validado".

Colunas esperadas:
  uf, regiao, granularidade, cultura, safra, data_referencia,
  pct_plantado, pct_colhido, produtividade_kg_ha, area_ha, producao_t,
  vs_safra_anterior, condicao_lavoura, fonte

stdlib apenas.
"""

import csv
import os


def _num(v):
    if v is None:
        return None
    s = str(v).strip().replace("+", "")
    if s == "":
        return None
    try:
        f = float(s.replace(",", "."))
        return int(f) if f == int(f) else f
    except Exception:
        return None


def _item(row):
    """Monta o item (linha estadual) que a aba Colheita do site consome."""
    return {
        "regiao": (row.get("regiao") or row.get("uf") or "").strip(),
        "uf": (row.get("uf") or "").strip().upper(),
        "granularidade": (row.get("granularidade") or "estadual").strip(),
        "pct_plantado": _num(row.get("pct_plantado")),
        "pct_colhido": _num(row.get("pct_colhido")),
        # nao temos comparativo de PROGRESSO (p.p.) -> ficam null para nao
        # exibir rotulo enganoso; a variacao de producao vai em campo proprio
        "vs_media5anos": None,
        "vs_safra_anterior": None,
        "condicao_lavoura": (row.get("condicao_lavoura") or "").strip() or None,
        "fonte": (row.get("fonte") or "").strip() or None,
        "data_referencia": (row.get("data_referencia") or "").strip() or None,
        "safra": (row.get("safra") or "").strip() or None,
        # contexto extra (pronto para exibicao futura no site):
        "produtividade_kg_ha": _num(row.get("produtividade_kg_ha")),
        "area_ha": _num(row.get("area_ha")),
        "producao_t": _num(row.get("producao_t")),
        "var_producao_pct": _num(row.get("vs_safra_anterior")),
        "preco_rs_sc": _num(row.get("preco_rs_sc")),
        "preco_data": (row.get("preco_data") or "").strip() or None,
        "preco_fonte": (row.get("preco_fonte") or "").strip() or None,
    }


def carregar(caminho):
    """Lê o CSV -> dict {UF: item}. Ausencia de arquivo = dict vazio."""
    itens = {}
    if not caminho or not os.path.exists(caminho):
        return itens
    with open(caminho, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            it = _item(row)
            if it["uf"]:
                itens[it["uf"]] = it
    return itens


def bloco_para_distrito(itens_por_uf, ufs):
    """Monta o bloco `colheita` de um distrito a partir das UFs dele.
    Retorna None se nao houver dado para nenhuma UF (o pipeline entao
    preserva a colheita anterior, sem regredir)."""
    sel = [it for it in (itens_por_uf.get(u) for u in ufs)
           if it and (it.get("pct_plantado") is not None
                      or it.get("pct_colhido") is not None)]
    if not sel:
        return None
    datas = [i["data_referencia"] for i in sel if i.get("data_referencia")]
    fontes = sorted({i["fonte"] for i in sel if i.get("fonte")})
    return {
        "status": "validado",
        "fonte": fontes[0] if len(fontes) == 1 else "Órgãos estaduais (ver linhas)",
        "granularidade": "estadual",
        "data_referencia": max(datas) if datas else None,
        "cultura": "soja",
        "itens": sel,
    }


def colheita_municipio(estado, area_ha):
    """Colheita derivada de um municipio: area real (PAM) x % estadual.

    estado  = item estadual retornado por carregar() (tem pct_plantado/colhido)
    area_ha = area_soja_ha do municipio (pode ser None)
    Retorna None se nao houver dado estadual para a UF do municipio.
    """
    if not estado:
        return None
    pp = estado.get("pct_plantado")
    pc = estado.get("pct_colhido")
    if pp is None and pc is None:
        return None
    out = {
        "pct_plantado": pp,
        "pct_colhido": pc,
        "area_soja_ha": area_ha,
        "fonte": estado.get("fonte"),
        "data_referencia": estado.get("data_referencia"),
        "granularidade": "estadual aplicado ao municipio",
        "derivado": True,
    }
    if area_ha is not None:
        if pp is not None:
            out["ha_plantado_estim"] = int(round(area_ha * pp / 100.0))
        if pc is not None:
            out["ha_colhido_estim"] = int(round(area_ha * pc / 100.0))
    return out


def preco_para_distrito(itens_por_uf, ufs):
    """Preco da saca para o distrito: a primeira UF dele que tiver preco."""
    for u in ufs:
        it = itens_por_uf.get(u)
        if it and it.get("preco_rs_sc") is not None:
            return {"valor": it["preco_rs_sc"], "uf": u,
                    "data": it.get("preco_data"), "fonte": it.get("preco_fonte"),
                    "unidade": "R$/sc 60kg"}
    return None
