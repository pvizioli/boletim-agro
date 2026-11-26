# -*- coding: utf-8 -*-
"""Gerador sintetico com a MESMA estrutura da tese (26 municipios x safras,
4 fases, clima diario -> balanco hidrico -> produtividade). Serve para:
 (i) testar a implementacao (recuperar parametros conhecidos);
 (ii) demonstrar o efeito de sobreajuste do protocolo in-sample da tese;
 (iii) comparar variantes fora da amostra com verdade conhecida.
NAO e evidencia de acuracia no mundo real: a verdade e gerada por Jensen.
"""

import datetime
import math

import numpy as np

from . import agrupamento, balanco_hidrico, config, ingestao

LAMBDAS_VERDADE = np.array([0.10, 0.25, 0.55, 0.20])


def _clima_ano(rng, lat, regime, ano, fator_ano, inicio="09-01", dias=235):
    d0 = datetime.date.fromisoformat("%d-%s" % (ano, inicio))
    chuva_media = [4.2, 5.6, 3.4][regime] * fator_ano   # mm/dia medio
    dtemp = [0.0, -1.5, 2.0][regime]
    serie = {}
    molhado = False
    for i in range(dias):
        d = d0 + datetime.timedelta(days=i)
        doy = d.timetuple().tm_yday
        p_w = 0.60 if molhado else 0.28
        molhado = rng.random() < p_w
        prec = 0.0
        if molhado:
            prec = rng.gamma(0.7, chuva_media / (0.7 * 0.40)) 
        sazon = math.cos(2 * math.pi * (doy - 15) / 365.0)
        tmed = 24.0 + 3.5 * sazon + dtemp + rng.normal(0, 1.2)
        amp = max(7.0, 11.0 - 0.15 * prec + rng.normal(0, 1.0))
        tmax, tmin = tmed + amp / 2, tmed - amp / 2
        eto = ingestao.eto_hargreaves(tmin, tmax, lat, doy)
        serie[d.isoformat()] = {"tmax": round(tmax, 2), "tmin": round(tmin, 2),
                                "prec": round(prec, 1), "eto": round(eto, 3),
                                "rad": None, "u2": None, "rh": None}
    return serie


def gerar(n_mun=26, anos=(2003, 2004, 2005, 2006, 2007), cenario="clusters_reais",
          ruido=0.05, seed=42, cad_mm=42.0, plantio_md="11-01"):
    """cenario: 'clusters_reais' (regime tem efeito residual gamma) ou
    'sem_efeito' (regimes existem no clima mas nao afetam o rendimento
    alem da agua)."""
    rng = np.random.default_rng(seed)
    regimes = rng.integers(0, 3, size=n_mun)
    lats = rng.uniform(-26.5, -23.0, size=n_mun)
    ym_true = rng.normal(62.0, 4.0, size=n_mun)
    gam = np.zeros((3, 4))
    if cenario == "clusters_reais":
        gam[:, 2] = [0.0, -0.05, 0.04]
        gam[:, 1] = [0.0, 0.02, -0.03]
    fatores = np.exp(rng.normal(0, 0.28, size=len(anos)))
    obs = []
    for j in range(n_mun):
        mun = "M%02d" % (j + 1)
        for k, ano in enumerate(anos):
            serie = _clima_ano(rng, lats[j], int(regimes[j]), ano, fatores[k])
            plantio = "%d-%s" % (ano, plantio_md)
            sim = balanco_hidrico.simular(serie, plantio, cad_mm=cad_mm)
            r = balanco_hidrico.razoes(sim)
            L = np.log(np.clip(np.array(r, dtype=float), config.RAZAO_MIN, 1.0))
            logrel = float(L @ LAMBDAS_VERDADE + sum(
                gam[regimes[j], i] for i in range(4)) + rng.normal(0, ruido))
            rel = min(1.2, math.exp(logrel))
            feat = agrupamento.features_fases(serie, plantio)
            obs.append({"mun": mun, "ano": ano, "y": ym_true[j] * rel,
                        "razoes": r, "feat": feat,
                        "regime_verdadeiro": int(regimes[j])})
    return {"obs": obs, "regimes": regimes.tolist(), "gamma": gam.tolist(),
            "lambdas": LAMBDAS_VERDADE.tolist()}


def gerar_serie_continua(ini, fim, lat=-23.5, regime=0, seed=0):
    """Serie diaria sintetica para um intervalo arbitrario [ini, fim]
    (AAAA-MM-DD). Usada em testes e mocks de API."""
    rng = np.random.default_rng(seed)
    d = datetime.date.fromisoformat(ini)
    fim_d = datetime.date.fromisoformat(fim)
    fator = {}
    serie = {}
    molhado = False
    while d <= fim_d:
        # fator de chuva por ano agricola (set-ago), reprodutivel
        ano_agr = d.year if d.month >= 9 else d.year - 1
        if ano_agr not in fator:
            fator[ano_agr] = float(np.exp(np.random.default_rng(
                ano_agr * 7 + seed).normal(0, 0.28)))
        doy = d.timetuple().tm_yday
        chuva_media = [4.2, 5.6, 3.4][regime] * fator[ano_agr]
        molhado = rng.random() < (0.60 if molhado else 0.28)
        prec = rng.gamma(0.7, chuva_media / (0.7 * 0.40)) if molhado else 0.0
        sazon = math.cos(2 * math.pi * (doy - 15) / 365.0)
        tmed = 24.0 + 3.5 * sazon + [0.0, -1.5, 2.0][regime] + rng.normal(0, 1.2)
        amp = max(7.0, 11.0 - 0.15 * prec + rng.normal(0, 1.0))
        tmax, tmin = tmed + amp / 2, tmed - amp / 2
        serie[d.isoformat()] = {
            "tmax": round(tmax, 2), "tmin": round(tmin, 2),
            "prec": round(prec, 1),
            "eto": round(ingestao.eto_hargreaves(tmin, tmax, lat, doy), 3),
            "rad": None, "u2": None, "rh": None}
        d += datetime.timedelta(days=1)
    return serie


def para_open_meteo(serie):
    """Serie normalizada -> JSON no formato da API Open-Meteo (daily)."""
    dias = sorted(serie)
    g = lambda c: [serie[x].get(c) for x in dias]  # noqa: E731
    return {"latitude": -23.5, "longitude": -51.9,
            "daily_units": {"time": "iso8601"},
            "daily": {"time": dias, "temperature_2m_max": g("tmax"),
                      "temperature_2m_min": g("tmin"),
                      "precipitation_sum": g("prec"),
                      "et0_fao_evapotranspiration": g("eto"),
                      "shortwave_radiation_sum": g("rad")}}
