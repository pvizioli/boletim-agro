"""
Conector Open-Meteo - boletim-agro (v2: pacing + tratamento de 429 + API key)
=============================================================================

Busca previsao diaria (7 dias) para muitos municipios agrupando coordenadas
numa unica chamada HTTP (batch). A API conta CADA coordenada como uma chamada
contra a cota - entao o controle de ritmo (pacing) e o tratamento de 429 sao
essenciais em escala nacional.

Limites do plano gratuito (nao-comercial): ~600/min, ~5.000/hora, ~10.000/dia.
Para produto comercial / volume maior: defina a variavel de ambiente
OPEN_METEO_APIKEY (usa o endpoint customer-api e remove os limites do free).

Estrategia:
  - pacing: dorme entre lotes para nao passar de TARGET_CHAMADAS_MIN/minuto.
  - 429: respeita o cabecalho Retry-After (ou backoff longo) antes de tentar de novo.
  - falha de fonte nao derruba o boletim: lote que falha de vez retorna nada e o
    main.py mantem a ultima versao valida.

Interface publica inalterada: buscar_clima(municipios) -> {ibge: bloco_clima}.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

APIKEY = os.environ.get("OPEN_METEO_APIKEY", "").strip()
URL_BASE = ("https://customer-api.open-meteo.com/v1/forecast" if APIKEY
            else "https://api.open-meteo.com/v1/forecast")

TAMANHO_LOTE = 100
DIAS_PREVISAO = 7
TENTATIVAS = 4
ESPERA_BASE = 3.0          # backoff base p/ erros de rede (s)
ESPERA_429 = 20.0          # espera minima ao tomar 429, se nao houver Retry-After
TARGET_CHAMADAS_MIN = 500  # ritmo alvo (margem sob os 600/min do free)

DAILY = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "weathercode",
    "windspeed_10m_max",
    "windgusts_10m_max",
    "winddirection_10m_dominant",
    "et0_fao_evapotranspiration",
]


def _lotes(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _pausa_por_chamadas(n):
    """Segundos necessarios para 'pagar' n chamadas no ritmo alvo."""
    return n / (TARGET_CHAMADAS_MIN / 60.0)


def _montar_url(lats, lons):
    params = {
        "latitude": ",".join(str(x) for x in lats),
        "longitude": ",".join(str(x) for x in lons),
        "daily": ",".join(DAILY),
        "timezone": "auto",
        "forecast_days": DIAS_PREVISAO,
    }
    if APIKEY:
        params["apikey"] = APIKEY
    return URL_BASE + "?" + urllib.parse.urlencode(params)


def _chamar_api(lats, lons):
    """Uma chamada multi-coordenada. Normaliza para lista. Propaga HTTPError."""
    url = _montar_url(lats, lons)
    req = urllib.request.Request(url, headers={"User-Agent": "boletim-agro/2.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    return [dados] if isinstance(dados, dict) else dados


def _chamar_com_retry(lats, lons):
    """Chama com pacing-aware retry. None se esgotar as tentativas."""
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return _chamar_api(lats, lons)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = e.headers.get("Retry-After") if e.headers else None
                try:
                    espera = float(ra) if ra else ESPERA_429
                except (TypeError, ValueError):
                    espera = ESPERA_429
                espera = max(espera, ESPERA_429)
                print("  [open_meteo] 429 (cota); aguardando " + str(espera) + "s")
            else:
                espera = ESPERA_BASE * (2 ** (tentativa - 1))
                print("  [open_meteo] HTTP " + str(e.code) + " tentativa " +
                      str(tentativa) + "/" + str(TENTATIVAS) + "; aguardando " +
                      str(espera) + "s")
        except Exception as e:  # rede, timeout SSL, json invalido
            espera = ESPERA_BASE * (2 ** (tentativa - 1))
            print("  [open_meteo] erro tentativa " + str(tentativa) + "/" +
                  str(TENTATIVAS) + " (" + str(e) + "); aguardando " +
                  str(espera) + "s")
        if tentativa < TENTATIVAS:
            time.sleep(espera)
    return None


def categoria_tempo(code):
    if code is None:
        return "indef"
    c = int(code)
    if c == 0:
        return "sol"
    if c in (1, 2):
        return "parcial"
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
    d = prev.get("daily", {})
    datas = d.get("time", [])

    def get(lst, i):
        return lst[i] if i < len(lst) else None

    tmax = d.get("temperature_2m_max", [])
    tmin = d.get("temperature_2m_min", [])
    pp = d.get("precipitation_sum", [])
    prob = d.get("precipitation_probability_max", [])
    wc = d.get("weathercode", [])
    vv = d.get("windspeed_10m_max", [])
    vr = d.get("windgusts_10m_max", [])
    vd = d.get("winddirection_10m_dominant", [])
    et = d.get("et0_fao_evapotranspiration", [])

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
            "vento_kmh": get(vv, i),
            "rajada_kmh": get(vr, i),
            "vento_dir_graus": get(vd, i),
            "et0_mm": get(et, i),
        })
    atual = dias[0] if dias else {}
    return {
        "ibge": mun["ibge"], "nome": mun.get("nome"), "uf": mun.get("uf"),
        "lat": mun["lat"], "lon": mun["lon"],
        "atual": {
            "tmax": atual.get("tmax"), "tmin": atual.get("tmin"),
            "precip_mm": atual.get("precip_mm"), "prob_chuva": atual.get("prob_chuva"),
            "weathercode": atual.get("weathercode"), "tempo": atual.get("tempo"),
        },
        "previsao_7d": dias,
        "fonte": "Open-Meteo", "atualizado_em": agora,
    }


def buscar_clima(municipios):
    """Lista de {ibge,lat,lon,nome?,uf?} -> {ibge: bloco_clima}. Lotes que
    falham ficam de fora (o main.py mantem a ultima versao valida)."""
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resultado = {}
    total = len(municipios)
    modo = "com API key" if APIKEY else "free (com pacing)"
    print("[open_meteo] " + str(total) + " municipios em lotes de " +
          str(TAMANHO_LOTE) + " (" + modo + ")")

    lotes = list(_lotes(municipios, TAMANHO_LOTE))
    for idx, lote in enumerate(lotes):
        lats = [m["lat"] for m in lote]
        lons = [m["lon"] for m in lote]
        previsoes = _chamar_com_retry(lats, lons)

        if previsoes is None:
            print("  [open_meteo] lote de " + str(len(lote)) +
                  " municipios falhou; mantendo versao anterior")
        else:
            if len(previsoes) != len(lote):
                print("  [open_meteo] AVISO: " + str(len(previsoes)) +
                      " previsoes para " + str(len(lote)) + " coordenadas")
            for mun, prev in zip(lote, previsoes):
                resultado[mun["ibge"]] = montar_bloco(mun, prev, agora)

        # pacing: dorme proporcional as chamadas feitas, exceto no ultimo lote
        if idx < len(lotes) - 1 and not APIKEY:
            time.sleep(_pausa_por_chamadas(len(lote)))

    print("[open_meteo] ok para " + str(len(resultado)) + "/" + str(total) +
          " municipios")
    return resultado


if __name__ == "__main__":
    amostra = [
        {"ibge": 4318309, "nome": "Sao Gabriel", "uf": "RS", "lat": -30.3337, "lon": -54.3217},
        {"ibge": 4318002, "nome": "Sao Borja", "uf": "RS", "lat": -28.6578, "lon": -56.0036},
    ]
    for ibge, b in buscar_clima(amostra).items():
        print(b["nome"], "tmax", b["atual"]["tmax"], "(" + str(b["atual"]["tempo"]) + ")")
