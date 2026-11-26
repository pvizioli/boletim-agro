# -*- coding: utf-8 -*-
"""Backtest final: satelite (S2 municipio inteiro e MODIS) + clima (Jensen)
contra IBGE PAM. Anomalias de vigor calculadas SO com anos de treino.
Gera metricas de acerto percentual frente ao real (produtividade e producao)."""
import sys, os, json, gzip, glob, math, datetime, collections
import numpy as np
from scipy.optimize import lsq_linear
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from produtividade import ingestao, balanco_hidrico as bh, config, cultivares
from produtividade import modelo_hibrido as mh

BT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(BT, 'raw')
CAD = 72.0
muns = {m['ibge']: m for m in json.load(open(os.path.join(RAW, 'municipios_backtest.json'), encoding='utf-8'))}
sid = json.load(open(os.path.join(RAW, 'sidra_pam_soja_pr.json'), encoding='utf-8'))
rend, area = {}, {}
for r in sid[1:]:
    try: v = float(r['V'])
    except: continue
    (rend if r['D2C'] == '112' else area)[(r['D1C'], int(r['D3C']))] = v
sh = lambda d, n: (datetime.date.fromisoformat(d) + datetime.timedelta(days=int(round(n)))).isoformat()
ago1 = lambda ano: datetime.date(ano, 8, 1)
DERAL = [('2022-10-03', 15), ('2022-10-24', 44), ('2022-10-31', 67),
         ('2023-10-09', 31), ('2023-10-16', 46), ('2023-10-23', 58), ('2020-10-31', 61)]
_cache = {}
def serie(ib):
    if ib not in _cache:
        o = json.load(gzip.open(os.path.join(RAW, 'nasa_power', ib + '.json.gz'), 'rt', encoding='utf-8'))
        _cache[ib] = ingestao.completar_eto(ingestao.de_nasa_power(o), muns[ib]['lat'])[0]
    return _cache[ib]

# ------------------------------------------------------------------ leitura S2
def ler_s2(pasta):
    out = {}
    for f in glob.glob(os.path.join(pasta, '*.json')):
        ib, ano = os.path.basename(f)[:-5].split('_'); ano = int(ano)
        j = json.load(open(f))
        d = (j.get('data') or [None])[0]
        if not d or 'outputs' not in d: continue
        so = d['outputs']['soja']['bands']['B0']['stats']
        fe = d['outputs']['fen']['bands']
        lat = muns[ib]['lat']
        px_ha = (0.00135 * 111320) * (0.00135 * 111320 * math.cos(math.radians(lat))) / 1e4
        nval = so['sampleCount'] - so['noDataCount']
        st = lambda b: fe[b]['stats']
        n_soja = st('sos')['sampleCount'] - st('sos')['noDataCount']
        if n_soja < 50: continue
        p = lambda b, k: st(b)['percentiles'][k]
        out[(ib, ano)] = {'area_sat_ha': so['mean'] * nval * px_ha, 'n_soja': n_soja,
            'sos': {q: p('sos', '%.1f' % q) for q in (10, 25, 50, 75, 90)},
            'pico': st('pico')['mean'], 'integ': p('integ', '50.0'), 'eos50': p('eos', '50.0'),
            'n15': st('ndvi15jan')['mean'], 'ij': p('integJan', '50.0')}
    return out

def ler_modis():
    fe = json.load(open(os.path.join(BT, 'feno_evi.json')))
    out = {}
    for k, f in fe.items():
        ib, ano = k.split('_'); ano = int(ano)
        if 'semeadura_p50' not in f: continue
        d0 = ago1(ano)
        dia = lambda iso: (datetime.date.fromisoformat(iso) - d0).days + 10  # sos = semeadura + 10
        out[(ib, ano)] = {'area_sat_ha': None, 'n_soja': f['n_soja'],
            'sos': {q: dia(f['semeadura_p%d' % q]) for q in (10, 25, 50, 75, 90)},
            'pico': f['pico_mediano'], 'integ': f['integral_mediana'],
            'eos50': (datetime.date.fromisoformat(f['colheita_p50']) - d0).days, 'n15': None, 'ij': None}
    return out

# ---------------------------------------------------- calibracao do atraso (Deral)
def frac_estado(sat, data, lag):
    ano = int(data[:4]); t = (datetime.date.fromisoformat(data) - ago1(ano)).days
    num = den = 0.0
    for (ib, a), f in sat.items():
        if a != ano: continue
        w = area.get((ib, ano + 1))
        if not w: continue
        x = [f['sos'][q] - lag for q in (10, 25, 50, 75, 90)]; y = [10, 25, 50, 75, 90]
        if t <= x[0]: p = max(0.0, 10 * (1 - (x[0] - t) / 20.0))
        elif t >= x[-1]: p = min(100.0, 90 + 10 * (t - x[-1]) / 20.0)
        else: p = float(np.interp(t, x, y))
        num += p * w; den += w
    return num / den if den else None

def calibrar_lag(sat):
    melhor = None
    for lag in range(0, 36):
        e = [frac_estado(sat, d, lag) - v for d, v in DERAL if frac_estado(sat, d, lag) is not None]
        if not e: continue
        rm = float(np.sqrt(np.mean(np.square(e))))
        if melhor is None or rm < melhor[1]: melhor = (lag, rm, float(np.mean(e)), len(e))
    # validacao: deixa uma safra do Deral de fora
    cv = []
    for safra in (2020, 2022, 2023):
        tr = [(d, v) for d, v in DERAL if int(d[:4]) != safra]; te = [(d, v) for d, v in DERAL if int(d[:4]) == safra]
        best = min(range(0, 36), key=lambda L: np.mean([(frac_estado(sat, d, L) - v) ** 2 for d, v in tr if frac_estado(sat, d, L) is not None] or [1e9]))
        cv += [frac_estado(sat, d, best) - v for d, v in te if frac_estado(sat, d, best) is not None]
    return {'lag': melhor[0], 'rmse_pp': round(melhor[1], 1), 'vies_pp': round(melhor[2], 1), 'n': melhor[3],
            'rmse_pp_fora_da_amostra': round(float(np.sqrt(np.mean(np.square(cv)))), 1) if cv else None}

# -------------------------------------------------------------- montar dataset
def montar(sat, lag, anos_pam):
    obs = []
    for (ib, ano), f in sorted(sat.items()):
        y = rend.get((ib, ano + 1))
        if not y or (ano + 1) not in anos_pam: continue
        s = serie(ib)
        sim0 = bh.simular(s, '%d-10-20' % ano, cad_mm=CAD)
        if sim0['dias_faltantes'] > 7: continue
        d0 = ago1(ano)
        sem = {k: (d0 + datetime.timedelta(days=int(round(f['sos'][q] - lag)))).isoformat() for k, q in (('p25', 25), ('p50', 50), ('p75', 75))}
        ciclo = float(np.clip(f['eos50'] - (f['sos'][50] - lag), 95, 150)) if f['eos50'] and f['eos50'] > 0 else 120.0
        rs, _ = mh.razoes_coortes(s, cultivares.coortes(sem, ciclo_satelite=ciclo), CAD)
        # em safra: clima so ate 15/jan (fases seguintes neutras)
        corte = '%d-01-15' % (ano + 1)
        s_jan = {d: v for d, v in s.items() if d <= corte}
        rj, _ = mh.razoes_coortes(s_jan, cultivares.coortes(sem, ciclo_satelite=ciclo), CAD)
        rj = [1.0 if (x is None or (isinstance(x, float) and math.isnan(x))) else x for x in (rj or [1, 1, 1, 1])]
        sim_j = bh.simular(s_jan, '%d-10-20' % ano, cad_mm=CAD)
        r0j = [1.0 if x is None else x for x in bh.razoes(sim_j)]
        obs.append({'mun': ib, 'ano': ano + 1, 'y': y / 60.0, 'area_pam': area.get((ib, ano + 1)),
                    'area_sat': f['area_sat_ha'], 'r0': bh.razoes(sim0), 'rs': rs, 'rj': rj, 'r0j': r0j,
                    'pico': f['pico'], 'integ': f['integ'], 'sem50': f['sos'][50] - lag,
                    'n15': f['n15'], 'ij': f['ij']})
    return [o for o in obs if o['rs'] is not None]

# ------------------------------------------------- modelo com anomalias sem vazamento
def ajusta_prediz(tr, te, chave_r, extras, agua=True):
    # anomalias por municipio com media/dp SO do treino
    ref = collections.defaultdict(list)
    for o in tr: ref[o['mun']].append(o)
    glob_ = {k: (np.mean([o[k] for o in tr]), np.std([o[k] for o in tr]) or 1.0) for k in extras}
    def anom(o, k):
        L = ref.get(o['mun'])
        if L and len(L) >= 3:
            v = [x[k] for x in L]; sd = np.std(v) or glob_[k][1]
            return (o[k] - np.mean(v)) / sd
        return (o[k] - glob_[k][0]) / glob_[k][1]
    def prep(L):
        out = []
        for o in L:
            d = {'mun': o['mun'], 'ano': o['ano'], 'y': o['y'], 'razoes': o[chave_r]}
            for k in extras: d[k] = anom(o, k)
            out.append(d)
        return out
    m = mh.Hibrido(usar_agua=agua, extras=extras).ajustar(prep(tr))
    return m.prever(prep(te))

def media_hist(tr, te):
    por = collections.defaultdict(list)
    for o in tr: por[o['mun']].append(o['y'])
    g = np.mean([o['y'] for o in tr])
    return [float(np.mean(por[o['mun']])) if o['mun'] in por else g for o in te]

def cv(obs, fn, prot):
    ch = 'ano' if prot == 'loyo' else 'mun'
    out = []
    for c in sorted(set(o[ch] for o in obs)):
        tr = [o for o in obs if o[ch] != c]; te = [o for o in obs if o[ch] == c]
        out += [dict(o, prev=p) for o, p in zip(te, fn(tr, te))]
    return out

def acerto(p, usar_area='pam'):
    y = np.array([x['y'] for x in p]); q = np.array([x['prev'] for x in p])
    ape = np.abs(q - y) / y
    res = {'n': len(p), 'acerto_medio_pct': round(100 * (1 - ape.mean()), 1),
           'dentro_5pct': round(100 * np.mean(ape <= .05), 1), 'dentro_10pct': round(100 * np.mean(ape <= .10), 1),
           'dentro_15pct': round(100 * np.mean(ape <= .15), 1), 'rmse_sc_ha': round(float(np.sqrt(np.mean((q - y) ** 2))), 2)}
    anos = sorted(set(x['ano'] for x in p)); ac_est = []; ac_prod = []; porano = {}
    for a in anos:
        L = [x for x in p if x['ano'] == a and x['area_pam']]
        w = np.array([x['area_pam'] for x in L])
        yo = np.average([x['y'] for x in L], weights=w); yp = np.average([x['prev'] for x in L], weights=w)
        ac_est.append(1 - abs(yp - yo) / yo)
        prod_real = sum(x['y'] * x['area_pam'] for x in L)
        if usar_area == 'sat' and all(x['area_sat'] for x in L):
            prod_prev = sum(x['prev'] * x['area_sat'] for x in L)
        else:
            prod_prev = sum(x['prev'] * x['area_pam'] for x in L)
        ac_prod.append(1 - abs(prod_prev - prod_real) / prod_real)
        porano[a] = {'real_sc_ha': round(yo, 1), 'prev_sc_ha': round(yp, 1), 'acerto_pct': round(100 * (1 - abs(yp - yo) / yo), 1),
                     'prod_real_mil_t': round(prod_real * 60 / 1e6, 1), 'prod_prev_mil_t': round(prod_prev * 60 / 1e6, 1)}
    res['acerto_agregado_pct'] = round(100 * np.mean(ac_est), 1)
    res['acerto_producao_pct'] = round(100 * np.mean(ac_prod), 1)
    res['por_safra'] = porano
    return res

def rodar(nome, obs, tem_jan):
    V = collections.OrderedDict()
    V['Media historica do municipio'] = lambda tr, te: media_hist(tr, te)
    V['Tendencia + efeito do municipio'] = lambda tr, te: ajusta_prediz(tr, te, 'r0', (), agua=False)
    V['Clima, calendario fixo (base)'] = lambda tr, te: ajusta_prediz(tr, te, 'r0', ())
    V['Clima + semeadura/ciclo do satelite'] = lambda tr, te: ajusta_prediz(tr, te, 'rs', ())
    V['Clima fixo + vigor do satelite'] = lambda tr, te: ajusta_prediz(tr, te, 'r0', ('pico', 'integ'))
    V['Hibrido completo (calendario + vigor)'] = lambda tr, te: ajusta_prediz(tr, te, 'rs', ('pico', 'integ', 'sem50'))
    if tem_jan:
        V['Em safra, 15/jan: clima ate 15/jan'] = lambda tr, te: ajusta_prediz(tr, te, 'r0j', ())
        V['Em safra, 15/jan: clima + satelite ate 15/jan'] = lambda tr, te: ajusta_prediz(tr, te, 'rj', ('n15', 'ij', 'sem50'))
    res = collections.OrderedDict()
    for k, fn in V.items():
        a = acerto(cv(obs, fn, 'loyo'), 'pam')
        b = acerto(cv(obs, fn, 'lomo'), 'pam')
        res[k] = {'safra_nova': a, 'municipio_novo': b}
        print('%-46s safra nova: acerto %5.1f%% | +-10%% %5.1f%% | agregado %5.1f%% | producao %5.1f%% || mun novo: acerto %5.1f%%' % (
            k, a['acerto_medio_pct'], a['dentro_10pct'], a['acerto_agregado_pct'], a['acerto_producao_pct'], b['acerto_medio_pct']), flush=True)
    return res

if __name__ == '__main__':
    saida = {}
    # MODIS (15 municipios, 6x6 km, 2013-2025)
    mo = ler_modis()
    cal = calibrar_lag(mo); print('MODIS atraso calibrado', cal)
    obs = montar(mo, cal['lag'], set(range(2013, 2026)))
    print('MODIS obs', len(obs), 'mun', len(set(o['mun'] for o in obs)))
    saida['modis'] = {'calibracao': cal, 'n_obs': len(obs), 'modelos': rodar('modis', obs, False)}
    # S2 (municipio inteiro)
    s2dir = os.path.join(BT, 's2')
    if os.path.isdir(s2dir) and glob.glob(os.path.join(s2dir, '*.json')):
        s2 = ler_s2(s2dir)
        cal2 = calibrar_lag(s2); print('S2 atraso calibrado', cal2)
        # area de soja: satelite x PAM
        pares = [(f['area_sat_ha'], area.get((ib, a + 1))) for (ib, a), f in s2.items() if area.get((ib, a + 1))]
        x = np.array([p[0] for p in pares]); y = np.array([p[1] for p in pares])
        ar = {'n': len(pares), 'corr': round(float(np.corrcoef(x, y)[0, 1]), 3),
              'razao_mediana_sat_pam': round(float(np.median(x / y)), 3),
              'acerto_area_pct': round(100 * (1 - float(np.mean(np.abs(x - y) / y))), 1)}
        print('S2 area de soja x PAM', ar)
        obs2 = montar(s2, cal2['lag'], set(range(2019, 2026)))
        print('S2 obs', len(obs2), 'mun', len(set(o['mun'] for o in obs2)))
        saida['s2'] = {'calibracao': cal2, 'area': ar, 'n_obs': len(obs2), 'modelos': rodar('s2', obs2, True)}
        # producao com area do satelite (modelo completo)
        fn = lambda tr, te: ajusta_prediz(tr, te, 'rs', ('pico', 'integ', 'sem50'))
        saida['s2']['producao_area_satelite'] = acerto(cv(obs2, fn, 'loyo'), 'sat')
        print('Producao com area do satelite: acerto %.1f%%' % saida['s2']['producao_area_satelite']['acerto_producao_pct'])
    json.dump(saida, open(os.path.join(BT, 'resultado_final.json'), 'w'), indent=1, ensure_ascii=False)
