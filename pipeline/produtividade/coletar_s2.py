# -*- coding: utf-8 -*-
"""Fenologia da soja no MUNICIPIO INTEIRO com Sentinel-2 L2A (CDSE
Statistical API). A classificacao de soja e a fenologia sao calculadas por
pixel no servidor (fenologia_s2.js); a API devolve so estatisticas.

Saida: data/produtividade/s2/<ibge>_<ano_plantio>.json
Uso: python coletar_s2.py [n_municipios] [ano_ini] [ano_fim] [limite_pu]
Credenciais: CDSE_CLIENT_ID / CDSE_CLIENT_SECRET (secrets do repo).
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(BASE, "data", "produtividade", "raw")
OUT = os.path.join(BASE, "data", "produtividade", "s2")
GEO = os.path.join(BASE, "data", "produtividade", "geo")
TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
             "protocol/openid-connect/token")
STAT_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
IBGE = ("https://servicodados.ibge.gov.br/api/v3/malhas/municipios/%s"
        "?formato=application/vnd.geo%%2Bjson&qualidade=minima")
RES = 0.00135  # ~150 m
MODIS = ["4101408", "4102000", "4103602", "4104303", "4104808", "4104907",
         "4109401", "4113205", "4114005", "4117701", "4119608", "4119905",
         "4127403", "4127502", "4127700"]


def token():
    dados = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["CDSE_CLIENT_ID"],
        "client_secret": os.environ["CDSE_CLIENT_SECRET"]}).encode()
    req = urllib.request.Request(TOKEN_URL, data=dados, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["access_token"]


def geometria(ibge):
    os.makedirs(GEO, exist_ok=True)
    cam = os.path.join(GEO, ibge + ".geojson")
    if os.path.exists(cam):
        return json.load(open(cam))
    req = urllib.request.Request(IBGE % ibge, headers={"User-Agent": "boletim-agro"})
    with urllib.request.urlopen(req, timeout=60) as r:
        gj = json.load(r)
    g = gj["features"][0]["geometry"] if gj.get("type") == "FeatureCollection" else gj
    json.dump(g, open(cam, "w"))
    return g


def corpo(geom, ano, script):
    return {
        "input": {
            "bounds": {"geometry": geom, "properties": {
                "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}},
            "data": [{"type": "sentinel-2-l2a",
                      "dataFilter": {"maxCloudCoverage": 70}}]},
        "aggregation": {
            "timeRange": {"from": "%d-08-01T00:00:00Z" % ano,
                          "to": "%d-04-30T23:59:59Z" % (ano + 1)},
            "aggregationInterval": {"of": "P1Y", "lastIntervalBehavior": "SHORTEN"},
            "evalscript": script, "resx": RES, "resy": RES},
        "calculations": {
            "soja": {"statistics": {"default": {}}},
            "fen": {"statistics": {"default": {
                "percentiles": {"k": [10, 25, 50, 75, 90]}}}}}}


def post(tok, body):
    req = urllib.request.Request(STAT_URL, data=json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + tok, "Content-Type": "application/json",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        pu = r.headers.get("x-processingunits-spent")
        return json.load(r), pu


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    a0 = int(sys.argv[2]) if len(sys.argv) > 2 else 2018
    a1 = int(sys.argv[3]) if len(sys.argv) > 3 else 2024
    limite = float(sys.argv[4]) if len(sys.argv) > 4 else 7000.0
    script = open(os.path.join(os.path.dirname(__file__), "fenologia_s2.js")).read()
    muns = json.load(open(os.path.join(RAW, "municipios_backtest.json"), encoding="utf-8"))
    chave = [m for m in muns if m["ibge"] in MODIS]
    resto = sorted([m for m in muns if m["ibge"] not in MODIS], key=lambda m: -m["area"])
    alvo = (chave + resto)[:n]
    os.makedirs(OUT, exist_ok=True)
    tok, t_tok, gasto = token(), time.time(), 0.0
    print("municipios", len(alvo), "safras", a0, a1, flush=True)
    for m in alvo:
        try:
            geom = geometria(m["ibge"])
        except Exception as e:  # noqa: BLE001
            print("geometria falhou", m["nome"], str(e)[:100], flush=True)
            continue
        for ano in range(a0, a1 + 1):
            dst = os.path.join(OUT, "%s_%d.json" % (m["ibge"], ano))
            if os.path.exists(dst):
                continue
            if gasto > limite:
                print("limite de PU atingido", gasto, flush=True)
                return
            if time.time() - t_tok > 1500:
                tok, t_tok = token(), time.time()
            for tent in range(4):
                try:
                    res, pu = post(tok, corpo(geom, ano, script))
                    json.dump(res, open(dst, "w"))
                    gasto += float(pu or 0)
                    print(m["nome"], ano, "PU", pu, "acum %.0f" % gasto, flush=True)
                    break
                except urllib.error.HTTPError as e:
                    msg = e.read().decode("utf-8", "replace")[:300]
                    print("  HTTP", e.code, m["nome"], ano, msg, flush=True)
                    if e.code in (400, 403):
                        break
                    time.sleep(30 * (tent + 1))
                except Exception as e:  # noqa: BLE001
                    print("  erro", m["nome"], ano, str(e)[:150], flush=True)
                    time.sleep(30 * (tent + 1))


if __name__ == "__main__":
    main()
