import os
import sys, json, numpy as np
sys.argv=['x','raw','nasa_power','11-01','42']
exec(open('analise.py').read().split('def ols(')[0])
from produtividade import experimentos
out=[]
# 26 municipios de maior area (como os 26 da tese)
top=sorted(muns, key=lambda k:-muns[k]['area'])[:26]
for ano in sorted(set(o['ano'] for o in obs)):
    oa=[o for o in obs if o['ano']==ano and o['mun'] in top]
    feats={o['mun']:o['feat'] for o in oa}
    agr=agrupamento.agrupar(feats,kmax=10,min_tamanho=2,seed=0)
    ks=[agr['fases'][i]['k'] for i in range(4)]
    G=[[agr['fases'][i]['labels'][o['mun']] for i in range(4)] for o in oa]
    real=avaliacao.protocolo_tese_in_sample(oa,G)
    # com k da tese (ate 12 grupos)
    kt=experimentos.K_TESE[2004]
    Gt=experimentos._grupos_forcados(oa,kt)
    rt=avaliacao.protocolo_tese_in_sample(oa,Gt)
    rng=np.random.default_rng(ano); al=[]; alt=[]
    for _ in range(40):
        al.append(avaliacao.protocolo_tese_in_sample(oa,[[int(rng.integers(0,k)) for k in ks] for _ in oa])['melhora_pct'])
        alt.append(avaliacao.protocolo_tese_in_sample(oa,[[int(rng.integers(0,k)) for k in kt] for _ in oa])['melhora_pct'])
    out.append((ano,len(oa),ks,round(real['melhora_pct'],1),round(np.mean(al),1),round(rt['melhora_pct'],1),round(np.mean(alt),1)))
    print(out[-1])
json.dump(out,open('tese_real.json','w'))
