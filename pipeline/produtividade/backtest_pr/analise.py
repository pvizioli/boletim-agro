# -*- coding: utf-8 -*-
"""Backtest real: PR, PAM (IBGE) x clima (NASA POWER / Open-Meteo)."""
import gzip, json, os, sys, collections, datetime
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from produtividade import ingestao, balanco_hidrico as bh, agrupamento, avaliacao, config
from produtividade.jensen import Jensen

RAW = sys.argv[1]
FONTE = sys.argv[2] if len(sys.argv) > 2 else 'nasa_power'
MD = sys.argv[3] if len(sys.argv) > 3 else '11-01'
CAD = float(sys.argv[4]) if len(sys.argv) > 4 else 42.0

muns = {m['ibge']: m for m in json.load(open(os.path.join(RAW, 'municipios_backtest.json'), encoding='utf-8'))}
sid = json.load(open(os.path.join(RAW, 'sidra_pam_soja_pr.json'), encoding='utf-8'))
cab = sid[0]
kv = {v: k for k, v in cab.items()}
def col(nome):
    k = next(k for k, v in cab.items() if k.endswith('N') and v.startswith(nome)); return k[:-1] + 'C'
kM, kA, kV = col('Munic'), col('Ano'), col('Vari')
rend, area = {}, {}
for r in sid[1:]:
    try: v = float(r['V'])
    except: continue
    key = (r[kM], int(r[kA]))
    if r[kV] == '112': rend[key] = v
    elif r[kV] == '216': area[key] = v

def serie_de(ibge):
    p = os.path.join(RAW, FONTE, ibge + '.json.gz')
    if not os.path.exists(p): return None
    obj = json.load(gzip.open(p, 'rt', encoding='utf-8'))
    s = ingestao.de_nasa_power(obj) if FONTE == 'nasa_power' else ingestao.de_open_meteo(obj)
    s, _ = ingestao.completar_eto(s, muns[ibge]['lat'])
    return s

obs = []
for ibge, m in muns.items():
    s = serie_de(ibge)
    if s is None: continue
    for ano in range(2013, 2027):
        if (ibge, ano) not in rend: continue
        mds = ['09-25', '10-15', '11-05'] if MD == 'mix' else [MD]
        sims = [bh.simular(s, '%d-%s' % (ano - 1, md), cad_mm=CAD) for md in mds]
        if max(x['dias_faltantes'] for x in sims) > 7: continue
        sim = sims[len(sims) // 2]
        pl = '%d-%s' % (ano - 1, mds[len(mds) // 2])
        raz = [float(np.mean([x['por_fase'][i]['razao'] for x in sims])) for i in range(4)]
        obs.append({'mun': ibge, 'ano': ano, 'y': rend[(ibge, ano)] / 60.0,
                    'area': area.get((ibge, ano), m['area']), 'razoes': raz,
                    'prec': sim['prec_total_mm'], 'etr_etm': sim['etr_total_mm'] / max(sim['etm_total_mm'], 1),
                    'feat': agrupamento.features_fases(s, pl)})

def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]

# --- variante FE + tendencia: log y = a_mun + b*(ano-2018) + sum lam log r
def fe_tend(tr, te, usar_clima=True, nn=True):
    ms = sorted(set(o['mun'] for o in tr))
    idx = {m: i for i, m in enumerate(ms)}
    def X(os_):
        A = np.zeros((len(os_), len(ms)))
        for k, o in enumerate(os_):
            if o['mun'] in idx: A[k, idx[o['mun']]] = 1
        t = np.array([[o['ano'] - 2018.0] for o in os_])
        cols = [A, t]
        if usar_clima:
            cols.append(np.log(np.clip(np.array([o['razoes'] for o in os_], float), config.RAZAO_MIN, 1)))
        return np.hstack(cols)
    Xt, yt = X(tr), np.log([o['y'] for o in tr])
    from scipy.optimize import lsq_linear
    lb = np.full(Xt.shape[1], -np.inf)
    if usar_clima and nn: lb[-4:] = 0
    b = lsq_linear(Xt, yt, bounds=(lb, np.full(Xt.shape[1], np.inf))).x
    Xe = X(te)
    # municipio sem historico (LOMO): intercepto medio
    a_med = b[:len(ms)].mean()
    pred = []
    for k, o in enumerate(te):
        v = Xe[k] @ b
        if o['mun'] not in idx: v += a_med
        pred.append(float(np.exp(v)))
    return pred, b

def cv(metodo, prot):
    chaves = sorted(set(o['ano' if prot == 'loyo' else 'mun'] for o in obs))
    out = []
    for c in chaves:
        tr = [o for o in obs if o['ano' if prot == 'loyo' else 'mun'] != c]
        te = [o for o in obs if o['ano' if prot == 'loyo' else 'mun'] == c]
        if metodo == 'tendencia': p, _ = fe_tend(tr, te, usar_clima=False)
        elif metodo == 'jensen_tendencia': p, _ = fe_tend(tr, te, usar_clima=True)
        else: p = avaliacao.prever_fold(tr, te, metodo)
        out += [dict(o, prev=v) for o, v in zip(te, p)]
    return out

res = {'fonte': FONTE, 'plantio_md': MD, 'cad': CAD, 'n_obs': len(obs),
       'n_mun': len(set(o['mun'] for o in obs)), 'anos': sorted(set(o['ano'] for o in obs)), 'cv': {}, 'por_ano': {}}
preds = {}
for prot in ('loyo', 'lomo'):
    for met in ('media_mun', 'tendencia', 'jensen', 'jensen_grupos', 'jensen_tendencia'):
        o = cv(met, prot)
        preds[(prot, met)] = o
        mm = avaliacao.metricas([x['y'] for x in o], [x['prev'] for x in o])
        res['cv'].setdefault(prot, {})[met] = {k: round(v, 3) for k, v in mm.items()}
# por ano (LOYO), media ponderada por area: observado x previsto
for met in ('tendencia', 'jensen_tendencia', 'jensen'):
    o = preds[('loyo', met)]
    for ano in res['anos']:
        oo = [x for x in o if x['ano'] == ano]
        w = np.array([x['area'] for x in oo]); 
        res['por_ano'].setdefault(str(ano), {})['obs'] = round(float(np.average([x['y'] for x in oo], weights=w)), 1)
        res['por_ano'][str(ano)][met] = round(float(np.average([x['prev'] for x in oo], weights=w)), 1)
# acerto em anos de quebra: anomalia vs tendencia
_, b = fe_tend(obs, obs[:1])
res['lambdas_full'] = [round(float(x), 3) for x in b[-4:]]
res['tendencia_pct_ano'] = round(float(np.expm1(b[-5]) * 100), 2)
# correlacao entre deficit e anomalia
json.dump(res, open(os.path.join(os.path.dirname(RAW), 'resultado_%s_%s_%d.json' % (FONTE, MD, CAD)), 'w'), indent=1)
json.dump([{k: v for k, v in x.items() if k != 'feat'} for x in preds[('loyo', 'jensen_tendencia')]],
          open(os.path.join(os.path.dirname(RAW), 'preds_%s_%s_%d.json' % (FONTE, MD, CAD)), 'w'))
print(json.dumps({k: res[k] for k in ('fonte', 'plantio_md', 'cad', 'n_obs', 'n_mun', 'lambdas_full', 'tendencia_pct_ano')}))
for prot in res['cv']:
    print(prot, {m: (v['rmse'], v['r2']) for m, v in res['cv'][prot].items()})
for a, v in res['por_ano'].items(): print(a, v)
