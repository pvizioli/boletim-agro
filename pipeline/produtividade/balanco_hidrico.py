# -*- coding: utf-8 -*-
"""Balanco hidrico diario da soja e razoes ETR/ETm por fase fenologica.

ETm = Kc(DAP) * ETo.  Reservatorio unico com capacidade CAD (mm).
Estresse (FAO-56): Ks = min(1, ARM / ((1 - p) * CAD)); ETR = Ks * ETm,
limitada ao que ha de agua (ARM + chuva). Excedente drena/escoa.
"""

import datetime

from . import config


def kc_por_dap(dap, pontos=config.KC_PONTOS):
    """Kc por dias apos plantio/emergencia, interpolacao linear."""
    if dap <= pontos[0][0]:
        return pontos[0][1]
    if dap >= pontos[-1][0]:
        return pontos[-1][1]
    for (d0, k0), (d1, k1) in zip(pontos, pontos[1:]):
        if d0 <= dap <= d1:
            return k0 + (k1 - k0) * (dap - d0) / float(d1 - d0)
    return pontos[-1][1]


def limites_fases(fases=config.FASES):
    """[(inicio_dap, fim_dap)] com DAP 1-indexado e fim inclusivo."""
    out, ini = [], 1
    for _, dur in fases:
        out.append((ini, ini + dur - 1))
        ini += dur
    return out


def _dias(plantio, n):
    d0 = datetime.date.fromisoformat(plantio)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def fases_escaladas(ciclo):
    """Duracoes das 4 fases proporcionais a um ciclo de `ciclo` dias
    (proporcoes da tese: 20/50/40/40 de 150)."""
    base = config.CICLO_DIAS
    durs = [max(1, int(round(d * ciclo / float(base)))) for _, d in config.FASES]
    durs[-1] += int(ciclo) - sum(durs)
    return tuple((n, d) for (n, _), d in zip(config.FASES, durs))


def simular(serie, plantio, cad_mm=None, p=config.P_DEPLECAO,
            arm_inicial_frac=0.5, spinup_dias=30, ciclo=config.CICLO_DIAS):
    """Simula o ciclo a partir da data de plantio (AAAA-MM-DD).

    serie: dict data -> {"prec","eto",...} (ver ingestao.py).
    Dias do ciclo sem chuva ou ETo na serie sao tratados como FALTANTES:
    nao entram na soma de nenhuma fase e sao contados em 'dias_faltantes'
    (o chamador decide completar com previsao/cenario).

    Retorna dict com por_fase (etr, etm, razao, dias, faltantes), diario
    (lista) e metadados.
    """
    if cad_mm is None:
        cad_mm = config.AD_CLASSES[config.AD_PADRAO]
    cad = float(cad_mm)
    arm = cad * float(arm_inicial_frac)

    # spin-up: pousio (Kc 0.30) nos dias anteriores ao plantio
    d0 = datetime.date.fromisoformat(plantio)
    for i in range(spinup_dias, 0, -1):
        dia = (d0 - datetime.timedelta(days=i)).isoformat()
        reg = serie.get(dia) or {}
        if reg.get("prec") is None or reg.get("eto") is None:
            continue
        arm = _passo(arm, cad, p, reg["prec"], 0.30 * reg["eto"])[0]

    ciclo = int(ciclo)
    fases_def = fases_escaladas(ciclo)
    fases = limites_fases(fases_def)
    escala = config.CICLO_DIAS / float(ciclo)
    acum = [{"etr": 0.0, "etm": 0.0, "dias": 0, "faltantes": 0,
             "prec": 0.0} for _ in fases]
    diario = []
    for k, dia in enumerate(_dias(plantio, ciclo), start=1):
        idx = next(i for i, (a, b) in enumerate(fases) if a <= k <= b)
        reg = serie.get(dia) or {}
        pr, eto = reg.get("prec"), reg.get("eto")
        if pr is None or eto is None:
            acum[idx]["faltantes"] += 1
            diario.append({"data": dia, "dap": k, "faltante": True})
            continue
        etm = kc_por_dap(k * escala) * eto
        arm, etr, ks = _passo(arm, cad, p, pr, etm)
        acum[idx]["etr"] += etr
        acum[idx]["etm"] += etm
        acum[idx]["prec"] += pr
        acum[idx]["dias"] += 1
        diario.append({"data": dia, "dap": k, "prec": pr, "eto": eto,
                       "etm": round(etm, 3), "etr": round(etr, 3),
                       "ks": round(ks, 3), "arm": round(arm, 2)})

    por_fase = []
    for (nome, _), a in zip(fases_def, acum):
        razao = (a["etr"] / a["etm"]) if a["etm"] > 0 else None
        por_fase.append({
            "fase": nome, "etr_mm": round(a["etr"], 1),
            "etm_mm": round(a["etm"], 1),
            "razao": None if razao is None else round(razao, 4),
            "prec_mm": round(a["prec"], 1),
            "dias_ok": a["dias"], "dias_faltantes": a["faltantes"]})
    return {"plantio": plantio, "cad_mm": cad, "ciclo_dias": ciclo, "por_fase": por_fase,
            "diario": diario,
            "dias_faltantes": sum(a["faltantes"] for a in acum),
            "etr_total_mm": round(sum(a["etr"] for a in acum), 1),
            "etm_total_mm": round(sum(a["etm"] for a in acum), 1),
            "prec_total_mm": round(sum(a["prec"] for a in acum), 1)}


def _passo(arm, cad, p, prec, etm):
    """Um dia: retorna (arm_novo, etr, ks)."""
    limiar = (1.0 - p) * cad
    ks = 1.0 if arm >= limiar else max(arm, 0.0) / limiar
    etr = ks * etm
    disponivel = arm + prec
    etr = min(etr, disponivel)
    novo = min(cad, disponivel - etr)
    return max(novo, 0.0), etr, ks


def razoes(sim):
    """Lista [r1..r4] (None se fase sem dados)."""
    return [f["razao"] for f in sim["por_fase"]]
