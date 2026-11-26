# -*- coding: utf-8 -*-
"""Coleta dados BRUTOS para o backtest do modelo de produtividade (PR).

Roda no GitHub Actions (ha rede). Grava em data/produtividade/raw/:
  sidra_pam_soja_pr.json           rendimento (v112, kg/ha) e area colhida
                                   (v216, ha) da soja, IBGE PAM, 2010-2025
  nasa_power/<ibge>.json.gz        diario 2012-09-01..2026-04-30
  open_meteo/<ibge>.json.gz        idem, para os municipios-chave da tese
Sem dependencias alem da stdlib. Falha por municipio nao interrompe.
"""

import csv
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(BASE, "data", "produtividade", "raw")
INI, FIM = "2012-09-01", "2026-04-30"
AREA_MIN = 20000.0
# municipios da tese (estacoes SIMEPAR, Fig. 3.3) + polos regionais
CHAVE = ["4103602", "4118402", "4113700", "4115200", "4105508", "4128104",
         "4101408", "4104808", "4127700", "4104303", "4119905", "4109401"]
UA = {"User-Agent": "boletim-agro/produtividade-backtest"}


def baixar(url, timeout=180, tentativas=3):
    for t in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            print("  tentativa", t + 1, "falhou:", str(e)[:120], flush=True)
            time.sleep(20 * (t + 1))
    raise RuntimeError("download falhou: " + url[:120])


def gravar_gz(caminho, obj):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with gzip.open(caminho, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))


def municipios():
    out = []
    with open(os.path.join(BASE, "config", "municipios.csv"),
              encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["uf"] != "PR":
                continue
            area = float(r["area_soja_ha"] or 0)
            if area >= AREA_MIN or r["codigo_ibge"] in CHAVE:
                out.append({"ibge": r["codigo_ibge"], "nome": r["cidade"],
                            "distrito": r["distrito_id"], "area": area,
                            "lat": float(r["latitude"]),
                            "lon": float(r["longitude"])})
    return out


def etapa_sidra(muns):
    codigos = ",".join(m["ibge"] for m in muns)
    anos = ",".join(str(a) for a in range(2010, 2026))
    url = ("https://apisidra.ibge.gov.br/values/t/1612/n6/%s/v/112,216/p/%s/c81/2713"
           % (codigos, anos))
    obj = baixar(url)
    with open(os.path.join(RAW, "sidra_pam_soja_pr.json"), "w",
              encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    print("SIDRA linhas:", len(obj), flush=True)


def etapa_power(muns):
    for i, m in enumerate(muns):
        dst = os.path.join(RAW, "nasa_power", m["ibge"] + ".json.gz")
        if os.path.exists(dst):
            continue
        q = urllib.parse.urlencode({
            "parameters": "T2M_MAX,T2M_MIN,PRECTOTCORR,ALLSKY_SFC_SW_DWN,RH2M,WS2M",
            "community": "AG", "longitude": m["lon"], "latitude": m["lat"],
            "start": INI.replace("-", ""), "end": FIM.replace("-", ""),
            "format": "JSON"})
        try:
            obj = baixar("https://power.larc.nasa.gov/api/temporal/daily/point?" + q)
            gravar_gz(dst, obj)
            print("POWER", i + 1, len(muns), m["nome"], flush=True)
        except Exception as e:  # noqa: BLE001
            print("POWER falhou", m["nome"], str(e)[:100], flush=True)
        time.sleep(2)


def etapa_open_meteo(muns):
    chave = [m for m in muns if m["ibge"] in CHAVE]
    for i, m in enumerate(chave):
        dst = os.path.join(RAW, "open_meteo", m["ibge"] + ".json.gz")
        if os.path.exists(dst):
            continue
        q = urllib.parse.urlencode({
            "latitude": m["lat"], "longitude": m["lon"], "start_date": INI,
            "end_date": FIM, "timezone": "America/Sao_Paulo",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                     "et0_fao_evapotranspiration,shortwave_radiation_sum"})
        try:
            obj = baixar("https://archive-api.open-meteo.com/v1/archive?" + q)
            gravar_gz(dst, obj)
            print("OPEN-METEO", i + 1, len(chave), m["nome"], flush=True)
        except Exception as e:  # noqa: BLE001
            print("OPEN-METEO falhou", m["nome"], str(e)[:100], flush=True)
        # chamada longa pesa ~350 unidades no plano gratuito: ~1 por 75 s
        time.sleep(75)


def main():
    etapa = sys.argv[1] if len(sys.argv) > 1 else "tudo"
    os.makedirs(RAW, exist_ok=True)
    muns = municipios()
    with open(os.path.join(RAW, "municipios_backtest.json"), "w",
              encoding="utf-8") as f:
        json.dump(muns, f, ensure_ascii=False, indent=0)
    print("municipios:", len(muns), flush=True)
    if etapa in ("sidra", "tudo"):
        etapa_sidra(muns)
    if etapa in ("power", "tudo"):
        etapa_power(muns)
    if etapa in ("openmeteo", "tudo"):
        etapa_open_meteo(muns)


if __name__ == "__main__":
    main()
