# -*- coding: utf-8 -*-
"""Construtores de URL e download das APIs publicas (so stdlib).

O modelo NAO depende destas funcoes: ele recebe JSON ja baixado. Elas
existem para backtest.py/main.py rodarem no GitHub Actions (que tem rede).
"""

import json
import urllib.parse
import urllib.request

OPEN_METEO_DIARIAS = ",".join([
    "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
    "et0_fao_evapotranspiration", "shortwave_radiation_sum"])


def url_open_meteo_historico(lat, lon, inicio, fim):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "start_date": inicio,
        "end_date": fim, "daily": OPEN_METEO_DIARIAS,
        "timezone": "America/Sao_Paulo"})
    return "https://archive-api.open-meteo.com/v1/archive?" + q


def url_open_meteo_previsao(lat, lon, dias_passados=7, dias_futuros=16):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "daily": OPEN_METEO_DIARIAS,
        "past_days": dias_passados, "forecast_days": dias_futuros,
        "timezone": "America/Sao_Paulo"})
    return "https://api.open-meteo.com/v1/forecast?" + q


def url_nasa_power(lat, lon, inicio, fim):
    """inicio/fim em AAAAMMDD."""
    q = urllib.parse.urlencode({
        "parameters": "T2M_MAX,T2M_MIN,PRECTOTCORR,ALLSKY_SFC_SW_DWN,RH2M,WS2M",
        "community": "AG", "longitude": lon, "latitude": lat,
        "start": inicio, "end": fim, "format": "JSON"})
    return "https://power.larc.nasa.gov/api/temporal/daily/point?" + q


def url_sidra_pam_soja(codigo_ibge, anos):
    """Rendimento medio (kg/ha) da soja, PAM municipal (tabela 1612,
    variavel 112, produto 2713). Fonte da produtividade OBSERVADA para
    calibracao e backtest."""
    return ("https://apisidra.ibge.gov.br/values/t/1612/n6/%s/v/112/p/%s/c81/2713"
            % (codigo_ibge, ",".join(str(a) for a in anos)))


def baixar_json(url, timeout=60, cabecalhos=None):
    req = urllib.request.Request(url, headers=cabecalhos or {
        "User-Agent": "boletim-agro/produtividade"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)
