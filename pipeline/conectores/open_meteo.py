"""Conector Open-Meteo — previsão 7d + observado dos últimos 7 dias, por coordenada.
API gratuita, sem chave: https://open-meteo.com/
"""
import requests

URL = "https://api.open-meteo.com/v1/forecast"
DAILY = ",".join([
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_gusts_10m_max",
    "relative_humidity_2m_mean",
])


def buscar(lat, lon, past_days=7, forecast_days=7):
    """Retorna dict com lista de dias (passado + futuro) para um ponto."""
    r = requests.get(URL, params={
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY,
        "timezone": "America/Sao_Paulo",
        "past_days": past_days,
        "forecast_days": forecast_days,
    }, timeout=30)
    r.raise_for_status()
    d = r.json().get("daily", {})
    tempos = d.get("time", [])

    def col(nome):
        v = d.get(nome) or [None] * len(tempos)
        return v

    tmax = col("temperature_2m_max")
    tmin = col("temperature_2m_min")
    chuva = col("precipitation_sum")
    prob = col("precipitation_probability_max")
    vento = col("wind_gusts_10m_max")
    umid = col("relative_humidity_2m_mean")

    dias = []
    for i, data in enumerate(tempos):
        dias.append({
            "data": data,
            "tmax": tmax[i],
            "tmin": tmin[i],
            "chuva_mm": chuva[i],
            "prob_chuva": prob[i],
            "vento_rajada_kmh": vento[i],
            "umidade_pct": umid[i],
        })
    return {"fonte": "open-meteo", "dias": dias}
