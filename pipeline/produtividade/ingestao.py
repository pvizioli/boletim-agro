# -*- coding: utf-8 -*-
"""Adaptadores: JSON de APIs publicas de clima -> serie diaria normalizada.

Formato normalizado: dict { "AAAA-MM-DD": {"tmax","tmin","prec","eto","rad","u2","rh"} }
  tmax/tmin em graus C, prec em mm/dia, eto em mm/dia, rad em MJ/m2/dia,
  u2 em m/s (2 m), rh em % (media). Campos ausentes ficam None.

Nenhuma funcao faz rede: recebem o JSON ja baixado. O download fica em
backtest.py / main.py, para o modelo ser testavel offline.
"""

import datetime
import math

CAMPOS = ("tmax", "tmin", "prec", "eto", "rad", "u2", "rh")


def _vazio():
    return {c: None for c in CAMPOS}


def _num(v):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or x <= -990:  # -999 = fill value (NASA POWER)
        return None
    return x


def _data_iso(s):
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return s[0:4] + "-" + s[4:6] + "-" + s[6:8]
    return s[0:10]


# --------------------------------------------------------------- Open-Meteo
def de_open_meteo(obj):
    """Resposta de /v1/forecast ou archive-api /v1/archive com daily=...
    Variaveis lidas: temperature_2m_max/min, precipitation_sum,
    et0_fao_evapotranspiration, shortwave_radiation_sum,
    relative_humidity_2m_mean, wind_speed_2m_mean (opcionais)."""
    d = obj.get("daily") or {}
    tempos = d.get("time") or []
    mapa = {
        "tmax": "temperature_2m_max", "tmin": "temperature_2m_min",
        "prec": "precipitation_sum", "eto": "et0_fao_evapotranspiration",
        "rad": "shortwave_radiation_sum", "rh": "relative_humidity_2m_mean",
        "u2": "wind_speed_2m_mean",
    }
    saida = {}
    for i, t in enumerate(tempos):
        reg = _vazio()
        for campo, chave in mapa.items():
            serie = d.get(chave)
            if serie is not None and i < len(serie):
                reg[campo] = _num(serie[i])
        saida[_data_iso(t)] = reg
    return saida


# --------------------------------------------------------------- NASA POWER
def de_nasa_power(obj):
    """Resposta de /api/temporal/daily/point (JSON). Le T2M_MAX, T2M_MIN,
    PRECTOTCORR, ALLSKY_SFC_SW_DWN, RH2M, WS2M. Converte kWh/m2 -> MJ/m2
    quando o metadado de unidade indicar kW-hr."""
    par = (obj.get("properties") or {}).get("parameter") or {}
    meta = obj.get("parameters") or {}
    fator_rad = 1.0
    un = str((meta.get("ALLSKY_SFC_SW_DWN") or {}).get("units", "")).lower()
    if "kw-hr" in un or "kwh" in un:
        fator_rad = 3.6
    mapa = {"tmax": "T2M_MAX", "tmin": "T2M_MIN", "prec": "PRECTOTCORR",
            "rad": "ALLSKY_SFC_SW_DWN", "rh": "RH2M", "u2": "WS2M"}
    datas = set()
    for chave in mapa.values():
        datas.update((par.get(chave) or {}).keys())
    saida = {}
    for dt in sorted(datas):
        reg = _vazio()
        for campo, chave in mapa.items():
            v = _num((par.get(chave) or {}).get(dt))
            if v is not None and campo == "rad":
                v = v * fator_rad
            reg[campo] = v
        saida[_data_iso(dt)] = reg
    return saida


# -------------------------------------------------------------------- INMET
def de_inmet(lista, min_horas=20):
    """Lista de registros horarios da API do INMET
    (apitempo.inmet.gov.br/estacao/{ini}/{fim}/{codigo}). Agrega para diario:
    tmax = max(TEM_MAX), tmin = min(TEM_MIN), prec = soma(CHUVA),
    rad = soma(RAD_GLO)/1000 (kJ/m2 -> MJ/m2). Dia com menos de `min_horas`
    registros fica sem chuva (None) para nao subestimar precipitacao."""
    por_dia = {}
    for r in lista or []:
        dia = _data_iso(r.get("DT_MEDICAO", ""))
        if not dia:
            continue
        por_dia.setdefault(dia, []).append(r)
    saida = {}
    for dia, regs in por_dia.items():
        reg = _vazio()
        tmx = [x for x in (_num(r.get("TEM_MAX")) for r in regs) if x is not None]
        tmn = [x for x in (_num(r.get("TEM_MIN")) for r in regs) if x is not None]
        chv = [x for x in (_num(r.get("CHUVA")) for r in regs) if x is not None]
        rad = [x for x in (_num(r.get("RAD_GLO")) for r in regs) if x is not None]
        if tmx:
            reg["tmax"] = max(tmx)
        if tmn:
            reg["tmin"] = min(tmn)
        if len(chv) >= min_horas:
            reg["prec"] = round(sum(chv), 2)
        if len(rad) >= min_horas:
            reg["rad"] = round(sum(rad) / 1000.0, 3)
        saida[dia] = reg
    return saida


# ------------------------------------------------------------------- CHIRPS
def de_chuva_generica(lista, chave_data=None, chave_valor=None):
    """Serie de chuva diaria de qualquer fonte (CHIRPS via ClimateSERV,
    Google Earth Engine, CSV convertido): lista de {data, mm}. Tenta chaves
    comuns (date/data/time; value/mm/precip/precipitation). Valores
    aninhados {'avg': x} sao aceitos."""
    saida = {}
    for r in lista or []:
        k_d = chave_data or next(
            (k for k in ("date", "data", "time", "dt") if k in r), None)
        k_v = chave_valor or next(
            (k for k in ("value", "mm", "precip", "precipitation", "prec")
             if k in r), None)
        if not k_d or not k_v:
            continue
        v = r[k_v]
        if isinstance(v, dict):
            v = v.get("avg", v.get("mean"))
        reg = _vazio()
        reg["prec"] = _num(v)
        dt = str(r[k_d])
        if "/" in dt:  # MM/DD/AAAA
            m, d, a = dt.split("/")[:3]
            dt = a.zfill(4) + "-" + m.zfill(2) + "-" + d.zfill(2)
        saida[_data_iso(dt)] = reg
    return saida


# ------------------------------------------------------------------ mesclar
def mesclar(base, *outras, campos=None):
    """Completa lacunas de `base` com as series seguintes, na ordem dada
    (prioridade decrescente). Nunca sobrescreve valor presente."""
    campos = campos or CAMPOS
    saida = {d: dict(r) for d, r in base.items()}
    for s in outras:
        for dia, reg in s.items():
            alvo = saida.setdefault(dia, _vazio())
            for c in campos:
                if alvo.get(c) is None and reg.get(c) is not None:
                    alvo[c] = reg[c]
    return saida


def mesclar_prioridade_chuva(base, chuva):
    """Troca a chuva da base pela de `chuva` (ex.: CHIRPS/estacao INMET),
    mantendo o restante. Dia sem chuva em `chuva` preserva o valor da base."""
    saida = {d: dict(r) for d, r in base.items()}
    for dia, reg in chuva.items():
        if reg.get("prec") is not None:
            saida.setdefault(dia, _vazio())["prec"] = reg["prec"]
    return saida


# --------------------------------------------------------------- ETo (FAO)
def _doy(iso):
    return datetime.date.fromisoformat(iso).timetuple().tm_yday


def radiacao_extraterrestre(lat_graus, doy):
    """Ra em MJ/m2/dia (FAO-56, eq. 21)."""
    phi = math.radians(lat_graus)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    dec = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    x = -math.tan(phi) * math.tan(dec)
    x = max(-1.0, min(1.0, x))
    ws = math.acos(x)
    gsc = 0.0820
    return (24 * 60 / math.pi) * gsc * dr * (
        ws * math.sin(phi) * math.sin(dec)
        + math.cos(phi) * math.cos(dec) * math.sin(ws))


def eto_hargreaves(tmin, tmax, lat_graus, doy):
    """ETo (mm/dia) de Hargreaves-Samani. Fallback quando so ha temperatura."""
    ra = radiacao_extraterrestre(lat_graus, doy)
    tmed = (tmax + tmin) / 2.0
    amp = max(tmax - tmin, 0.0)
    return max(0.0, 0.0023 * 0.408 * ra * (tmed + 17.8) * math.sqrt(amp))


def _es(t):
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def eto_penman_monteith(tmin, tmax, rs, u2, lat_graus, doy, alt_m=0.0,
                        rh_med=None, rh_max=None, rh_min=None):
    """ETo FAO-56 Penman-Monteith diaria. rs em MJ/m2/dia, u2 em m/s a 2 m."""
    tmed = (tmax + tmin) / 2.0
    delta = 4098 * _es(tmed) / (tmed + 237.3) ** 2
    pres = 101.3 * ((293 - 0.0065 * alt_m) / 293) ** 5.26
    gama = 0.000665 * pres
    es = (_es(tmax) + _es(tmin)) / 2.0
    if rh_max is not None and rh_min is not None:
        ea = (_es(tmin) * rh_max / 100.0 + _es(tmax) * rh_min / 100.0) / 2.0
    elif rh_med is not None:
        ea = es * rh_med / 100.0
    else:
        ea = _es(tmin)  # aproximacao FAO-56: Tdew ~ Tmin
    ra = radiacao_extraterrestre(lat_graus, doy)
    rso = (0.75 + 2e-5 * alt_m) * ra
    rns = 0.77 * rs
    razao = min(1.0, rs / rso) if rso > 0 else 0.5
    sigma = 4.903e-9
    rnl = sigma * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2.0) * (
        0.34 - 0.14 * math.sqrt(max(ea, 0.0))) * (1.35 * razao - 0.35)
    rn = rns - rnl
    num = 0.408 * delta * rn + gama * 900.0 / (tmed + 273.0) * u2 * (es - ea)
    den = delta + gama * (1 + 0.34 * u2)
    return max(0.0, num / den)


def completar_eto(serie, lat_graus, alt_m=0.0):
    """Preenche 'eto' ausente: PM se houver rad e u2; senao Hargreaves; se
    nao houver temperatura, deixa None. Retorna (serie, resumo_de_metodos)."""
    resumo = {"fonte": 0, "penman_monteith": 0, "hargreaves": 0, "ausente": 0}
    saida = {}
    for dia, reg in serie.items():
        r = dict(reg)
        if r.get("eto") is not None:
            resumo["fonte"] += 1
        elif r.get("tmax") is not None and r.get("tmin") is not None:
            doy = _doy(dia)
            if r.get("rad") is not None and r.get("u2") is not None:
                r["eto"] = round(eto_penman_monteith(
                    r["tmin"], r["tmax"], r["rad"], r["u2"], lat_graus, doy,
                    alt_m, rh_med=r.get("rh")), 3)
                resumo["penman_monteith"] += 1
            else:
                r["eto"] = round(eto_hargreaves(
                    r["tmin"], r["tmax"], lat_graus, doy), 3)
                resumo["hargreaves"] += 1
        else:
            resumo["ausente"] += 1
        saida[dia] = r
    return saida, resumo
