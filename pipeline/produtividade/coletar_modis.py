# -*- coding: utf-8 -*-
"""Coleta serie MODIS 250 m (MOD13Q1 Terra + MYD13Q1 Aqua) via ORNL DAAC
REST API (sem autenticacao) para os municipios do backtest.

Saida: data/produtividade/modis/<ibge>.npz com, por produto:
  <prod>_datas (AYYYYDDD), <prod>_ndvi, <prod>_evi, <prod>_rel, <prod>_doy
  (int16, forma [n_datas, n_pixels]) + nrows, ncols, lat, lon.
Uso: python coletar_modis.py [n_municipios] [km_raio]
"""

import concurrent.futures as cf
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(BASE, "data", "produtividade", "raw")
OUT = os.path.join(BASE, "data", "produtividade", "modis")
API = "https://modis.ornl.gov/rst/api/v1/"
PRODUTOS = ("MOD13Q1", "MYD13Q1")
BANDAS = {"evi": "250m_16_days_EVI",
          "rel": "250m_16_days_pixel_reliability",
          "doy": "250m_16_days_composite_day_of_the_year"}
INICIO = "2012-08-01"
CHAVE = ["4103602", "4118402", "4113700", "4115200", "4105508", "4128104",
         "4101408", "4104808", "4127700", "4104303", "4119905", "4109401"]


def get(url, tent=5):
    for t in range(tent):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "boletim-agro/fenologia"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            espera = 10 * (t + 1)
            print("  retry", t + 1, str(e)[:90], flush=True)
            time.sleep(espera)
    raise RuntimeError("falhou: " + url[:140])


def datas(prod, lat, lon):
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon})
    d = get(API + prod + "/dates?" + q)["dates"]
    ini = INICIO
    return [x["modis_date"] for x in d if x["calendar_date"] >= ini]


def subset(prod, lat, lon, banda, d0, d1, km):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "band": banda, "startDate": d0,
        "endDate": d1, "kmAboveBelow": km, "kmLeftRight": km})
    return get(API + prod + "/subset?" + q)


def coletar_municipio(m, km):
    dst = os.path.join(OUT, m["ibge"] + ".npz")
    if os.path.exists(dst):
        return "existe"
    arrs = {"lat": m["lat"], "lon": m["lon"]}
    for prod in PRODUTOS:
        ds = datas(prod, m["lat"], m["lon"])
        arrs[prod + "_datas"] = np.array(ds)
        lotes = [ds[i:i + 10] for i in range(0, len(ds), 10)]
        for chave, banda in BANDAS.items():
            blocos = {}
            tarefas = []
            with cf.ThreadPoolExecutor(max_workers=3) as ex:
                for lote in lotes:
                    tarefas.append(ex.submit(subset, prod, m["lat"], m["lon"],
                                             banda, lote[0], lote[-1], km))
                for f in tarefas:
                    obj = f.result()
                    arrs["nrows"], arrs["ncols"] = obj["nrows"], obj["ncols"]
                    for s in obj["subset"]:
                        blocos[s["modis_date"]] = s["data"]
            npx = arrs["nrows"] * arrs["ncols"]
            M = np.full((len(ds), npx), -32768, dtype=np.int16)
            for i, d in enumerate(ds):
                if d in blocos:
                    M[i] = np.array(blocos[d], dtype=np.int32).clip(-32768, 32767)
            arrs[prod + "_" + chave] = M
        print("  ", m["nome"], prod, len(ds), "datas, ultima", ds[-1], flush=True)
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(dst, **arrs)
    return "ok"


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    km = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    parte = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    partes = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    muns = json.load(open(os.path.join(RAW, "municipios_backtest.json"),
                          encoding="utf-8"))
    chave = [m for m in muns if m["ibge"] in CHAVE]
    resto = sorted([m for m in muns if m["ibge"] not in CHAVE],
                   key=lambda m: -m["area"])
    alvo = (chave + resto)[:n][parte::partes]
    print("municipios:", len(alvo), "raio km:", km, flush=True)
    for i, m in enumerate(alvo):
        t = time.time()
        try:
            r = coletar_municipio(m, km)
        except Exception as e:  # noqa: BLE001
            r = "FALHOU " + str(e)[:120]
        print(i + 1, m["nome"], r, "%.0fs" % (time.time() - t), flush=True)


if __name__ == "__main__":
    main()
