# Módulo Satélite — Detecção de colheita via NDVI (piloto MT)

4ª camada de estimativa de colheita do boletim-agro. Gera estimativas
municipais de percentual colhido a partir de queda de NDVI (Sentinel-2)
confirmada por sinal de solo exposto (BSI), via Copernicus Data Space
Ecosystem (CDSE, tier gratuito).

## Princípios (herdados do projeto)

- Satélite NUNCA sobrescreve dado oficial (Conab/IMEA/Emater/Deral).
  Escreve apenas em data/colheita/colheita_satelite.csv, sempre com
  confianca=estimativa_satelite.
- Toda métrica carrega fonte + data da imagem + cobertura de nuvens.
- Falha de fonte nunca derruba o pipeline: preserva última versão válida.
- Job separado do cron climático (workflow satelite.yml, manual).

## Escopo do piloto

- UF: MT (78 municípios, 7 macrorregiões IMEA no crosswalk — ground
  truth para calibração).
- Safra alvo: 2026/27, capturando desde o plantio (set/out 2026).

## Barreiras conhecidas e mitigação

1. Máscara de soja por município — MapBiomas (classe soja, coleção mais
   recente). S1 usa bounding box em torno do centroide como proxy;
   máscara raster entra no S3.
2. Nuvens jan–mai — compositing multi-data (janela móvel de 10-15 dias,
   melhor pixel) + fusão futura com Sentinel-1 (radar).
3. Colheita vs. senescência natural — queda de NDVI só vira colheita se
   acompanhada de subida de BSI/NDTI (solo exposto).
4. Calibração — camada regional da Fase 4 (colheita_regional.csv, IMEA)
   é o ground truth; erro medido por macrorregião.

## Estrutura

- config.py — endpoints CDSE, constantes, thresholds (placeholder).
- cdse_auth.py — token OAuth2 client-credentials (secrets
  CDSE_CLIENT_ID / CDSE_CLIENT_SECRET).
- mascara_soja.py — catálogo de municípios-alvo (MT) com bbox proxy.
- main.py — orquestrador. Sem credenciais roda em dry-run (valida
  catálogo e schema, não escreve estimativas).

## Saída

data/colheita/colheita_satelite.csv — colunas:
uf, regiao_id, regiao_nome, municipio, codigo_ibge, cultura, safra,
data_referencia, data_imagem, ndvi_medio, bsi_medio,
cobertura_nuvens_pct, pct_colhido_estimado, confianca, fonte, gerado_em

## Roadmap

- S1 (feito): esqueleto, schema, workflow manual, catálogo MT.
- S2: conta CDSE + secrets no repo + primeiro request real de tile.
- S3: compositing, BSI/NDTI, máscara MapBiomas, calibração vs. IMEA.
