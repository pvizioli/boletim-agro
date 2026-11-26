# -*- coding: utf-8 -*-
import sys, os, json, gzip, datetime, collections
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from produtividade import ingestao, balanco_hidrico as bh, config, avaliacao
from produtividade import modelo_hibrido as mh, cultivares

BT = os.path.dirname(os.path.abspath(__file__)); RAW = os.path.join(BT, 'raw')
INDICE = os.environ.get('INDICE', 'evi'); FONTE = os.environ.get('FONTE', 'nasa_power')
CAD = float(os.environ.get('CAD', '72')); LAG = int(os.environ.get('LAG', '0'))
feno = json.load(open(os.path.join(BT, 'feno_%s.json' % INDICE)))
muns = {m['ibge']: m for m in json.load(open(os.path.join(RAW, 'municipios_backtest.json'), encoding='utf-8'))}
sid = json.load(open(os.path.join(RAW, 'sidra_pam_soja_pr.json'), encoding='utf-8'))
rend, area = {}, {}
for r in sid[1:]:
    try: v = float(r['V'])
    except: continue
    (rend if r['D2C'] == '112' else area)[(r['D1C'], int(r['D3C']))] = v
ibs = sorted(set(k.split('_')[0] for k in feno))
sh = lambda d, n: (datetime.date.fromisoformat(d) + datetime.timedelta(days=n)).isoformat()
res = {'indice': INDICE, 'fonte': FONTE, 'cad': CAD, 'lag_extra': LAG}

# ---------- 1. calendario x Deral (estado; media ponderada por area PAM)
DERAL = [('2022-10-03', 15), ('2022-10-24', 44), ('2022-10-31', 67),
         ('2023-10-09', 31), ('2023-10-16', 46), ('2023-10-23', 58), ('2020-10-31', 61)]
def frac_ponderada(data):
    ano = int(data[:4]); num = den = 0.0
    for ib in ibs:
        f = feno.get('%s_%d' % (ib, ano)); a = area.get((ib, ano + 1))
        if not f or not a or f.get('n_soja', 0) < 20: continue
        # recalcula com lag extra usando p10..p90 (interpolacao)
        qs = [(q, f['semeadura_p%d' % q]) for q in (10, 25, 50, 75, 90)]
        x = [datetime.date.fromisoformat(sh(d, LAG)).toordinal() for _, d in qs]
        y = [q for q, _ in qs]
        t = datetime.date.fromisoformat(data).toordinal()
        p = float(np.interp(t, x, y, left=0, right=100))
        if t < x[0]: p = 10.0 * max(0, 1 - (x[0] - t) / 20.0)
        if t > x[-1]: p = 90 + 10 * min(1, (t - x[-1]) / 20.0)
        num += p * a; den += a
    return num / den if den else None
res['deral'] = [{'data': d, 'deral_pct': v, 'satelite_pct': round(frac_ponderada(d), 1)} for d, v in DERAL]
e = np.array([x['satelite_pct'] - x['deral_pct'] for x in res['deral']])
res['deral_erro_medio_pp'] = round(float(e.mean()), 1); res['deral_rmse_pp'] = round(float(np.sqrt((e ** 2).mean())), 1)

# ---------- 2. area de soja detectada x PAM (correlacao no tempo, por municipio)
cors = []
for ib in ibs:
    xs = [(feno['%s_%d' % (ib, a)].get('n_soja', 0), area.get((ib, a + 1))) for a in range(2012, 2025)]
    xs = [(p, q) for p, q in xs if q]
    if len(xs) > 6 and np.std([p for p, _ in xs]) > 0:
        cors.append(np.corrcoef(*zip(*xs))[0, 1])
res['area_corr_temporal_mediana'] = round(float(np.median(cors)), 2) if cors else None
res['frac_soja_media'] = round(float(np.mean([feno['%s_%d' % (ib, a)].get('frac_soja', 0) for ib in ibs for a in range(2012, 2025)])), 3)

# ---------- 3. backtest de produtividade
def serie(ib):
    p = os.path.join(RAW, FONTE, ib + '.json.gz')
    o = json.load(gzip.open(p, 'rt', encoding='utf-8'))
    s = ingestao.de_nasa_power(o) if FONTE == 'nasa_power' else ingestao.de_open_meteo(o)
    return ingestao.completar_eto(s, muns[ib]['lat'])[0]
obs = []
for ib in ibs:
    if not os.path.exists(os.path.join(RAW, FONTE, ib + '.json.gz')): continue
    s = serie(ib)
    for ano in range(2012, 2025):
        f = feno.get('%s_%d' % (ib, ano)); y = rend.get((ib, ano + 1))
        if not y or not f or 'semeadura_p50' not in f: continue
        # V0: calendario fixo
        sim0 = bh.simular(s, '%d-10-20' % ano, cad_mm=CAD)
        if sim0['dias_faltantes'] > 7: continue
        pct = {'p25': sh(f['semeadura_p25'], LAG), 'p50': sh(f['semeadura_p50'], LAG), 'p75': sh(f['semeadura_p75'], LAG)}
        ciclo = float(np.clip(f['ciclo_mediano'] - LAG, 90, 150))
        rs, falt = mh.razoes_coortes(s, cultivares.coortes(pct, ciclo_satelite=ciclo), CAD)
        rs150, _ = mh.razoes_coortes(s, cultivares.coortes(pct, ciclo_satelite=150), CAD)
        if rs is None: continue
        obs.append({'mun': ib, 'ano': ano + 1, 'y': y / 60.0, 'area': area.get((ib, ano + 1), 1),
                    'razoes0': bh.razoes(sim0), 'razoes_sat': rs, 'razoes_sat150': rs150,
                    'pico': f['pico_mediano'], 'integral': f['integral_mediana'],
                    'ciclo': f['ciclo_mediano'], 'sem_doy': datetime.date.fromisoformat(f['semeadura_p50']).timetuple().tm_yday})
for o in obs:
    o['sem_rel'] = o['sem_doy'] if o['sem_doy'] > 150 else o['sem_doy'] + 365
_por = collections.defaultdict(list)
for o in obs: _por[o['mun']].append(o)
for m, L in _por.items():
    for k in ('pico', 'integral', 'sem_rel'):
        mu = np.mean([x[k] for x in L]); sd = np.std([x[k] for x in L]) or 1.0
        for x in L: x[k + '_an'] = (x[k] - mu) / sd

def variante(nome, chave_r, extras, agua=True):
    for o in obs: o['razoes'] = o[chave_r]
    out = {}
    for prot in ('loyo', 'lomo'):
        p = mh.cv(obs, lambda: mh.Hibrido(usar_agua=agua, extras=extras), prot)
        m = avaliacao.metricas([x['y'] for x in p], [x['prev'] for x in p])
        out[prot] = {k: round(v, 3) for k, v in m.items() if k in ('rmse', 'mae', 'r2', 'vies')}
        if prot == 'loyo':
            anos = sorted(set(x['ano'] for x in p))
            o_ = [np.average([x['y'] for x in p if x['ano'] == a], weights=[x['area'] for x in p if x['ano'] == a]) for a in anos]
            p_ = [np.average([x['prev'] for x in p if x['ano'] == a], weights=[x['area'] for x in p if x['ano'] == a]) for a in anos]
            out['anual_corr'] = round(float(np.corrcoef(o_, p_)[0, 1]), 3)
            out['anual_rmse'] = round(float(np.sqrt(np.mean((np.array(o_) - np.array(p_)) ** 2))), 2)
            out['por_ano'] = {str(a): [round(x, 1), round(y_, 1)] for a, x, y_ in zip(anos, o_, p_)}
            md = collections.defaultdict(list)
            for x in p: md[x['mun']].append(x['y'])
            med = {k: np.median(v) for k, v in md.items()}
            tp = sum(x['y'] < .85 * med[x['mun']] and x['prev'] < .85 * med[x['mun']] for x in p)
            ob = sum(x['y'] < .85 * med[x['mun']] for x in p); al = sum(x['prev'] < .85 * med[x['mun']] for x in p)
            out['quebra'] = {'reais': int(ob), 'detectadas': int(tp), 'alarmes': int(al)}
    m = mh.Hibrido(usar_agua=agua, extras=extras).ajustar(obs)
    out['coef'] = m.coeficientes()
    res.setdefault('variantes', {})[nome] = out
    print(nome.ljust(34), 'LOYO', out['loyo']['rmse'], out['loyo']['r2'], '| LOMO', out['lomo']['rmse'], out['lomo']['r2'], '| anual r', out['anual_corr'], out['anual_rmse'], '| quebra', out['quebra'], flush=True)

res['n_obs'] = len(obs); res['n_mun'] = len(set(o['mun'] for o in obs))
print('obs', len(obs), 'mun', res['n_mun'], '| Deral erro medio pp', res['deral_erro_medio_pp'], 'rmse', res['deral_rmse_pp'], '| area corr', res['area_corr_temporal_mediana'])
for x in res['deral']: print('   ', x)
variante('so_tendencia', 'razoes0', (), agua=False)
variante('V0 calendario fixo 20/out', 'razoes0', ())
variante('V1a semeadura satelite, ciclo 150', 'razoes_sat150', ())
variante('V1 semeadura + ciclo satelite', 'razoes_sat', ())
variante('V2 V1 + vigor (pico, integral)', 'razoes_sat', ('pico', 'integral'))
variante('V3 so vigor', 'razoes_sat', ('pico', 'integral'), agua=False)
variante('V4 V2 + data de semeadura', 'razoes_sat', ('pico', 'integral', 'sem_rel'))
variante('V5 fixo + anomalia de vigor', 'razoes0', ('pico_an', 'integral_an'))
variante('V6 satelite + anomalias', 'razoes_sat', ('pico_an', 'integral_an', 'sem_rel_an'))
json.dump(res, open(os.path.join(BT, 'backtest_sat_%s_%s_%d_lag%d.json' % (INDICE, FONTE, CAD, LAG)), 'w'), indent=1)
