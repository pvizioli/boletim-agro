# Modelo de produtividade de soja (Jensen modificado) - boletim-agro

Previsao de produtividade (sc/ha) a partir de JSON de clima e pluviometria.
Base: dissertacao de mestrado (Rodrigues, J. V. B.), que propoe incluir
variaveis indicadoras de agrupamento (k-medias) no modelo de Jensen (1968).
Roda em CPU (numpy + scipy), sem GPU, no GitHub Actions.

IMPORTANTE: a saida e sempre uma ESTIMATIVA de modelo, rotulada e com
confianca. Nunca substitui dado oficial (IMEA, CONAB, IBGE).
Leia docs/RELATORIO_TESTE_TESE.md antes de confiar no resultado.

## O que o modelo faz

1. Le series diarias de clima (Open-Meteo, NASA POWER, INMET, CHIRPS/chuva
   generica) e normaliza (ingestao.py).
2. Completa ETo (fonte -> Penman-Monteith -> Hargreaves) e roda o balanco
   hidrico diario com Kc da soja (balanco_hidrico.py).
3. Calcula ETR/ETm nas 4 fases da tese (20/50/40/40 dias).
4. Aplica Jensen: log(Y/Ym) = b0 + soma(lambda_i * log(ETR/ETm)_i)
   [+ soma dos efeitos de grupo, no modificado] (jensen.py).
5. Para dias que ainda nao ocorreram, simula cenarios com anos historicos
   analogos e devolve P10/P50/P90 + intervalo de 80% (previsao.py).

## Uso

Ponto unico, a partir de um JSON ja baixado:

    python -m produtividade.main prever --clima om.json --formato open-meteo \
        --plantio 2026-11-01 --hoje 2026-12-10 --lat -23.4 --ym 62 [--modelo modelo.json]

Formatos: open-meteo, nasa-power, inmet, normalizado.

Lote para o boletim (precisa de rede; Open-Meteo):

    python -m produtividade.main lote --uf PR --municipios config/municipios.csv \
        --saida web/data/out/produtividade [--modelo data/produtividade/modelo_produtividade.json]

Calibracao e backtest com dado real (IBGE PAM via SIDRA + Open-Meteo):

    python -m produtividade.main backtest --uf PR --municipios config/municipios.csv \
        --anos 2012-2025 --saida data/produtividade

Sem modelo calibrado o lote usa o prior generico FAO-33 (Ky 0,85) e marca
confianca BAIXA. A calibracao exige rendimentos observados (SIDRA).

## Contrato de saida (boletim-agro/produtividade/v1)

previsao_produtividade.json: schema, gerado_em, data_referencia, modelo
(id, calibrado, calibracao), avisos, itens[], regioes[], falhas[].
Cada item: uf, regiao_id, regiao_nome, municipio, codigo_ibge, cultura,
safra, plantio_assumido, fim_ciclo_estimado, fracao_ciclo_com_dados,
fases[] (razao ETR/ETm, mm), agua, produtividade_sc_ha {p10,p50,p90},
intervalo_80_total_sc_ha, metodo_incerteza, confianca, rotulo, avisos.

Tambem grava previsao_produtividade.csv e benchmark_regional_previsto.csv
(colunas cultura, produtividade_media_sc_ha, desvio_padrao: mesmo formato
que o Pilar 2 do MdG le em benchmark_regional_conab). O MdG nao foi
alterado: para usar a previsao como referencia, importe esse CSV de forma
explicita e identificada como previsao.

Regras de integridade: falha em um municipio nao derruba o lote; se todos
falharem, nada e sobrescrito; escrita via arquivo temporario + rename.

## Premissas (todas em config.py)

- Plantio por UF (PR=1/nov conforme a tese; demais UFs sao premissas a
  substituir por ZARC ou plantio observado).
- CAD pela classe ZARC (padrao AD3 = 42 mm); depleção p = 0,5 (FAO-56).
- Kc digitalizado da Figura 3.1 da tese (aproximado).
- Ciclo de 150 dias (cultivar tardia).
- Ym = maior produtividade historica do municipio na calibracao.

## Testes

    python -m pytest produtividade/tests -q        # 41 testes
    python -m produtividade.experimentos           # experimentos sinteticos

Os testes de adaptadores usam respostas montadas conforme a documentacao
das APIs; a primeira execucao em rede real (GitHub Actions) deve ser
conferida. O sandbox de desenvolvimento nao alcanca Open-Meteo, NASA POWER
nem SIDRA.

## Fase seguinte (satelite)

Ja existe o piloto NDVI/BSI (pipeline/satelite). Ligacoes previstas, ainda
nao implementadas: (a) emergencia/plantio detectados por NDVI no lugar da
data assumida; (b) NDVI de pico como preditor complementar; (c) pct_colhido
do satelite para validar fim_ciclo_estimado.
