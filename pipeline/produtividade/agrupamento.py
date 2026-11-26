# -*- coding: utf-8 -*-
"""Agrupamento de municipios por clima (k-medias), como na tese.

Variaveis (Tabela 3.1 da tese): em blocos de 5 dias dentro de cada fase,
tmin, tmed, tmax, ppmax (maior chuva diaria) e ppacum (chuva acumulada).
Diferencas em relacao a tese (documentadas):
 - numero de grupos: a tese usa o indice d-HC (Souza, 2007), sem
   implementacao publica; aqui usamos silhueta com tamanho minimo de
   grupo (a tese teve parametros singulares em grupos de 2 municipios).
 - para previsao, os grupos sao CLIMATOLOGICOS (media de varios anos),
   estaveis, e nao recalculados a cada safra.
Somente numpy; sem GPU.
"""

import datetime

import numpy as np

from . import config

BLOCO_DIAS = 5
VARS = ("tmin", "tmed", "tmax", "ppmax", "ppacum")


def features_fases(serie, plantio, fases=config.FASES):
    """Retorna lista (uma por fase) de vetores numpy com as variaveis em
    blocos de 5 dias. Blocos com dados faltantes recebem NaN."""
    d0 = datetime.date.fromisoformat(plantio)
    saida, ini = [], 0
    for _, dur in fases:
        vec = []
        for b in range(dur // BLOCO_DIAS):
            tmn, tmx, pr = [], [], []
            for i in range(BLOCO_DIAS):
                dia = (d0 + datetime.timedelta(
                    days=ini + b * BLOCO_DIAS + i)).isoformat()
                r = serie.get(dia) or {}
                if r.get("tmin") is not None:
                    tmn.append(r["tmin"])
                if r.get("tmax") is not None:
                    tmx.append(r["tmax"])
                if r.get("prec") is not None:
                    pr.append(r["prec"])
            ok_t = len(tmn) == BLOCO_DIAS and len(tmx) == BLOCO_DIAS
            ok_p = len(pr) == BLOCO_DIAS
            vec.extend([
                min(tmn) if ok_t else np.nan,
                (sum(tmn) + sum(tmx)) / (2.0 * BLOCO_DIAS) if ok_t else np.nan,
                max(tmx) if ok_t else np.nan,
                max(pr) if ok_p else np.nan,
                sum(pr) if ok_p else np.nan])
        saida.append(np.array(vec, dtype=float))
        ini += dur
    return saida


def media_anos(lista_features):
    """Media (ignorando NaN) das features de varios anos -> climatologia."""
    n_fases = len(lista_features[0])
    return [np.nanmean(np.vstack([f[i] for f in lista_features]), axis=0)
            for i in range(n_fases)]


def _padronizar(X, mu=None, sd=None):
    if mu is None:
        mu = np.nanmean(X, axis=0)
        sd = np.nanstd(X, axis=0)
        sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    Z = np.where(np.isnan(Z), 0.0, Z)
    return Z, mu, sd


def kmeans(Z, k, n_init=10, max_iter=100, seed=0):
    """k-medias com inicializacao k-means++. Retorna (labels, centroides, inercia)."""
    rng = np.random.default_rng(seed)
    n = Z.shape[0]
    melhor = None
    for _ in range(n_init):
        c = [Z[rng.integers(n)]]
        for _ in range(1, k):
            d2 = np.min([np.sum((Z - ci) ** 2, axis=1) for ci in c], axis=0)
            s = d2.sum()
            p = d2 / s if s > 0 else np.full(n, 1.0 / n)
            c.append(Z[rng.choice(n, p=p)])
        C = np.vstack(c)
        lab = np.zeros(n, dtype=int)
        for _ in range(max_iter):
            D = ((Z[:, None, :] - C[None, :, :]) ** 2).sum(axis=2)
            novo = D.argmin(axis=1)
            if np.array_equal(novo, lab) and _ > 0:
                break
            lab = novo
            for j in range(k):
                if np.any(lab == j):
                    C[j] = Z[lab == j].mean(axis=0)
        D = ((Z[:, None, :] - C[None, :, :]) ** 2).sum(axis=2)
        lab = D.argmin(axis=1)
        inercia = float(D[np.arange(n), lab].sum())
        if melhor is None or inercia < melhor[2]:
            melhor = (lab.copy(), C.copy(), inercia)
    return melhor


def silhueta(Z, lab):
    n = len(lab)
    ks = np.unique(lab)
    if len(ks) < 2:
        return -1.0
    D = np.sqrt(((Z[:, None, :] - Z[None, :, :]) ** 2).sum(axis=2))
    s = np.zeros(n)
    for i in range(n):
        mesmo = (lab == lab[i])
        mesmo[i] = False
        a = D[i, mesmo].mean() if mesmo.any() else 0.0
        b = min(D[i, lab == k].mean() for k in ks if k != lab[i])
        s[i] = 0.0 if max(a, b) == 0 else (b - a) / max(a, b)
    return float(s.mean())


def escolher_k(Z, kmax=6, min_tamanho=3, seed=0):
    """Maior silhueta entre k = 2..kmax, exigindo grupos >= min_tamanho.
    Se nenhum k respeita o tamanho minimo, retorna k = 1 (sem dummies)."""
    n = Z.shape[0]
    melhor = (1, np.zeros(n, dtype=int), np.mean(Z, axis=0, keepdims=True), -1.0)
    for k in range(2, min(kmax, n // min_tamanho) + 1):
        lab, C, _ = kmeans(Z, k, seed=seed)
        tam = np.bincount(lab, minlength=k)
        if tam.min() < min_tamanho:
            continue
        s = silhueta(Z, lab)
        if s > melhor[3]:
            melhor = (k, lab, C, s)
    return melhor


def agrupar(features_por_mun, kmax=6, min_tamanho=3, seed=0):
    """features_por_mun: dict municipio -> lista de 4 vetores (fases).
    Retorna dict com, por fase: k, labels {mun: grupo}, centroides, mu, sd,
    silhueta. Pode ser serializado (listas) e usado por atribuir()."""
    muns = sorted(features_por_mun)
    resultado = {"municipios": muns, "fases": []}
    for i in range(len(config.FASES)):
        X = np.vstack([features_por_mun[m][i] for m in muns])
        Z, mu, sd = _padronizar(X)
        k, lab, C, sil = escolher_k(Z, kmax, min_tamanho, seed)
        resultado["fases"].append({
            "k": int(k), "silhueta": round(float(sil), 4),
            "labels": {m: int(l) for m, l in zip(muns, lab)},
            "centroides": C.tolist(), "mu": np.nan_to_num(mu).tolist(),
            "sd": sd.tolist()})
    return resultado


def atribuir(agrup_fase, vetor):
    """Grupo mais proximo para um municipio novo (ou ano novo)."""
    mu = np.array(agrup_fase["mu"])
    sd = np.array(agrup_fase["sd"])
    z = (np.asarray(vetor, dtype=float) - mu) / sd
    z = np.where(np.isnan(z), 0.0, z)
    C = np.array(agrup_fase["centroides"])
    return int(((C - z) ** 2).sum(axis=1).argmin())
