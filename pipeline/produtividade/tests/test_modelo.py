# -*- coding: utf-8 -*-
"""Previsao, reproducao aritmetica da tese, pipeline offline, backtest."""
import csv
import datetime
import json
import os
import urllib.parse

import numpy as np
import pytest

from produtividade import (agrupamento, avaliacao, backtest, config, ingestao,
                           pipeline, previsao, simulacao)
from produtividade.jensen import Jensen


def _obs_sinteticas(**kw):
    return simulacao.gerar(**kw)["obs"]


# ---------------------------------------------------- tese: aritmetica
def test_tabela_4_6_decorre_da_tabela_4_5():
    jm = {2003: 8691, 2004: 12843, 2005: 48, 2006: 4360, 2007: 5025}
    j = {2003: 25870, 2004: 32317, 2005: 20722, 2006: 8637, 2007: 14704}
    esperado = {2003: 66.41, 2004: 60.26, 2005: 99.77, 2006: 49.52, 2007: 65.83}
    for ano in jm:
        assert round(100 * (j[ano] - jm[ano]) / j[ano], 2) == esperado[ano]


def test_protocolo_tese_satura_quando_parametros_excedem_observacoes():
    obs = [o for o in _obs_sinteticas(seed=3) if o["ano"] == 2004]  # 26 obs
    rng = np.random.default_rng(0)
    G = [[int(rng.integers(0, k)) for k in (12, 10, 5, 8)] for _ in obs]
    r = avaliacao.protocolo_tese_in_sample(obs, G)
    assert r["n_parametros_modificado"] > r["n_obs"]
    assert r["melhora_pct"] > 90          # rotulos ALEATORIOS "melhoram" ~100%


def test_rotulos_aleatorios_melhoram_in_sample_na_faixa_da_tese():
    obs = [o for o in _obs_sinteticas(seed=5) if o["ano"] == 2006]
    ks = (6, 3, 3, 4)
    ganhos = []
    for s in range(30):
        rng = np.random.default_rng(s)
        G = [[int(rng.integers(0, k)) for k in ks] for _ in obs]
        ganhos.append(avaliacao.protocolo_tese_in_sample(obs, G)["melhora_pct"])
    assert np.median(ganhos) > 30         # ganho grande sem nenhum sinal real


# ----------------------------------------------------------- validacao
def test_cv_jensen_bate_baseline_em_dados_com_sinal_hidrico():
    obs = _obs_sinteticas(seed=1, anos=tuple(range(2003, 2011)))
    m_base, _ = avaliacao.cv(obs, "media_mun", "loyo")
    m_j, _ = avaliacao.cv(obs, "jensen", "loyo")
    assert m_j["rmse"] < 0.75 * m_base["rmse"]


def test_cv_nao_vaza_ano_de_teste():
    obs = _obs_sinteticas(seed=2)
    ano = 2005
    tr = [o for o in obs if o["ano"] != ano]
    te = [o for o in obs if o["ano"] == ano]
    p1 = avaliacao.prever_fold(tr, te, "jensen")
    for o in te:
        o["y"] = 999.0                      # alterar o alvo do teste
    p2 = avaliacao.prever_fold(tr, te, "jensen")
    assert np.allclose(p1, p2)


# ------------------------------------------------------------- previsao
def _serie_ciclo_completo(chuva=5.0):
    s = {}
    d0 = datetime.date(2026, 9, 25)
    for i in range(230):
        s[(d0 + datetime.timedelta(days=i)).isoformat()] = {
            "prec": chuva if i % 2 == 0 else 0.0, "eto": 5.0, "tmax": 31,
            "tmin": 20, "rad": None, "u2": None, "rh": None}
    return s


def _modelo():
    m = Jensen()
    m.lambdas = np.array([0.1, 0.25, 0.55, 0.2])
    m.b0 = 0.0
    m.calibrado = True
    m.n_obs = 120
    return m


def test_ciclo_completo_e_deterministico_e_rotulado():
    r = previsao.prever_safra(_serie_ciclo_completo(20.0), "2026-10-25",
                              "2027-03-30", 65.0, modelo=_modelo(), lat=-23.4,
                              rmse_modelo_sc_ha=3.0)
    assert r["rotulo"] == "estimativa"
    assert r["metodo_incerteza"] == "deterministico"
    assert r["fracao_ciclo_com_dados"] == 1.0
    assert r["produtividade_sc_ha"]["p50"] == pytest.approx(65.0, abs=0.5)
    assert r["confianca"] in ("alta", "media")


def test_seca_reduz_produtividade():
    umido = previsao.prever_safra(_serie_ciclo_completo(20.0), "2026-10-25",
                                  "2027-03-30", 65.0, modelo=_modelo(), lat=-23.4)
    seco = previsao.prever_safra(_serie_ciclo_completo(2.0), "2026-10-25",
                                 "2027-03-30", 65.0, modelo=_modelo(), lat=-23.4)
    assert seco["produtividade_sc_ha"]["p50"] < 0.8 * umido["produtividade_sc_ha"]["p50"]


def test_sem_calibracao_vira_confianca_baixa_com_aviso():
    r = previsao.prever_safra(_serie_ciclo_completo(10.0), "2026-10-25",
                              "2027-03-30", 65.0, modelo=None, lat=-23.4)
    assert r["confianca"] == "baixa"
    assert any("prior generico" in a for a in r["avisos"])


def test_ciclo_parcial_usa_cenarios_analogos_e_quantis_ordenados():
    hist = simulacao.gerar_serie_continua("2014-09-01", "2026-12-09", seed=4)
    obs = {d: r for d, r in hist.items() if d >= "2026-09-01"}
    analogos = {a: {d: r for d, r in hist.items()
                    if "%d-09-01" % a <= d <= "%d-04-15" % (a + 1)}
                for a in range(2014, 2026)}
    r = previsao.prever_safra(obs, "2026-11-01", "2026-12-09", 65.0,
                              modelo=_modelo(), lat=-23.4, analogos=analogos,
                              rmse_modelo_sc_ha=4.0)
    p = r["produtividade_sc_ha"]
    assert r["metodo_incerteza"] == "cenarios_analogos" and r["n_cenarios"] >= 8
    assert p["p10"] <= p["p50"] <= p["p90"] and p["p10"] < p["p90"]
    lo, hi = r["intervalo_80_total_sc_ha"]
    assert lo < p["p50"] < hi
    assert r["fracao_ciclo_com_dados"] < 0.5
    assert r["confianca"] in ("baixa", "media")


def test_parcial_sem_cenarios_avisa_otimismo():
    s = _serie_ciclo_completo(20.0)
    s = {d: v for d, v in s.items() if d <= "2026-12-20"}
    r = previsao.prever_safra(s, "2026-10-25", "2026-12-20", 65.0,
                              modelo=_modelo(), lat=-23.4)
    assert r["metodo_incerteza"] == "parcial_sem_cenarios"
    assert any("SEM estresse" in a for a in r["avisos"])


def test_serie_analoga_nao_inclui_ano_corrente():
    hist = simulacao.gerar_serie_continua("2024-09-01", "2026-12-09", seed=1)
    obs = {d: r for d, r in hist.items() if d >= "2026-09-01"}
    analogos = {2026: obs, 2024: {d: r for d, r in hist.items()
                                  if "2024-09-01" <= d <= "2025-04-15"}}
    r = previsao.prever_safra(obs, "2026-11-01", "2026-12-09", 65.0,
                              modelo=_modelo(), lat=-23.4, analogos=analogos)
    assert r["n_cenarios"] == 1


# ------------------------------------------------- SIDRA e backtest
def test_sidra_parser_robusto_a_ordem_das_dimensoes():
    obj = [{"D1C": "Município (Código)", "D1N": "Município", "D2N": "Variável",
            "D3N": "Ano", "D3C": "Ano (Código)", "V": "Valor"},
           {"D1C": "4115200", "D1N": "Maringá - PR", "D2N": "Rendimento médio",
            "D3N": "Ano", "D3C": "2020", "V": "3300"},
           {"D1C": "4115200", "D1N": "Maringá - PR", "D2N": "Rendimento médio",
            "D3N": "Ano", "D3C": "2021", "V": "..."}]
    # cabecalho real do SIDRA usa D?N como rotulo textual
    obj[0] = {"D1C": "Município (Código)", "D1N": "Município",
              "D3C": "Ano (Código)", "D3N": "Ano", "V": "Valor"}
    r = backtest.de_sidra(obj)
    assert r == {("4115200", 2020): 3300.0}


def test_backtest_escolhe_modelo_e_calibra_em_json():
    obs = _obs_sinteticas(seed=11, anos=tuple(range(2003, 2011)))
    rel = backtest.rodar_backtest(obs)
    assert rel["modelo_escolhido"] in ("jensen", "jensen_grupos")
    assert set(rel["cv"]) == {"loyo", "lomo"}
    mod = backtest.calibrar(obs, rel)
    json.dumps(mod)                         # serializavel
    m = Jensen.from_dict(mod["modelo"])
    assert m.calibrado and len(mod["ym_sc_ha_por_municipio"]) == 26


def test_montar_dataset_mapeia_ano_pam_para_plantio_anterior():
    chamadas = []

    def obter(m, ano_plantio):
        chamadas.append(ano_plantio)
        return simulacao.gerar_serie_continua(
            "%d-09-01" % ano_plantio, "%d-04-15" % (ano_plantio + 1), seed=ano_plantio)
    muns = [{"codigo_ibge": "4115200", "uf": "PR", "lat": -23.4, "lon": -51.9}]
    obs = backtest.montar_dataset({("4115200", 2020): 3300.0}, muns, obter)
    assert chamadas == [2019] and len(obs) == 1
    assert obs[0]["y"] == pytest.approx(55.0)


# ----------------------------------------------------- pipeline offline
def _fake_baixar_factory(falha_em=None):
    def baixar(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        lat = float(q["latitude"][0])
        if falha_em is not None and abs(lat - falha_em) < 1e-6:
            raise RuntimeError("falha de rede simulada")
        if "archive-api" in url:
            ini, fim = q["start_date"][0], q["end_date"][0]
        else:
            hoje = datetime.date(2026, 12, 10)
            ini = (hoje - datetime.timedelta(days=int(q["past_days"][0]))).isoformat()
            fim = (hoje + datetime.timedelta(days=int(q["forecast_days"][0]) - 1)).isoformat()
        return simulacao.para_open_meteo(
            simulacao.gerar_serie_continua(ini, fim, lat=lat, seed=int(abs(lat) * 10)))
    return baixar


MUNS = [{"codigo_ibge": "4115200", "uf": "PR", "cidade": "Maringa", "lat": -23.4,
         "lon": -51.9, "area_soja_ha": 1000.0, "regiao_id": "r1", "regiao_nome": "Norte"},
        {"codigo_ibge": "4113700", "uf": "PR", "cidade": "Londrina", "lat": -23.3,
         "lon": -51.2, "area_soja_ha": 3000.0, "regiao_id": "r1", "regiao_nome": "Norte"}]


def test_lote_offline_grava_json_csv_e_benchmark(tmp_path):
    r = pipeline.rodar_lote(MUNS, "2026-12-10", str(tmp_path),
                            baixar=_fake_baixar_factory(), ym_padrao=62.0)
    assert r["gravado"] and r["itens"] == 2 and not r["falhas"]
    doc = json.load(open(tmp_path / "previsao_produtividade.json", encoding="utf-8"))
    assert doc["schema"] == config.SCHEMA_SAIDA
    it = doc["itens"][0]
    assert it["safra"] == "2026/27" and it["rotulo"] == "estimativa"
    assert it["plantio_assumido"] == "2026-11-01" and it["confianca"] == "baixa"
    assert doc["regioes"][0]["n_municipios"] == 2
    bm = list(csv.DictReader(open(tmp_path / "benchmark_regional_previsto.csv",
                                  encoding="utf-8")))
    assert {"produtividade_media_sc_ha", "desvio_padrao", "cultura"} <= set(bm[0])


def test_lote_falha_isolada_nao_derruba_os_demais(tmp_path):
    r = pipeline.rodar_lote(MUNS, "2026-12-10", str(tmp_path),
                            baixar=_fake_baixar_factory(falha_em=-23.3), ym_padrao=62.0)
    assert r["gravado"] and r["itens"] == 1 and len(r["falhas"]) == 1


def test_lote_todos_falham_preserva_ultima_versao(tmp_path):
    antigo = tmp_path / "previsao_produtividade.json"
    antigo.write_text('{"versao":"anterior"}', encoding="utf-8")

    def sempre_falha(url):
        raise RuntimeError("offline")
    r = pipeline.rodar_lote(MUNS, "2026-12-10", str(tmp_path), baixar=sempre_falha,
                            ym_padrao=62.0)
    assert not r["gravado"]
    assert antigo.read_text(encoding="utf-8") == '{"versao":"anterior"}'


def test_plantio_e_safra_por_uf():
    assert pipeline.plantio_para("PR", "2026-12-10") == "2026-11-01"
    assert pipeline.plantio_para("PR", "2026-03-01") == "2025-11-01"
    assert pipeline.safra_de("2026-11-01") == "2026/27"


def test_cli_prever_com_open_meteo_json(tmp_path, capsys):
    from produtividade import main
    s = simulacao.gerar_serie_continua("2026-09-01", "2027-04-15", seed=2)
    p = tmp_path / "om.json"
    p.write_text(json.dumps(simulacao.para_open_meteo(s)), encoding="utf-8")
    out = tmp_path / "saida.json"
    main.main(["prever", "--clima", str(p), "--plantio", "2026-11-01", "--hoje",
               "2027-03-31", "--lat", "-23.4", "--ym", "65", "--saida", str(out)])
    r = json.load(open(out, encoding="utf-8"))
    assert r["schema"] == config.SCHEMA_SAIDA and r["rotulo"] == "estimativa"
    assert 0 < r["produtividade_sc_ha"]["p50"] <= 65 * 1.3
