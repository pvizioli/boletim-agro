# -*- coding: utf-8 -*-
"""Catálogo de municípios-alvo do piloto satélite.

Cruza config/municipios.csv (lat/lon, área de soja) com
config/crosswalk_regioes.csv (macrorregião IMEA) para a UF piloto.

No S1 a "máscara" é um bounding box quadrado em torno do centroide
(proxy). No S3 entra a máscara raster MapBiomas (classe soja), que
substitui o bbox por geometria real de lavoura.
"""

import csv

from . import config


def _ler_csv(caminho):
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def bbox_proxy(lat, lon, meio_lado=None):
    """Bounding box [oeste, sul, leste, norte] em torno do centroide."""
    m = config.BBOX_MEIO_LADO_GRAUS if meio_lado is None else meio_lado
    return [lon - m, lat - m, lon + m, lat + m]


def carregar_alvos(uf=None):
    """Lista de municípios-alvo com regiao IMEA e bbox proxy.

    Cada item: codigo_ibge, municipio, uf, latitude, longitude,
    area_soja_ha, regiao_id, regiao_nome, confianca_crosswalk, bbox.
    Municípios da UF sem linha no crosswalk são ignorados com aviso
    (o piloto exige ground truth regional).
    """
    uf = uf or config.UF_PILOTO
    municipios = [m for m in _ler_csv(config.MUNICIPIOS_CSV) if m.get("uf") == uf]
    cross = {
        c["codigo_ibge"]: c
        for c in _ler_csv(config.CROSSWALK_CSV)
        if c.get("uf") == uf
    }
    alvos = []
    sem_regiao = []
    vistos = set()
    for m in municipios:
        cod = m.get("codigo_ibge", "").strip()
        if not cod or cod in vistos:
            continue
        vistos.add(cod)
        c = cross.get(cod)
        if not c:
            sem_regiao.append(m.get("cidade", cod))
            continue
        try:
            lat = float(m["latitude"])
            lon = float(m["longitude"])
        except (KeyError, TypeError, ValueError):
            sem_regiao.append(m.get("cidade", cod) + " (sem coordenada)")
            continue
        try:
            area = float(m.get("area_soja_ha") or 0)
        except ValueError:
            area = 0.0
        alvos.append({
            "codigo_ibge": cod,
            "municipio": m.get("cidade", ""),
            "uf": uf,
            "latitude": lat,
            "longitude": lon,
            "area_soja_ha": area,
            "regiao_id": c.get("regiao_id", ""),
            "regiao_nome": c.get("regiao_nome", ""),
            "confianca_crosswalk": c.get("confianca", ""),
            "bbox": bbox_proxy(lat, lon),
        })
    if sem_regiao:
        print("  [aviso] " + str(len(sem_regiao)) +
              " municipio(s) de " + uf + " fora do crosswalk: " +
              ", ".join(sorted(sem_regiao)[:5]) +
              ("..." if len(sem_regiao) > 5 else ""))
    alvos.sort(key=lambda a: (a["regiao_id"], a["municipio"]))
    return alvos
