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
    sel = [itens_por_uf[u] for u in ufs if u in itens_por_uf]
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
