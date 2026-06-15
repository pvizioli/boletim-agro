"""
Conector Open-Meteo - boletim-agro
==================================

Busca previsao diaria (7 dias) para MUITOS municipios de uma vez, agrupando
coordenadas numa unica chamada HTTP (batch). A API de forecast aceita listas
de latitude/longitude separadas por virgula e devolve um ARRAY de previsoes
na mesma ordem enviada.

Por que batch:
  Escala nacional = ~5.562 municipios. Uma chamada por municipio estouraria a
  cota gratuita (~10 mil/dia). Agrupando em lotes de TAMANHO_LOTE coordenadas,
  caem para ~56 chamadas por rodada (2x/dia = ~112/dia). Folgado.

Principios do projeto respeitados:
  - stdlib apenas (urllib): nada de pip, nada que o Forcepoint bloqueie no runner.
  - Falha de fonte nao derruba o boletim: em erro, retorna None para o lote e
    o main.py mantem a ultima versao valida com carimbo.
  - Cada metrica carrega fonte + data: ver campo "fonte" e "atualizado_em".

PONTO DE INTEGRACAO (conferir no main.py):
  A funcao publica e buscar_clima(municipios). Recebe uma lista de dicts com
  pelo menos {ibge, lat, lon} e devolve {ibge: bloco_clima}. O main.py deve
  encaixar cada bloco_clima dentro do latest.json do distrito. Os nomes de
  campo do bloco_clima estao documentados em montar_bloco() abaixo - se o site
  ja espera outros nomes, ajuste ali (um lugar so).
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

URL_BASE = "https://api.open-meteo.com/v1/forecast"
TAMANHO_LOTE = 100        # coordenadas por chamada (limite pratico de URL)
DIAS_PREVISAO = 7
TENTATIVAS = 3
ESPERA_BASE = 2.0         # segundos; backoff exponencial entre tentativas

# Variaveis diarias pedidas a API (ordem importa para leitura do JSON)
DAILY = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "weathercode",
]


def _lotes(seq, n):
    """Quebra uma lista em pedacos de tamanho n."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _chamar_api(lats, lons):
    """
    Faz UMA chamada multi-coordenada. Retorna lista de previsoes (uma por
    coordenada) ou levanta excecao. A API devolve dict quando ha 1 so
    coordenada e lista quando ha varias - normalizamos para lista sempre.
    """
    params = {
        "latitude": ",".join(str(x) for x in lats),
        "longitude": ",".join(str(x) for x in lons),
        "daily": ",".join(DAILY),
        "timezone": "auto",
        "forecast_days": DIAS_PREVISAO,
    }
    url = URL_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "boletim-agro/2.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    if isinstance(dados, dict):
        dados = [dados]
    return dados


def _chamar_com_retry(lats, lons):
    """Chama a API com ate TENTATIVAS, backoff exponencial. None se falhar."""
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return _chamar_api(lats, lons)
        except Exception as e:  # rede, timeout, 5xx, json invalido
            espera = ESPERA_BASE * (2 ** (tentativa - 1))
            print("  [open_meteo] tentativa " + str(tentativa) + "/" +
                  str(TENTATIVAS) + " falhou (" + str(e) + "); aguardando " +
                  str(espera) + "s")
            if tentativa < TENTATIVAS:
                time.sleep(espera)
    return None


# WMO weathercode -> categoria simples para o site escolher o icone SVG.
# Mantido aqui para haver um unico lugar com a regra.
def categoria_tempo(code):
    if code is None:
        return "indef"
    c = int(code)
    if c == 0:
        return "sol"
    if c in (1, 2):
        return "parcial"        # sol entre nuvens
    if c == 3:
        return "nuvem"
    if c in (45, 48):
        return "neblina"
    if c in (51, 53, 55, 56, 57):
        return "garoa"
    if c in (61, 63, 65, 66, 67, 80, 81, 82):
        return "chuva"
    if c in (71, 73, 75, 77, 85, 86):
        return "neve"
    if c in (95, 96, 99):
        return "trovoada"
    return "nuvem"


def montar_bloco(mun, prev, agora):
    """
    Monta o bloco_clima de UM municipio a partir da resposta da API.

    Campos do bloco (ALINHAR COM O SITE/main.py SE PRECISO):
      atual:       tmax, tmin, precip_mm, prob_chuva, weathercode, tempo (categoria)
      previsao_7d: lista de {data, tmax, tmin, precip_mm, prob_chuva, weathercode, tempo}
      fonte, atualizado_em
    """
    d = prev.get("daily", {})
    datas = d.get("time", [])
    tmax = d.get("temperature_2m_max", [])
    tmin = d.get("temperature_2m_min", [])
    pp = d.get("precipitation_sum", [])
    prob = d.get("precipitation_probability_max", [])
    wc = d.get("weathercode", [])

    def get(lst, i):
        return lst[i] if i < len(lst) else None

    dias = []
    for i in range(len(datas)):
        dias.append({
            "data": get(datas, i),
            "tmax": get(tmax, i),
            "tmin": get(tmin, i),
            "precip_mm": get(pp, i),
            "prob_chuva": get(prob, i),
            "weathercode": get(wc, i),
            "tempo": categoria_tempo(get(wc, i)),
        })

    atual = dias[0] if dias else {}
    return {
        "ibge": mun["ibge"],
        "nome": mun.get("nome"),
        "uf": mun.get("uf"),
        "lat": mun["lat"],
        "lon": mun["lon"],
        "atual": {
            "tmax": atual.get("tmax"),
            "tmin": atual.get("tmin"),
            "precip_mm": atual.get("precip_mm"),
            "prob_chuva": atual.get("prob_chuva"),
            "weathercode": atual.get("weathercode"),
            "tempo": atual.get("tempo"),
        },
        "previsao_7d": dias,
        "fonte": "Open-Meteo",
        "atualizado_em": agora,
    }


def buscar_clima(municipios):
    """
    FUNCAO PUBLICA. Recebe lista de dicts {ibge, lat, lon, nome?, uf?} e devolve
    {ibge: bloco_clima}. Municipios cujo lote falhar ficam de fora do dict
    retornado (o main.py mantem a ultima versao valida deles).

    Uso no main.py:
        from conectores.open_meteo import buscar_clima
        clima = buscar_clima(lista_de_municipios_do_distrito)
        for mun in distrito["municipios"]:
            bloco = clima.get(mun["ibge"])
            if bloco:
                mun["clima"] = bloco            # ou onde o latest.json espera
    """
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resultado = {}
    total = len(municipios)
    print("[open_meteo] " + str(total) + " municipios em lotes de " +
          str(TAMANHO_LOTE))

    for lote in _lotes(municipios, TAMANHO_LOTE):
        lats = [m["lat"] for m in lote]
        lons = [m["lon"] for m in lote]
        previsoes = _chamar_com_retry(lats, lons)

        if previsoes is None:
            print("  [open_meteo] lote de " + str(len(lote)) +
                  " municipios falhou; mantendo versao anterior")
            continue

        if len(previsoes) != len(lote):
            print("  [open_meteo] AVISO: API devolveu " + str(len(previsoes)) +
                  " previsoes para " + str(len(lote)) + " coordenadas")

        for mun, prev in zip(lote, previsoes):
            resultado[mun["ibge"]] = montar_bloco(mun, prev, agora)

        time.sleep(0.5)  # gentileza com a API entre lotes

    print("[open_meteo] ok para " + str(len(resultado)) + "/" + str(total) +
          " municipios")
    return resultado


if __name__ == "__main__":
    # Teste rapido com 3 municipios do distrito-piloto (coordenadas reais)
    amostra = [
        {"ibge": 4318309, "nome": "Sao Gabriel", "uf": "RS", "lat": -30.3337, "lon": -54.3217},
        {"ibge": 4318002, "nome": "Sao Borja", "uf": "RS", "lat": -28.6578, "lon": -56.0036},
        {"ibge": 4300406, "nome": "Alegrete", "uf": "RS", "lat": -29.7902, "lon": -55.7949},
    ]
    out = buscar_clima(amostra)
    for ibge, bloco in out.items():
        a = bloco["atual"]
        print(bloco["nome"], "-> tmax", a["tmax"], "tmin", a["tmin"],
              "chuva", a["precip_mm"], "mm", "(" + str(a["tempo"]) + ")")
