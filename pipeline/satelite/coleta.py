# -*- coding: utf-8 -*-
"""Coleta de estatísticas NDVI/BSI via Statistical API (CDSE Sentinel Hub).

Para cada município-alvo, consulta médias de NDVI e BSI sobre o bbox
proxy em janelas de 5 dias. Não baixa rasters: a Statistical API agrega
no servidor, minimizando processing units.

S2: coleta bruta (sem máscara MapBiomas, sem estimativa de colheita).
As linhas gravadas levam confianca=coleta_bruta e pct vazio; a
conversão em pct_colhido_estimado calibrado entra no S3.
"""

import datetime
import json
import urllib.request

from . import config

STAT_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"


def evalscript_ndvi_bsi():
    """Evalscript V3 com saídas ndvi, bsi e dataMask.

    Escrito por concatenação (regra do projeto: zero backticks).
    """
    linhas = [
        "//VERSION=3",
        "function setup() {",
        "  return {",
        "    input: [{bands: [\"B02\", \"B04\", \"B08\", \"B11\", \"dataMask\"]}],",
        "    output: [",
        "      {id: \"ndvi\", bands: 1, sampleType: \"FLOAT32\"},",
        "      {id: \"bsi\", bands: 1, sampleType: \"FLOAT32\"},",
        "      {id: \"dataMask\", bands: 1}",
        "    ]",
        "  };",
        "}",
        "function evaluatePixel(s) {",
        "  var ndvi = (s.B08 - s.B04) / (s.B08 + s.B04);",
        "  var bsi = ((s.B11 + s.B04) - (s.B08 + s.B02)) /",
        "            ((s.B11 + s.B04) + (s.B08 + s.B02));",
        "  return {ndvi: [ndvi], bsi: [bsi], dataMask: [s.dataMask]};",
        "}",
    ]
    return "\n".join(linhas)


def montar_requisicao(bbox, data_ini, data_fim):
    return {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                },
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "maxCloudCoverage": config.NUVENS_MAX_PCT,
                    "mosaickingOrder": "leastCC",
                },
            }],
        },
        "aggregation": {
            "timeRange": {
                "from": data_ini + "T00:00:00Z",
                "to": data_fim + "T23:59:59Z",
            },
            "aggregationInterval": {"of": "P5D"},
            "width": 256,
            "height": 256,
            "evalscript": evalscript_ndvi_bsi(),
        },
    }


def _stats_banda(intervalo, saida):
    try:
        return intervalo["outputs"][saida]["bands"]["B0"]["stats"]
    except (KeyError, TypeError):
        return None


def coletar_municipio(token, alvo, dias=30, timeout=90):
    """Retorna lista de observações por janela de 5 dias.

    Cada item: data_imagem (início da janela), ndvi_medio, bsi_medio,
    amostras_validas_pct. Janelas sem cena válida são omitidas.
    """
    hoje = datetime.date.today()
    ini = (hoje - datetime.timedelta(days=dias)).isoformat()
    corpo = json.dumps(
        montar_requisicao(alvo["bbox"], ini, hoje.isoformat())
    ).encode("utf-8")
    req = urllib.request.Request(
        STAT_URL,
        data=corpo,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dados = json.load(resp)

    observacoes = []
    for intervalo in dados.get("data", []):
        ndvi = _stats_banda(intervalo, "ndvi")
        bsi = _stats_banda(intervalo, "bsi")
        if not ndvi or ndvi.get("mean") is None:
            continue
        total = (ndvi.get("sampleCount") or 0)
        nodata = (ndvi.get("noDataCount") or 0)
        validas = 100.0 * (total - nodata) / total if total else 0.0
        observacoes.append({
            "data_imagem": intervalo["interval"]["from"][:10],
            "ndvi_medio": round(ndvi["mean"], 4),
            "bsi_medio": round(bsi["mean"], 4) if bsi and bsi.get("mean") is not None else "",
            "amostras_validas_pct": round(validas, 1),
        })
    return observacoes


def safra_vigente(data=None):
    """Safra de soja BR: setembro a agosto (set/2026 abre a 2026/2027)."""
    d = data or datetime.date.today()
    if d.month >= 9:
        return str(d.year) + "/" + str(d.year + 1)
    return str(d.year - 1) + "/" + str(d.year)
