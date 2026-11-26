# -*- coding: utf-8 -*-
"""Fenologia da soja por satelite: confirmacao de cultura, semeadura,
pico e colheita, por pixel e agregado por municipio/regiao.

Independente do sensor: recebe series (data, indice de vegetacao, valido)
de MODIS (historico, 250 m), Sentinel-2 (10 m, acompanhamento) ou outro.

Metodo (com base em Becker et al., 2020, MODIS EVI no PR, e no estudo
de 2024 em Remote Sensing 16(14):2520, MODIS NDVI x Deral):
 1. remove quedas espurias (nuvem/sombra) e interpola para diario;
 2. suaviza com Savitzky-Golay em envelope superior (Chen et al., 2004);
 3. por temporada: pico de verao, minimos a esquerda/direita;
 4. SOS = cruzamento de 10% da amplitude na subida; semeadura = SOS - 10 d;
    colheita = queda de 80% entre o pico e o minimo a direita;
 5. soja confirmada se a curva tem forma e duracao de soja (regras abaixo).
Somente numpy/scipy; sem GPU.
"""

import datetime

import numpy as np
from scipy.signal import savgol_filter

# Regras de confirmacao (indice EVI em 0-1; ver PARAMS_NDVI para NDVI)
PARAMS_EVI = {
    "pico_min": 0.55, "base_max": 0.35, "amp_min": 0.28,
    "subida_dias": (30, 90), "ciclo_dias": (80, 150),
    "sos_janela": ("08-20", "01-15"), "pico_janela": ("11-15", "03-20"),
    "frac_sos": 0.10, "frac_colheita": 0.80, "lag_semeadura": 10,
}
PARAMS_NDVI = dict(PARAMS_EVI, pico_min=0.75, base_max=0.50, amp_min=0.30)


def _ord(d):
    return datetime.date.fromisoformat(d).toordinal()


def _iso(o):
    return datetime.date.fromordinal(int(o)).isoformat()


def limpar(t, v, ok, queda=0.10):
    """Remove observacoes invalidas e quedas isoladas (valor menor que os
    dois vizinhos por mais de `queda`): assinatura tipica de nuvem."""
    t = np.asarray(t, float)
    v = np.asarray(v, float)
    m = np.asarray(ok, bool) & np.isfinite(v)
    t, v = t[m], v[m]
    ordem = np.argsort(t)
    t, v = t[ordem], v[ordem]
    if len(v) >= 3:
        viz = np.minimum(np.r_[v[1], v[:-1]], np.r_[v[1:], v[-2]])
        bom = ~((viz - v) > queda)
        t, v = t[bom], v[bom]
    # datas repetidas (Terra/Aqua no mesmo dia): fica o maior valor
    if len(t):
        u, idx = np.unique(t, return_inverse=True)
        vm = np.full(len(u), -np.inf)
        np.maximum.at(vm, idx, v)
        t, v = u, vm
    return t, v


def diaria_suavizada(t, v, t0, t1, janela=31, iter_env=3):
    """Serie diaria [t0, t1] (ordinais) interpolada e suavizada (SG em
    envelope superior). Retorna (dias, y) ou (None, None) se faltam dados."""
    if len(t) < 8:
        return None, None
    dias = np.arange(int(t0), int(t1) + 1)
    y0 = np.interp(dias, t, v)
    y = y0.copy()
    for _ in range(iter_env):
        s = savgol_filter(y, janela, 2, mode="interp")
        y = np.maximum(y0, s) if _ < iter_env - 1 else s
    return dias, y


def _md_ord(ano, md):
    m, d = [int(x) for x in md.split("-")]
    return datetime.date(ano, m, d).toordinal()


def temporada(dias, y, ano_plantio, params=PARAMS_EVI):
    """Metricas de uma temporada (plantio em `ano_plantio`). Retorna dict
    com soja (bool), motivo, datas (ISO) e indices; ou None sem dados."""
    if dias is None:
        return None
    P = params
    a0, a1 = _md_ord(ano_plantio, P["pico_janela"][0]), _md_ord(ano_plantio + 1, P["pico_janela"][1])
    jan = (dias >= a0) & (dias <= a1)
    if not jan.any():
        return None
    ip = np.flatnonzero(jan)[np.argmax(y[jan])]
    pico, d_pico = float(y[ip]), int(dias[ip])
    esq = (dias >= d_pico - 130) & (dias <= d_pico - 20)
    dir_ = (dias >= d_pico + 20) & (dias <= d_pico + 120)
    if not esq.any() or not dir_.any():
        return None
    # base robusta: percentil 20 (quedas residuais de nuvem nao viram base)
    base = float(np.percentile(y[esq], 20))
    base_dir = float(np.percentile(y[dir_], 20))
    ir = np.flatnonzero(dir_)[-1]
    amp = pico - base
    out = {"pico": round(pico, 4), "data_pico": _iso(d_pico),
           "base": round(base, 4), "amplitude": round(amp, 4)}
    if amp <= 0:
        out.update(soja=False, motivo="sem_amplitude")
        return out
    lim_sos = base + P["frac_sos"] * amp
    # ultimo cruzamento ascendente antes do pico (busca do pico para tras)
    abaixo = np.flatnonzero((np.arange(len(dias)) < ip) & (y < lim_sos)
                            & (dias >= d_pico - 130))
    d_sos = int(dias[abaixo[-1] + 1]) if len(abaixo) else int(d_pico - 130)
    lim_col = pico - P["frac_colheita"] * (pico - base_dir)
    des = np.flatnonzero((np.arange(len(dias)) > ip) & (np.arange(len(dias)) <= ir) & (y <= lim_col))
    d_col = int(dias[des[0]]) if len(des) else int(dias[ir])
    integ = float(np.sum(np.clip(y[(dias >= d_sos) & (dias <= d_col)] - base, 0, None)))
    out.update({
        "sos": _iso(d_sos), "semeadura": _iso(d_sos - P["lag_semeadura"]),
        "colheita": _iso(d_col), "subida_dias": d_pico - d_sos,
        "ciclo_dias": d_col - (d_sos - P["lag_semeadura"]),
        "integral": round(integ, 2)})
    s0, s1 = _md_ord(ano_plantio, P["sos_janela"][0]), _md_ord(ano_plantio + 1, P["sos_janela"][1])
    motivos = []
    if pico < P["pico_min"]:
        motivos.append("pico_baixo")
    if base > P["base_max"]:
        motivos.append("sem_solo_exposto")
    if amp < P["amp_min"]:
        motivos.append("amplitude_baixa")
    if not (P["subida_dias"][0] <= out["subida_dias"] <= P["subida_dias"][1]):
        motivos.append("subida_atipica")
    if not (P["ciclo_dias"][0] <= out["ciclo_dias"] <= P["ciclo_dias"][1]):
        motivos.append("ciclo_atipico")
    if not (s0 <= d_sos <= s1):
        motivos.append("fora_da_janela")
    out["soja"] = not motivos
    out["motivo"] = ",".join(motivos) if motivos else "ok"
    return out


def pixels_temporada(T, V, OK, ano_plantio, params=PARAMS_EVI):
    """T: datas ordinais [n_obs]; V, OK: [n_obs, n_pix]. Retorna lista de
    metricas por pixel (None onde sem dados)."""
    t0 = _md_ord(ano_plantio, "07-01")
    t1 = _md_ord(ano_plantio + 1, "07-31")
    T = np.asarray(T)
    res = []
    for j in range(V.shape[1]):
        tj = T[:, j] if T.ndim == 2 else T
        sel = (tj >= t0 - 40) & (tj <= t1 + 40)
        if sel.sum() < 8 or tj[sel].max() < t1 - 60:
            res.append(None)   # temporada incompleta: usar emergencia_parcial
            continue
        t, v = limpar(tj[sel], V[sel, j], OK[sel, j])
        dias, y = diaria_suavizada(t, v, t0, t1)
        res.append(temporada(dias, y, ano_plantio, params))
    return res


def agregar(metricas, area_pixel_ha=None):
    """Resumo municipal: n pixels de soja, distribuicao de semeadura
    (p10..p90 em ISO), ciclo, pico e integral medianos."""
    soja = [m for m in metricas if m and m.get("soja")]
    validos = [m for m in metricas if m]
    out = {"n_pixels": len(metricas), "n_validos": len(validos),
           "n_soja": len(soja),
           "frac_soja": round(len(soja) / max(len(validos), 1), 4)}
    if area_pixel_ha:
        out["area_soja_ha_estimada"] = round(len(soja) * area_pixel_ha, 0)
    if len(soja) < 5:
        return out
    sem = np.array([_ord(m["semeadura"]) for m in soja])
    col = np.array([_ord(m["colheita"]) for m in soja])
    for q in (10, 25, 50, 75, 90):
        out["semeadura_p%d" % q] = _iso(np.percentile(sem, q))
    out["colheita_p50"] = _iso(np.percentile(col, 50))
    out["colheita_p90"] = _iso(np.percentile(col, 90))
    out["ciclo_mediano"] = float(np.median([m["ciclo_dias"] for m in soja]))
    out["pico_mediano"] = float(np.median([m["pico"] for m in soja]))
    out["integral_mediana"] = float(np.median([m["integral"] for m in soja]))
    out["data_pico_p50"] = _iso(np.percentile([_ord(m["data_pico"]) for m in soja], 50))
    return out


def fracao_semeada_ate(metricas, data_iso):
    """% dos pixels de soja semeados ate a data (para comparar com o
    avanco de plantio do Deral/IMEA)."""
    soja = [m for m in metricas if m and m.get("soja")]
    if not soja:
        return None
    lim = _ord(data_iso)
    return 100.0 * sum(_ord(m["semeadura"]) <= lim for m in soja) / len(soja)


def emergencia_parcial(T, V, OK, ano_plantio, hoje_iso, params=PARAMS_EVI,
                       amp_ref=0.40):
    """Temporada em curso (sem pico ainda): por pixel, base = percentil 20
    de jul-set; emergido se a serie suavizada recente passou base +
    frac_sos*amp_ref. Retorna lista {emergido, sos, semeadura} por pixel.
    Use com mascara de soja de anos anteriores (pixels que foram soja)."""
    P = params
    t0 = _md_ord(ano_plantio, "07-01")
    th = _ord(hoje_iso)
    T = np.asarray(T)
    out = []
    for j in range(V.shape[1]):
        tj = T[:, j] if T.ndim == 2 else T
        sel = (tj >= t0 - 40) & (tj <= th)
        t, v = limpar(tj[sel], V[sel, j], OK[sel, j])
        if len(t) < 6:
            out.append(None)
            continue
        dias = np.arange(t0, min(th, int(t.max())) + 1)
        y = np.interp(dias, t, v)
        if len(dias) > 31:
            y = savgol_filter(y, 31, 2, mode="interp")
        jan_base = (dias <= _md_ord(ano_plantio, "09-30"))
        base = float(np.percentile(y[jan_base], 20)) if jan_base.any() else float(y.min())
        lim = base + P["frac_sos"] * amp_ref
        acima = np.flatnonzero((y >= lim) & (dias >= _md_ord(ano_plantio, P["sos_janela"][0])))
        # exige subida sustentada: ultimo valor tambem acima do limiar
        if len(acima) and y[-1] >= base + 0.25 * amp_ref:
            abaixo = np.flatnonzero((np.arange(len(dias)) < acima[-1]) & (y < lim))
            d_sos = int(dias[abaixo[-1] + 1]) if len(abaixo) else int(dias[acima[0]])
            out.append({"emergido": True, "sos": _iso(d_sos),
                        "semeadura": _iso(d_sos - P["lag_semeadura"])})
        else:
            out.append({"emergido": False})
    return out
