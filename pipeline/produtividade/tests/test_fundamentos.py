# -*- coding: utf-8 -*-
"""Ingestao, ETo, balanco hidrico, Jensen, agrupamento."""
import numpy as np
import pytest

from produtividade import agrupamento, balanco_hidrico as bh, config, ingestao
from produtividade.jensen import Jensen
import datetime


# ------------------------------------------------------------------ ETo
def test_eto_penman_monteith_exemplo18_fao56():
    # FAO-56 Exemplo 18 (Bruxelas, 6/jul): ETo = 3,9 mm/dia
    eto = ingestao.eto_penman_monteith(12.3, 21.5, 22.07, 2.078, 50.8, 187, 100,
                                       rh_max=84, rh_min=63)
    assert abs(eto - 3.9) < 0.1


def test_radiacao_extraterrestre_fao56():
    assert abs(ingestao.radiacao_extraterrestre(50.8, 187) - 41.1) < 0.2


def test_hargreaves_ordem_de_grandeza_tropical():
    eto = ingestao.eto_hargreaves(18.0, 31.0, -23.4, 330)
    assert 4.0 < eto < 7.5


# ------------------------------------------------------------- adaptadores
def test_open_meteo():
    obj = {"daily": {"time": ["2026-11-01", "2026-11-02"],
                     "temperature_2m_max": [30.1, None],
                     "temperature_2m_min": [19.0, 18.0],
                     "precipitation_sum": [0.0, 12.4],
                     "et0_fao_evapotranspiration": [5.1, 4.2]}}
    s = ingestao.de_open_meteo(obj)
    assert s["2026-11-01"]["tmax"] == 30.1 and s["2026-11-02"]["tmax"] is None
    assert s["2026-11-02"]["prec"] == 12.4 and s["2026-11-02"]["eto"] == 4.2


def test_nasa_power_fill_e_unidade():
    obj = {"properties": {"parameter": {
        "T2M_MAX": {"20261101": 31.0, "20261102": -999.0},
        "T2M_MIN": {"20261101": 19.0, "20261102": 18.0},
        "PRECTOTCORR": {"20261101": 0.0, "20261102": 8.5},
        "ALLSKY_SFC_SW_DWN": {"20261101": 6.0, "20261102": 5.0}}},
        "parameters": {"ALLSKY_SFC_SW_DWN": {"units": "kW-hr/m^2/day"}}}
    s = ingestao.de_nasa_power(obj)
    assert s["2026-11-02"]["tmax"] is None          # -999 vira ausente
    assert s["2026-11-01"]["rad"] == pytest.approx(21.6)  # kWh -> MJ
    assert s["2026-11-02"]["prec"] == 8.5


def test_inmet_agrega_horario_e_descarta_dia_incompleto():
    horas = []
    for h in range(24):
        horas.append({"DT_MEDICAO": "2026-11-01", "HR_MEDICAO": "%02d00" % h,
                      "TEM_MAX": str(20 + h / 3.0), "TEM_MIN": str(18 + h / 3.0),
                      "CHUVA": "0.5"})
    for h in range(5):  # dia 2 com 5 horas apenas
        horas.append({"DT_MEDICAO": "2026-11-02", "HR_MEDICAO": "%02d00" % h,
                      "TEM_MAX": "25", "TEM_MIN": "20", "CHUVA": "1.0"})
    s = ingestao.de_inmet(horas)
    assert s["2026-11-01"]["prec"] == pytest.approx(12.0)
    assert s["2026-11-01"]["tmin"] == pytest.approx(18.0)
    assert s["2026-11-02"]["prec"] is None   # nao subestima chuva


def test_chuva_generica_chirps():
    s = ingestao.de_chuva_generica([{"date": "11/05/2026", "value": {"avg": 3.2}},
                                    {"date": "2026-11-06", "value": 0}])
    assert s["2026-11-05"]["prec"] == 3.2 and s["2026-11-06"]["prec"] == 0.0


def test_mesclar_nao_sobrescreve():
    a = {"2026-11-01": {"tmax": 30, "tmin": None, "prec": 5, "eto": None,
                        "rad": None, "u2": None, "rh": None}}
    b = {"2026-11-01": {"tmax": 99, "tmin": 20, "prec": 99, "eto": 4,
                        "rad": None, "u2": None, "rh": None}}
    m = ingestao.mesclar(a, b)["2026-11-01"]
    assert m["tmax"] == 30 and m["prec"] == 5 and m["tmin"] == 20 and m["eto"] == 4


def test_completar_eto_prefere_fonte_depois_pm_depois_hargreaves():
    s = {"2026-11-01": {"tmax": 30, "tmin": 19, "prec": 0, "eto": 4.4,
                        "rad": None, "u2": None, "rh": None},
         "2026-11-02": {"tmax": 30, "tmin": 19, "prec": 0, "eto": None,
                        "rad": 20.0, "u2": 2.0, "rh": 60},
         "2026-11-03": {"tmax": 30, "tmin": 19, "prec": 0, "eto": None,
                        "rad": None, "u2": None, "rh": None}}
    out, r = ingestao.completar_eto(s, -23.4)
    assert out["2026-11-01"]["eto"] == 4.4
    assert (r["fonte"], r["penman_monteith"], r["hargreaves"]) == (1, 1, 1)


# ---------------------------------------------------------- balanco hidrico
def _serie(f, ini="2026-09-25", n=220, eto=5.0):
    d0 = datetime.date.fromisoformat(ini)
    return {(d0 + datetime.timedelta(days=i)).isoformat():
            {"prec": f(i), "eto": eto} for i in range(n)}


def test_kc_interpolacao_e_limites():
    assert bh.kc_por_dap(1) == 0.30
    assert bh.kc_por_dap(73) == pytest.approx(1.25)
    assert bh.kc_por_dap(400) == 0.60
    assert 0.6 < bh.kc_por_dap(60) < 1.25


def test_fases_somam_150_dias():
    lim = bh.limites_fases()
    assert lim[0] == (1, 20) and lim[-1][1] == 150 == config.CICLO_DIAS


def test_sem_estresse_e_estresse_severo():
    umido = bh.simular(_serie(lambda i: 15.0 if i % 2 == 0 else 0.0), "2026-10-25")
    assert all(f["razao"] == pytest.approx(1.0) for f in umido["por_fase"])
    assert 450 < umido["etm_total_mm"] < 800     # necessidade hidrica da soja
    seca = bh.simular(_serie(lambda i: 0.0), "2026-10-25")
    assert all(f["razao"] < 0.1 for f in seca["por_fase"][1:])


def test_balanco_conserva_massa():
    s = _serie(lambda i: 8.0 if i % 3 == 0 else 0.0)
    sim = bh.simular(s, "2026-10-25", arm_inicial_frac=0.5, spinup_dias=0)
    cad = sim["cad_mm"]
    etr = sim["etr_total_mm"]
    assert etr <= sim["prec_total_mm"] + cad * 0.5 + 1e-6


def test_mais_chuva_nunca_reduz_razao():
    a = bh.simular(_serie(lambda i: 2.0), "2026-10-25")
    b = bh.simular(_serie(lambda i: 4.0), "2026-10-25")
    for fa, fb in zip(a["por_fase"], b["por_fase"]):
        assert fb["razao"] >= fa["razao"] - 1e-9


def test_dias_faltantes_nao_entram_nas_somas():
    s = _serie(lambda i: 5.0, n=60)  # serie curta: ciclo incompleto
    sim = bh.simular(s, "2026-10-25")
    assert sim["dias_faltantes"] > 0
    assert sim["por_fase"][-1]["razao"] is None


# ---------------------------------------------------------------- Jensen
def test_jensen_recupera_lambdas():
    rng = np.random.default_rng(1)
    r = rng.uniform(0.4, 1, (300, 4))
    lam = np.array([0.1, 0.3, 0.8, 0.2])
    y = np.exp(np.log(r) @ lam + rng.normal(0, 0.01, 300))
    m = Jensen().ajustar(r, y)
    assert np.allclose(m.lambdas, lam, atol=0.04)


def test_lambda_nao_negativo_e_respeitado():
    rng = np.random.default_rng(2)
    r = rng.uniform(0.4, 1, (200, 4))
    y = np.exp(-0.5 * np.log(r[:, 1]) + np.log(r[:, 2]) + rng.normal(0, 0.01, 200))
    m = Jensen(lambda_nao_negativo=True).ajustar(r, y)
    assert (m.lambdas >= -1e-12).all()


def test_jensen_serializacao_ida_e_volta():
    rng = np.random.default_rng(3)
    r = rng.uniform(0.4, 1, (80, 4))
    g = rng.integers(0, 3, (80, 4))
    y = np.exp(np.log(r) @ np.array([.1, .2, .5, .1]) + 0.03 * (g[:, 2] == 1))
    m = Jensen(usar_grupos=True).ajustar(r, y, g)
    m2 = Jensen.from_dict(m.to_dict())
    assert np.allclose(m.prever_rel(r, g), m2.prever_rel(r, g))


def test_prior_generico_nao_e_calibrado():
    m = Jensen.prior_generico()
    assert not m.calibrado
    assert m.prever_rel([[1, 1, 1, 1]])[0] == pytest.approx(1.0)
    assert m.prever_rel([[0.5, 0.5, 0.5, 0.5]])[0] < 1.0


# ------------------------------------------------------------ agrupamento
def test_kmeans_separa_grupos_distintos():
    rng = np.random.default_rng(0)
    Z = np.vstack([rng.normal(c, 0.2, (10, 3)) for c in (0, 5, 10)])
    lab, C, _ = agrupamento.kmeans(Z, 3)
    assert sorted(np.bincount(lab)) == [10, 10, 10]


def test_escolher_k_respeita_tamanho_minimo():
    rng = np.random.default_rng(1)
    Z = rng.normal(0, 1, (9, 4))
    k, lab, C, s = agrupamento.escolher_k(Z, kmax=6, min_tamanho=3)
    assert k == 1 or np.bincount(lab).min() >= 3


def test_atribuir_aponta_grupo_mais_proximo():
    feats = {}
    rng = np.random.default_rng(5)
    for j in range(12):
        base = 0.0 if j < 6 else 8.0
        feats["m%d" % j] = [rng.normal(base, 0.3, 20) for _ in range(4)]
    agr = agrupamento.agrupar(feats, kmax=3, min_tamanho=3)
    f0 = agr["fases"][0]
    assert f0["k"] == 2
    assert agrupamento.atribuir(f0, rng.normal(0, 0.3, 20)) == f0["labels"]["m0"]
    assert agrupamento.atribuir(f0, rng.normal(8, 0.3, 20)) == f0["labels"]["m11"]
