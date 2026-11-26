# -*- coding: utf-8 -*-
"""Fenologia por satelite, cultivares, ciclo variavel e modelo hibrido."""
import datetime

import numpy as np
import pytest

from produtividade import balanco_hidrico as bh, cultivares, fenologia as fen
from produtividade import modelo_hibrido as mh


def _o(d):
    return datetime.date.fromisoformat(d).toordinal()


def _curva_soja(sem, ciclo=120, base=0.22, pico=0.75, safrinha=True):
    t = np.arange(_o("2022-07-01"), _o("2023-07-31"))
    s = _o(sem) + 10
    y = base + (pico - base) / (1 + np.exp(-(t - (s + 25)) / 6)) / (1 + np.exp((t - (s + ciclo - 25)) / 6))
    if safrinha:
        y += 0.35 / (1 + np.exp(-(t - (s + ciclo + 30)) / 6)) / (1 + np.exp((t - (s + ciclo + 110)) / 6))
    return t, y


def _amostrar(t, y, seed, nuvens=6):
    rng = np.random.default_rng(seed)
    T, V = t[::8], y[::8] + rng.normal(0, 0.02, len(t[::8]))
    V[rng.choice(len(T), nuvens, replace=False)] -= 0.3
    return T, V[:, None], np.ones((len(T), 1), bool)


def test_semeadura_ordena_e_erra_pouco_com_nuvens():
    ests = []
    for k, sem in enumerate(("2022-09-25", "2022-10-20", "2022-11-20")):
        T, V, OK = _amostrar(*_curva_soja(sem), seed=k)
        m = fen.pixels_temporada(T, V, OK, 2022)[0]
        assert m["soja"], m["motivo"]
        ests.append(_o(m["semeadura"]) - _o(sem))
    assert all(-5 <= e <= 25 for e in ests)          # vies estrutural do lag
    assert max(ests) - min(ests) <= 15               # consistente entre datas


def test_pastagem_e_floresta_nao_sao_soja():
    t = np.arange(_o("2022-07-01"), _o("2023-07-31"))
    for y in (0.40 + 0.12 * np.sin((t - t[0]) / 365 * 2 * np.pi),
              np.full(len(t), 0.55)):
        m = fen.pixels_temporada(t[::8], y[::8][:, None], np.ones((len(t[::8]), 1), bool), 2022)[0]
        assert m is None or not m["soja"]


def test_milho_verao_ciclo_longo_rejeitado():
    T, V, OK = _amostrar(*_curva_soja("2022-09-10", ciclo=175, safrinha=False), seed=3, nuvens=0)
    m = fen.pixels_temporada(T, V, OK, 2022)[0]
    assert not m["soja"] and "ciclo" in m["motivo"]


def test_agregar_e_fracao_semeada():
    met = []
    for k, sem in enumerate(["2022-10-%02d" % d for d in range(1, 29, 3)]):
        T, V, OK = _amostrar(*_curva_soja(sem), seed=10 + k)
        met.append(fen.pixels_temporada(T, V, OK, 2022)[0])
    ag = fen.agregar(met, 5.37)
    assert ag["n_soja"] >= 8 and ag["semeadura_p10"] < ag["semeadura_p90"]
    assert fen.fracao_semeada_ate(met, "2022-09-01") == 0
    assert fen.fracao_semeada_ate(met, "2023-01-01") == 100


def test_emergencia_parcial_detecta_lavoura_ja_emergida():
    t, y = _curva_soja("2022-10-01")
    corte = _o("2022-11-25")
    m = t <= corte
    T, V = t[m][::8], y[m][::8]
    r = fen.emergencia_parcial(T, V[:, None], np.ones((len(T), 1), bool), 2022, "2022-11-25")[0]
    assert r["emergido"] and abs(_o(r["semeadura"]) - _o("2022-10-01")) < 25
    r2 = fen.emergencia_parcial(T, np.full((len(T), 1), 0.22), np.ones((len(T), 1), bool), 2022, "2022-11-25")[0]
    assert not r2["emergido"]


def test_fases_escaladas_somam_o_ciclo():
    for c in (100, 115, 130, 150):
        assert sum(d for _, d in bh.fases_escaladas(c)) == c


def test_ciclo_curto_concentra_fases():
    s = {}
    d0 = datetime.date(2022, 9, 1)
    for i in range(260):
        s[(d0 + datetime.timedelta(days=i)).isoformat()] = {"prec": 6.0, "eto": 5.0}
    a = bh.simular(s, "2022-10-15", ciclo=100)
    b = bh.simular(s, "2022-10-15", ciclo=150)
    assert a["etm_total_mm"] < b["etm_total_mm"]
    assert a["por_fase"][2]["fase"] == "reprodutivo"


def test_cultivares_gmr_e_coortes():
    assert cultivares.ciclo_por_gmr(6.4) == pytest.approx(107)
    assert cultivares.ciclo_por_gmr(7.4) > cultivares.ciclo_por_gmr(6.0)
    assert cultivares.ajustar_por_semeadura(120, "2022-11-24") < 120
    co = cultivares.coortes({"p25": "2022-10-05", "p50": "2022-10-15", "p75": "2022-10-30"},
                            [{"ciclo_dias": 110, "participacao": 0.6},
                             {"ciclo_dias": 125, "participacao": 0.4}])
    assert len(co) == 6 and abs(sum(w for _, _, w in co) - 1) < 1e-9


def test_template_de_cultivares_le(tmp_path):
    import os
    p = os.path.join(os.path.dirname(__file__), "..", "docs", "cultivares_template.csv")
    d = cultivares.ler_csv(p)
    assert "cascavel" in d and all(c["ciclo_dias"] for c in d["cascavel"])


def test_hibrido_recupera_efeitos_e_preve_municipio_novo():
    rng = np.random.default_rng(0)
    obs = []
    a = {"m%d" % i: rng.normal(4.0, 0.1) for i in range(10)}
    for m, am in a.items():
        for ano in range(2013, 2025):
            r = list(rng.uniform(0.5, 1, 4))
            pico = rng.normal(0.7, 0.05)
            ly = am + 0.015 * (ano - 2018) + 0.8 * np.log(r[1]) + 0.3 * np.log(r[2]) + 0.5 * (pico - 0.7)
            obs.append({"mun": m, "ano": ano, "y": float(np.exp(ly + rng.normal(0, 0.01))),
                        "razoes": r, "pico": pico})
    h = mh.Hibrido(extras=("pico",)).ajustar(obs)
    c = h.coeficientes()
    assert c["lambdas"][1] == pytest.approx(0.8, abs=0.05)
    assert c["tendencia_pct_ano"] == pytest.approx(1.5, abs=0.3)
    p = mh.cv(obs, lambda: mh.Hibrido(extras=("pico",)), "lomo")
    assert np.sqrt(np.mean([(x["y"] - x["prev"]) ** 2 for x in p])) < 8
