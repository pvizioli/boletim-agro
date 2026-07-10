# -*- coding: utf-8 -*-
"""Constantes do módulo satélite (piloto MT)."""

import os

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Entradas
MUNICIPIOS_CSV = os.path.join(BASE, "config", "municipios.csv")
CROSSWALK_CSV = os.path.join(BASE, "config", "crosswalk_regioes.csv")

# Saída (nunca sobrescreve dado oficial; arquivo próprio)
SAIDA_CSV = os.path.join(BASE, "data", "colheita", "colheita_satelite.csv")

COLUNAS_SAIDA = [
    "uf", "regiao_id", "regiao_nome", "municipio", "codigo_ibge",
    "cultura", "safra", "data_referencia", "data_imagem",
    "ndvi_medio", "bsi_medio", "cobertura_nuvens_pct",
    "pct_colhido_estimado", "confianca", "fonte", "gerado_em",
]

# CDSE — Copernicus Data Space Ecosystem (Sentinel Hub compatível)
CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)
CDSE_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
CDSE_CATALOG_URL = "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0/search"

# Credenciais via env (secrets do GitHub Actions no S2)
ENV_CLIENT_ID = "CDSE_CLIENT_ID"
ENV_CLIENT_SECRET = "CDSE_CLIENT_SECRET"

# Piloto
UF_PILOTO = "MT"
CULTURA = "soja"
ORGAO_GROUND_TRUTH = "imea"

# Thresholds preliminares (calibrar no S3 contra colheita_regional.csv)
NDVI_QUEDA_MINIMA = 0.20      # queda vs. pico da janela para candidatar colheita
BSI_SUBIDA_MINIMA = 0.10      # confirmação de solo exposto
NUVENS_MAX_PCT = 60.0         # descarta cena acima disso
JANELA_COMPOSITING_DIAS = 12  # melhor pixel na janela móvel

# Proxy de bbox no S1 (sem máscara MapBiomas ainda): meio-lado do quadrado
# em graus, escalado pela área de soja municipal no S3.
BBOX_MEIO_LADO_GRAUS = 0.15
