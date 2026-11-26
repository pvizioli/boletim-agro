# -*- coding: utf-8 -*-
"""Dados macroclimaticos e historico longo para o modelo de produtividade.

Grava em data/produtividade/raw/:
  indices/oni.txt, soi.txt, aao.txt   NOAA/CPC (ENSO, Oscilacao Sul, Antartica)
  poligonos/<nome>_<i>.json.gz        NASA POWER diario 1990-hoje em pontos
                                      de poligonos (pressao, chuva, temperatura)
  sidra_pam_soja_pr_1990.json         IBGE PAM 1990-2025 (rendimento e area)
  nasa_power_hist/<ibge>.json.gz      clima diario dos municipios 1990-2012
"""

import datetime
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(BASE, "data", "produtividade", "raw")
UA = {"User-Agent": "boletim-agro/macro"}
INDICES = {
    "oni": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "soi": "https://www.cpc.ncep.noaa.gov/data/indices/soi",
    "aao": "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_ao_index/aao/monthly.aao.index.b79.current.ascii",
}
# Poligonos imaginarios (lat, lon): pressao, chuva e frio que governam a safra no Sul
POLIGONOS = {
    "asas_centro": [(-25, -20), (-30, -20), (-25, -10), (-30, -10)],   # Alta Subtropical do Atlantico Sul
    "asas_oeste": [(-25, -40), (-30, -40), (-22, -37), (-28, -45)],    # flanco oeste da ASAS (umidade para o Sul)
    "chaco": [(-22, -62), (-25, -61), (-24, -64), (-20, -60)],         # Baixa do Chaco
    "prata": [(-35, -60), (-38, -58), (-33, -56), (-36, -63)],         # anticiclones polares / frentes frias
    "zcas": [(-15, -47), (-18, -45), (-20, -48), (-16, -50)],          # Zona de Convergencia do Atlantico Sul
    "pr_sul": [(-25.5, -52), (-26, -50), (-24.5, -53.5), (-23.5, -51)],  # controle: o proprio PR
}
HOJE = datetime.date.today()


def baixar(url, timeout=240, tent=4, txt=False):
    for t in range(tent):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return b.decode("utf-8", "replace") if txt else json.loads(b)
        except Exception as e:  # noqa: BLE001
            print("  retry", t + 1, str(e)[:100], flush=True)
            time.sleep(15 * (t + 1))
    raise RuntimeError("falhou " + url[:120])


def power(lat, lon, ini, fim):
    q = urllib.parse.urlencode({
        "parameters": "T2M_MAX,T2M_MIN,PRECTOTCORR,ALLSKY_SFC_SW_DWN,RH2M,WS2M,PS",
        "community": "AG", "longitude": lon, "latitude": lat,
        "start": ini, "end": fim, "format": "JSON"})
    return baixar("https://power.larc.nasa.gov/api/temporal/daily/point?" + q)


def gz(caminho, obj):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with gzip.open(caminho, "wt", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))


def etapa_indices():
    d = os.path.join(RAW, "indices")
    os.makedirs(d, exist_ok=True)
    for k, u in INDICES.items():
        try:
            open(os.path.join(d, k + ".txt"), "w").write(baixar(u, txt=True))
            print("indice", k, "ok", flush=True)
        except Exception as e:  # noqa: BLE001
            print("indice", k, "FALHOU", str(e)[:100], flush=True)


def etapa_poligonos():
    fim = (HOJE - datetime.timedelta(days=5)).strftime("%Y%m%d")
    for nome, pts in POLIGONOS.items():
        for i, (la, lo) in enumerate(pts):
            dst = os.path.join(RAW, "poligonos", "%s_%d.json.gz" % (nome, i))
            if os.path.exists(dst):
                continue
            try:
                gz(dst, power(la, lo, "19900101", fim))
                print("poligono", nome, i, "ok", flush=True)
            except Exception as e:  # noqa: BLE001
                print("poligono", nome, i, "FALHOU", str(e)[:100], flush=True)
            time.sleep(1)


def etapa_sidra():
    muns = json.load(open(os.path.join(RAW, "municipios_backtest.json"), encoding="utf-8"))
    cod = ",".join(m["ibge"] for m in muns)
    anos = ",".join(str(a) for a in range(1990, 2026))
    url = ("https://apisidra.ibge.gov.br/values/t/1612/n6/%s/v/112,216/p/%s/c81/2713" % (cod, anos))
    obj = baixar(url, timeout=300)
    json.dump(obj, open(os.path.join(RAW, "sidra_pam_soja_pr_1990.json"), "w"), ensure_ascii=False)
    print("SIDRA linhas", len(obj), flush=True)


def etapa_hist():
    muns = json.load(open(os.path.join(RAW, "municipios_backtest.json"), encoding="utf-8"))
    for i, m in enumerate(muns):
        dst = os.path.join(RAW, "nasa_power_hist", m["ibge"] + ".json.gz")
        if os.path.exists(dst):
            continue
        try:
            gz(dst, power(m["lat"], m["lon"], "19900701", "20120831"))
            print("hist", i + 1, m["nome"], flush=True)
        except Exception as e:  # noqa: BLE001
            print("hist FALHOU", m["nome"], str(e)[:100], flush=True)
        time.sleep(1)


if __name__ == "__main__":
    etapa = sys.argv[1] if len(sys.argv) > 1 else "tudo"
    if etapa in ("indices", "tudo"):
        etapa_indices()
    if etapa in ("poligonos", "tudo"):
        etapa_poligonos()
    if etapa in ("sidra", "tudo"):
        etapa_sidra()
    if etapa in ("hist", "tudo"):
        etapa_hist()
