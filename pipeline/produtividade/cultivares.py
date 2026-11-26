# -*- coding: utf-8 -*-
"""Cultivares de soja por regiao -> ciclo e coortes para o balanco hidrico.

Entrada (CSV, ver docs/cultivares_template.csv):
  regiao_id, cultivar, gmr, participacao_pct, ciclo_dias (opcional),
  populacao_mil_plantas_ha, habito (determinado|indeterminado|semi),
  tecnologia, observacao
Sem ciclo_dias, estima pelo GMR (aproximacao ZARC: ciclos simulados de
100/115/130 dias para os grupos I/II/III no PR). O ciclo observado por
satelite, quando existe, calibra esta conversao por regiao.
"""

import csv

import numpy as np

# GMR -> ciclo (dias), interpolacao linear; aproximacao a calibrar
GMR_CICLO = ((5.0, 95.0), (6.0, 103.0), (6.4, 107.0), (6.9, 115.0),
             (7.4, 123.0), (8.0, 130.0), (8.5, 135.0))
# sensibilidade fotoperiodica: dias de ciclo perdidos por dia de atraso
# na semeadura apos a data de referencia (aproximacao de literatura)
ENCURTA_POR_DIA = 0.25
REF_SEMEADURA_MD = "10-15"


def ciclo_por_gmr(gmr):
    xs, ys = zip(*GMR_CICLO)
    return float(np.interp(float(gmr), xs, ys))


def ajustar_por_semeadura(ciclo, semeadura_iso, ref_md=REF_SEMEADURA_MD):
    import datetime
    d = datetime.date.fromisoformat(semeadura_iso)
    ref = datetime.date.fromisoformat("%d-%s" % (d.year, ref_md))
    atraso = (d - ref).days
    return max(85.0, ciclo - ENCURTA_POR_DIA * max(atraso, 0))


def ler_csv(caminho):
    out = {}
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            reg = r["regiao_id"].strip()
            gmr = float(r["gmr"]) if r.get("gmr") else None
            ciclo = float(r["ciclo_dias"]) if r.get("ciclo_dias") else (
                ciclo_por_gmr(gmr) if gmr is not None else None)
            out.setdefault(reg, []).append({
                "cultivar": r.get("cultivar", ""), "gmr": gmr,
                "participacao": float(r.get("participacao_pct") or 0) / 100.0,
                "ciclo_dias": ciclo,
                "populacao": float(r["populacao_mil_plantas_ha"])
                if r.get("populacao_mil_plantas_ha") else None,
                "habito": r.get("habito", ""),
                "tecnologia": r.get("tecnologia", "")})
    return out


def ciclo_ponderado(lista):
    w = np.array([c["participacao"] for c in lista], float)
    c = np.array([c["ciclo_dias"] for c in lista], float)
    if w.sum() <= 0:
        w = np.ones_like(c)
    return float(np.sum(w * c) / w.sum())


def coortes(semeadura_pcts, lista_cultivares=None, ciclo_satelite=None):
    """Combina distribuicao de semeadura (p25/p50/p75 do satelite ou do
    Deral) com o mix de cultivares -> lista de (data, ciclo, peso)."""
    datas = [semeadura_pcts[k] for k in ("p25", "p50", "p75")]
    pesos_d = [0.25, 0.5, 0.25]
    out = []
    if lista_cultivares:
        for c in lista_cultivares:
            for d, wd in zip(datas, pesos_d):
                out.append((d, ajustar_por_semeadura(c["ciclo_dias"], d),
                            wd * (c["participacao"] or 1.0)))
    else:
        base = ciclo_satelite or 120.0
        for d, wd in zip(datas, pesos_d):
            out.append((d, base, wd))
    s = sum(w for _, _, w in out)
    return [(d, c, w / s) for d, c, w in out]
