# -*- coding: utf-8 -*-
"""Satelite (MODIS) + Jensen: fenologia por municipio-safra, validacao do
calendario contra o Deral e backtest de produtividade contra a PAM."""
import sys, os, json, gzip, glob, datetime, collections
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from produtividade import fenologia as fen, ingestao, balanco_hidrico as bh, config
from produtividade import modelo_hibrido as mh, avaliacao

BT = os.path.dirname(os.path.abspath(__file__))
MODIS = sys.argv[1]
RAW = os.path.join(BT, 'raw')
PIX_HA = 0.231656 ** 2 * 100
INDICE = os.environ.get('INDICE', 'evi')
PARAMS = fen.PARAMS_EVI if INDICE == 'evi' else fen.PARAMS_NDVI

def carregar(ibge):
    z = np.load(os.path.join(MODIS, ibge + '.npz'))
    Ts, Vs, Ok = [], [], []
    for prod in ('MOD13Q1', 'MYD13Q1'):
        if prod + '_datas' not in z: continue
        ds = z[prod + '_datas']
        v = z[prod + '_' + INDICE].astype(float)
        rel = z[prod + '_rel']; doy = z[prod + '_doy'].astype(int)
        y0 = np.array([int(d[1:5]) for d in ds]); d0 = np.array([int(d[5:]) for d in ds])
        base = np.array([datetime.date(a, 1, 1).toordinal() - 1 for a in y0])
        ano = np.where(doy < (d0[:, None] - 30), y0[:, None] + 1, y0[:, None])
        base_px = np.vectorize(lambda a: datetime.date(int(a), 1, 1).toordinal() - 1)(ano)
        t = np.where(doy > 0, base_px + doy, (base + d0 + 8)[:, None])
        ok = ((rel == 0) | (rel == 1)) & (v > -2000)
        Ts.append(t); Vs.append(v / 10000.0); Ok.append(ok)
    return np.vstack(Ts), np.vstack(Vs), np.vstack(Ok), z

if __name__ == '__main__':
    arquivos = sorted(glob.glob(os.path.join(MODIS, '*.npz')))
    muns = {m['ibge']: m for m in json.load(open(os.path.join(RAW, 'municipios_backtest.json'), encoding='utf-8'))}
    feno = {}
    for f in arquivos:
        ib = os.path.basename(f)[:-4]
        T, V, OK, z = carregar(ib)
        ultima = datetime.date.fromordinal(int(np.nanmax(T))).isoformat()
        for ano in range(2012, 2026):
            met = fen.pixels_temporada(T, V, OK, ano, PARAMS)
            ag = fen.agregar(met, PIX_HA)
            ag['ultima_obs'] = ultima
            # fracoes semeadas nas datas do Deral (estado)
            ag['semeado_em'] = {d: fen.fracao_semeada_ate(met, d) for d in (
                '%d-10-03' % ano, '%d-10-09' % ano, '%d-10-16' % ano, '%d-10-23' % ano, '%d-10-24' % ano, '%d-10-31' % ano)}
            # mascara de soja deste ano (para a temporada em curso)
            ag['_mask'] = [bool(m and m.get('soja')) for m in met]
            feno[(ib, ano)] = ag
        # temporada em curso (2026)
        mask = np.zeros(V.shape[1], bool)
        for ano in (2023, 2024, 2025):
            mask |= np.array(feno[(ib, ano)]['_mask'])
        hoje = ultima
        par = fen.emergencia_parcial(T[:, mask], V[:, mask], OK[:, mask], 2026, hoje, PARAMS)
        em = [p for p in par if p and p.get('emergido')]
        feno[(ib, 2026)] = {'ultima_obs': ultima, 'n_pixels_soja_hist': int(mask.sum()),
                            'frac_emergida': round(len(em) / max(sum(1 for p in par if p), 1), 3),
                            'semeadura_p50_parcial': (datetime.date.fromordinal(int(np.median([datetime.date.fromisoformat(p['semeadura']).toordinal() for p in em]))).isoformat() if em else None)}
        print(ib, muns[ib]['nome'], 'ultima', ultima, 'soja px 2024:', feno[(ib, 2024)]['n_soja'], '| 2026 emergido', feno[(ib, 2026)]['frac_emergida'], flush=True)
    out = {'%s_%d' % k: {kk: vv for kk, vv in v.items() if kk != '_mask'} for k, v in feno.items()}
    json.dump(out, open(os.path.join(BT, 'feno_%s.json' % INDICE), 'w'), indent=0, ensure_ascii=False)
